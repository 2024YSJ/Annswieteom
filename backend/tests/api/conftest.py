from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.interview import get_llm_provider
from app.db.session import Base, get_db
from app.main import app
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.gap_period import GapPeriod
from app.models.generated_document import GeneratedDocument
from app.models.record import Record
from app.models.refresh_token import RefreshToken
from app.models.session import Session as SessionModel
from app.models.user import User
from app.services.llm.base import Suggestion, BasedOn
from app.services.record_pipeline.search import get_chunk_search


@pytest.fixture
def client():
    """A TestClient wired to a fresh in-memory SQLite DB per test.

    Only the users/refresh_tokens tables are created (not the full model
    graph) since some other tables use pgvector's Vector type, which has no
    SQLite compiler.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def _create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[User.__table__, RefreshToken.__table__])

    asyncio.run(_create_tables())

    test_session_local = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with test_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


class FakeLLMProvider:
    """Deterministic stand-in for FallbackProvider (spec 02_interview §6:
    the state machine must be verifiable with stub text before A's real LLM
    is wired in). Each draft_suggestion call returns a fixed generic-pattern
    suggestion unless a queue of canned suggestions is provided.
    """

    def __init__(self, suggestions: list[Suggestion] | None = None):
        self._queue = list(suggestions) if suggestions else None
        self.calls: list[tuple[str, str]] = []

    async def draft_suggestion(self, context, step):
        self.calls.append((context.category_label, step))
        if self._queue:
            return self._queue.pop(0)
        return Suggestion(draft_text=f"dummy {step} draft", based_on=BasedOn(type="generic_pattern"))

    async def generate_document(self, facts, tone):
        raise NotImplementedError

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def session_client():
    """Like `client`, but with the session/interview model graph created and
    the LLM + embedding-search dependencies stubbed out (no real Ollama/
    Gemini/pgvector required to exercise the state machine).
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    tables = [
        User.__table__,
        RefreshToken.__table__,
        SessionModel.__table__,
        GapPeriod.__table__,
        ActivityCategory.__table__,
        ConfirmedFact.__table__,
        # Empty but must exist: deleting a Session lazy-loads these
        # cascade="all, delete-orphan" relationships even with zero rows.
        Record.__table__,
        GeneratedDocument.__table__,
    ]

    async def _create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=tables)

    asyncio.run(_create_tables())

    test_session_local = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with test_session_local() as session:
            yield session

    fake_llm = FakeLLMProvider()

    async def override_chunk_search(session_id, label):
        return []

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm
    app.dependency_overrides[get_chunk_search] = lambda: override_chunk_search
    try:
        with TestClient(app) as test_client:
            test_client.fake_llm = fake_llm
            yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
