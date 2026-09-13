from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.user_attribute import UserAttribute
from app.models.user_consent import UserConsent
from app.models.user_occupation_embedding import UserOccupationEmbedding
from app.services.feed import occupation_adapter
from app.services.feed.occupation_adapter import (
    load_occupation_vector,
    occupation_needs_refresh,
    refresh_occupation_embedding,
)
from app.services.profile.attributes import add_user_value


@pytest.fixture
def db_maker():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[UserAttribute.__table__, UserConsent.__table__, UserOccupationEmbedding.__table__],
            )

    asyncio.run(_create())
    yield maker
    asyncio.run(engine.dispose())


@pytest.fixture
def no_table_maker():
    """user_occupation_embeddings가 아예 없는 DB(pgvector 없는 SQLite/마이그레이션
    이전) — 500이 되면 안 되고 "갱신 필요"로 폴백해야 한다는 계약을 지킨다."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[UserAttribute.__table__, UserConsent.__table__])

    asyncio.run(_create())
    yield maker
    asyncio.run(engine.dispose())


class FakeEmbeddingProvider:
    """LocalOllamaEmbedding 대신 주입 — 실제 Ollama 호출 없이 임베딩 함수의
    호출 여부/횟수/전달값만 검증한다."""

    def __init__(self, vectors=None, fail=False):
        self._vectors = vectors
        self.fail = fail
        self.calls: list[list[str]] = []
        self.model_name = "fake-bge-m3"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return self._vectors or [[0.1, 0.2] for _ in texts]


# ── occupation_needs_refresh ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_desired_job_never_needs_refresh(db_maker):
    async with db_maker() as db:
        assert await occupation_needs_refresh(db, uuid.uuid4(), None) is False
        assert await occupation_needs_refresh(db, uuid.uuid4(), "  ") is False


@pytest.mark.asyncio
async def test_no_row_needs_refresh(db_maker):
    async with db_maker() as db:
        assert await occupation_needs_refresh(db, uuid.uuid4(), "백엔드 프로그래머") is True


@pytest.mark.asyncio
async def test_stale_source_text_needs_refresh(db_maker):
    async with db_maker() as db:
        user_id = uuid.uuid4()
        db.add(UserOccupationEmbedding(user_id=user_id, embedding=[0.1], source_text="회계사"))
        await db.commit()
        assert await occupation_needs_refresh(db, user_id, "백엔드 프로그래머") is True


@pytest.mark.asyncio
async def test_matching_source_text_does_not_need_refresh(db_maker):
    async with db_maker() as db:
        user_id = uuid.uuid4()
        db.add(UserOccupationEmbedding(user_id=user_id, embedding=[0.1], source_text="백엔드 프로그래머"))
        await db.commit()
        assert await occupation_needs_refresh(db, user_id, "백엔드 프로그래머") is False


@pytest.mark.asyncio
async def test_missing_table_needs_refresh(no_table_maker):
    async with no_table_maker() as db:
        assert await occupation_needs_refresh(db, uuid.uuid4(), "백엔드 프로그래머") is True


# ── load_occupation_vector ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_occupation_vector_missing_table_returns_none(no_table_maker):
    async with no_table_maker() as db:
        assert await load_occupation_vector(db, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_load_occupation_vector_returns_stored_embedding(db_maker):
    async with db_maker() as db:
        user_id = uuid.uuid4()
        db.add(UserOccupationEmbedding(user_id=user_id, embedding=[0.3, 0.4], source_text="백엔드 프로그래머"))
        await db.commit()
        assert await load_occupation_vector(db, user_id) == [0.3, 0.4]


# ── refresh_occupation_embedding ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_skips_when_desired_job_unchanged(db_maker, monkeypatch):
    monkeypatch.setattr(occupation_adapter, "AsyncSessionLocal", db_maker)
    fake = FakeEmbeddingProvider()
    monkeypatch.setattr(occupation_adapter, "LocalOllamaEmbedding", lambda: fake)

    user_id = uuid.uuid4()
    async with db_maker() as db:
        await add_user_value(db, user_id, "desired_job", "백엔드 프로그래머")
        db.add(UserOccupationEmbedding(user_id=user_id, embedding=[0.9], source_text="백엔드 프로그래머"))
        await db.commit()

    await refresh_occupation_embedding(user_id)

    assert fake.calls == []


@pytest.mark.asyncio
async def test_refresh_embeds_and_upserts_when_desired_job_changed(db_maker, monkeypatch):
    monkeypatch.setattr(occupation_adapter, "AsyncSessionLocal", db_maker)
    fake = FakeEmbeddingProvider(vectors=[[0.5, 0.6]])
    monkeypatch.setattr(occupation_adapter, "LocalOllamaEmbedding", lambda: fake)

    user_id = uuid.uuid4()
    async with db_maker() as db:
        await add_user_value(db, user_id, "desired_job", "백엔드 프로그래머")
        await db.commit()

    await refresh_occupation_embedding(user_id)

    assert fake.calls == [["백엔드 프로그래머"]]
    async with db_maker() as db:
        vector = await load_occupation_vector(db, user_id)
    assert vector == [0.5, 0.6]


@pytest.mark.asyncio
async def test_refresh_leaves_no_row_when_embedding_fails(db_maker, monkeypatch):
    monkeypatch.setattr(occupation_adapter, "AsyncSessionLocal", db_maker)
    fake = FakeEmbeddingProvider(fail=True)
    monkeypatch.setattr(occupation_adapter, "LocalOllamaEmbedding", lambda: fake)

    user_id = uuid.uuid4()
    async with db_maker() as db:
        await add_user_value(db, user_id, "desired_job", "백엔드 프로그래머")
        await db.commit()

    await refresh_occupation_embedding(user_id)

    async with db_maker() as db:
        assert await load_occupation_vector(db, user_id) is None


@pytest.mark.asyncio
async def test_refresh_does_nothing_without_a_desired_job(db_maker, monkeypatch):
    monkeypatch.setattr(occupation_adapter, "AsyncSessionLocal", db_maker)
    fake = FakeEmbeddingProvider()
    monkeypatch.setattr(occupation_adapter, "LocalOllamaEmbedding", lambda: fake)

    await refresh_occupation_embedding(uuid.uuid4())

    assert fake.calls == []
