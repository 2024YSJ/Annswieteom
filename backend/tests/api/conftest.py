from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.interview import get_llm_provider
from app.api.records import get_process_image_record, get_process_record
from app.db.session import Base, get_db
from app.main import app
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.gap_period import GapPeriod
from app.models.generated_document import GeneratedDocument
from app.models.record import Record
from app.models.record_chunk import RecordChunk
from app.models.refresh_token import RefreshToken
from app.models.session import Session as SessionModel
from app.models.user import User
from app.services.llm.base import Suggestion, BasedOn
from app.services.record_pipeline.search import get_chunk_search
from app.services.storage import get_storage


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


class FakeStorage:
    """In-memory stand-in for SupabaseStorage — no real network calls in tests."""

    def __init__(self):
        self.uploaded: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def upload(self, path: str, content: bytes, content_type: str) -> None:
        self.uploaded[path] = content

    async def download(self, path: str) -> bytes:
        return self.uploaded.get(path, b"")

    async def delete(self, path: str) -> None:
        self.deleted.append(path)
        self.uploaded.pop(path, None)

    async def create_signed_url(self, path: str, expires_in: int = 3600) -> str:
        return f"https://fake.storage.test/{path}?expires_in={expires_in}"


@pytest.fixture
def records_client():
    """Like `session_client`, but also stands in for the record pipeline's
    background tasks and Supabase Storage — so records tests can exercise
    the full create -> (fake) parse -> poll flow without a real DB session
    outside the request/response cycle, real network calls, or pgvector.
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
        Record.__table__,
        # Empty but must exist: deleting a Record lazy-loads this
        # cascade="all, delete-orphan" relationship even with zero rows.
        RecordChunk.__table__,
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

    process_record_calls: list = []
    process_image_record_calls: list = []

    async def fake_process_record(record_id):
        process_record_calls.append(record_id)
        async with test_session_local() as session:
            record = await session.get(Record, record_id)
            if record is not None:
                record.parse_status = "DONE"
                record.raw_text = record.raw_text or "parsed text"
                await session.commit()

    async def fake_process_image_record(record_id):
        process_image_record_calls.append(record_id)
        async with test_session_local() as session:
            record = await session.get(Record, record_id)
            if record is not None:
                record.parse_status = "DONE"
                record.raw_text = "ocr text"
                await session.commit()

    fake_storage = FakeStorage()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_process_record] = lambda: fake_process_record
    app.dependency_overrides[get_process_image_record] = lambda: fake_process_image_record
    app.dependency_overrides[get_storage] = lambda: fake_storage
    try:
        with TestClient(app) as test_client:
            test_client.fake_storage = fake_storage
            test_client.process_record_calls = process_record_calls
            test_client.process_image_record_calls = process_image_record_calls
            yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
