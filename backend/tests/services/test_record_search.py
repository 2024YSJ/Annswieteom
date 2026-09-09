"""기록물 청크 검색 (2026-09-09).

2026-09-09 전까지 `search_relevant_chunks`는 카테고리에 붙은 청크를 작성순으로
5개 자르는 게 전부였고, `record_chunks.embedding`과 그 ivfflat 인덱스는 파이프라인이
쓰기만 하고 아무도 읽지 않았다 — 긴 블로그 글은 질문이 무엇이든 늘 앞쪽 청크만
근거로 올라왔다. 여기서 검증하는 건 세 층의 우선순위와, 각 층이 실패했을 때
인터뷰 턴을 죽이지 않고 다음 층으로 내려가는지다.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.record import Record
from app.models.record_chunk import RecordChunk
from app.models.session import Session as SessionModel
from app.models.user import User
from app.services.record_pipeline import search as search_module
from app.services.record_pipeline.search import find_uncited_chunks, search_relevant_chunks


class FakeEmbedding:
    model_name = "fake"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("embedding provider down")
        return [[1.0] * 1024 for _ in texts]

    async def health_check(self) -> bool:
        return not self.fail


@pytest.fixture
def db_factory(monkeypatch):
    """search_relevant_chunks는 요청 밖에서도 돌 수 있어야 해서 get_db가 아니라
    AsyncSessionLocal을 직접 연다 — 테스트에서는 그 이름을 갈아끼운다."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        User.__table__,
        SessionModel.__table__,
        ActivityCategory.__table__,
        ConfirmedFact.__table__,
        Record.__table__,
        RecordChunk.__table__,
    ]

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=tables)

    asyncio.run(_create())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(search_module, "AsyncSessionLocal", factory)
    try:
        yield factory
    finally:
        asyncio.run(engine.dispose())


@pytest.fixture
def world(db_factory):
    """사용자 1명, 세션 1개, 카테고리 2개, 카테고리별 청크 2개씩."""
    ids = {}

    async def _seed():
        async with db_factory() as db:
            user = User(nickname="tester")
            db.add(user)
            await db.flush()
            session = SessionModel(user_id=user.id)
            db.add(session)
            await db.flush()

            for key, order in (("a", 0), ("b", 1)):
                category = ActivityCategory(session_id=session.id, category_type="study", order_index=order)
                db.add(category)
                await db.flush()
                record = Record(session_id=session.id, category_id=category.id, record_type="text")
                db.add(record)
                await db.flush()
                for index in range(2):
                    chunk = RecordChunk(
                        record_id=record.id,
                        chunk_text=f"{key}-청크-{index}",
                        chunk_index=index,
                    )
                    db.add(chunk)
                    await db.flush()
                    ids[f"chunk_{key}{index}"] = chunk.id
                ids[f"category_{key}"] = category.id
            ids["session"] = session.id
            await db.commit()

    asyncio.run(_seed())
    return ids


def test_returns_only_this_categorys_chunks(world):
    excerpts = asyncio.run(search_relevant_chunks(world["session"], world["category_a"]))
    assert [e.text for e in excerpts] == ["a-청크-0", "a-청크-1"]


def test_falls_back_to_the_whole_session_when_the_category_has_none(world, db_factory):
    """사용자가 기록물을 '엉뚱한' 카테고리에 붙이는 일은 흔하다 — 다른 데서
    온 근거 하나가 근거 없음보다 낫다."""
    empty_category_id = uuid.uuid4()

    async def _add_empty_category():
        async with db_factory() as db:
            db.add(ActivityCategory(
                id=empty_category_id,
                session_id=world["session"],
                category_type="study",
                order_index=2,
            ))
            await db.commit()

    asyncio.run(_add_empty_category())

    excerpts = asyncio.run(search_relevant_chunks(world["session"], empty_category_id))
    assert {e.text for e in excerpts} == {"a-청크-0", "a-청크-1", "b-청크-0", "b-청크-1"}


def test_query_text_is_embedded_before_searching(world):
    """질문 문구가 실제로 임베딩되는지 — 이게 안 되면 '벡터 검색'이 이름뿐이다."""
    provider = FakeEmbedding()
    asyncio.run(search_relevant_chunks(
        world["session"], world["category_a"], query_text="가장 힘들었던 점은?", embedding_provider=provider
    ))
    assert provider.calls == [["가장 힘들었던 점은?"]]


def test_vector_search_failure_falls_back_to_recency_instead_of_erroring(world):
    """SQLite에는 pgvector 연산자가 없다 — 실제로도 인덱스 부재/차원 불일치로
    벡터 질의가 깨질 수 있고, 그때 사용자가 잃는 건 근거 정렬 품질이지
    인터뷰 턴 자체가 아니어야 한다."""
    excerpts = asyncio.run(search_relevant_chunks(
        world["session"], world["category_a"], query_text="아무 질문", embedding_provider=FakeEmbedding()
    ))
    assert [e.text for e in excerpts] == ["a-청크-0", "a-청크-1"]


def test_embedding_provider_outage_falls_back_to_recency(world):
    provider = FakeEmbedding(fail=True)
    excerpts = asyncio.run(search_relevant_chunks(
        world["session"], world["category_a"], query_text="아무 질문", embedding_provider=provider
    ))
    assert [e.text for e in excerpts] == ["a-청크-0", "a-청크-1"]


def test_top_k_limits_the_result(world):
    excerpts = asyncio.run(search_relevant_chunks(world["session"], world["category_a"], top_k=1))
    assert len(excerpts) == 1


def test_find_uncited_chunks_excludes_what_a_fact_already_cited(world, db_factory):
    async def _cite_one():
        async with db_factory() as db:
            db.add(ConfirmedFact(
                category_id=world["category_a"],
                fact_type="task",
                content="이 청크에서 나온 사실",
                source_type="record_cited",
                source_record_chunk_id=world["chunk_a0"],
            ))
            await db.commit()

    asyncio.run(_cite_one())

    async def _find():
        async with db_factory() as db:
            return await find_uncited_chunks(world["session"], db)

    excerpts = asyncio.run(_find())
    assert "a-청크-0" not in [e.text for e in excerpts]
    assert {e.text for e in excerpts} == {"a-청크-1", "b-청크-0", "b-청크-1"}


def test_find_uncited_chunks_spans_every_category_in_the_session(world, db_factory):
    async def _find():
        async with db_factory() as db:
            return await find_uncited_chunks(world["session"], db)

    excerpts = asyncio.run(_find())
    assert len(excerpts) == 4
