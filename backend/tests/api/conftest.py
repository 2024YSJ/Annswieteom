from __future__ import annotations

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.services.llm.fallback import get_llm_provider
from app.api.records import get_process_document_record, get_process_image_record, get_process_record
from app.db.session import Base, get_db
from app.main import app
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.gap_period import GapPeriod
from app.models.generated_document import GeneratedDocument
from app.models.generated_paragraph import GeneratedParagraph
from app.models.generated_sentence import GeneratedSentence
from app.models.record import Record
from app.models.record_chunk import RecordChunk
from app.models.refresh_token import RefreshToken
from app.models.session import Session as SessionModel
from app.models.user import User
from app.services.embedding import get_embedding_provider
from app.services.llm.base import (
    BasedOn,
    CategorySuggestion,
    DraftDocument,
    DrilldownDecision,
    FactCandidate,
    JobInfoCategoryQuery,
    ParagraphDraft,
    PeriodSuggestion,
    SentenceWithEvidence,
    SufficiencyResult,
)

_DEFAULT_PERIOD_SUGGESTION = object()  # sentinel: "use the built-in default", distinct from an explicit None
from app.services.record_pipeline.citation import get_fact_citations
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
    """Deterministic stand-in for FallbackProvider — the interview loop must be
    verifiable with stub text before real Gemini/Ollama calls are involved.
    Each extract_facts call returns a fixed single generic-pattern candidate
    (fact_type mirrors the question's fact_type_hint isn't known to the fake,
    so tests that care about a specific fact_type queue an explicit candidate
    list) unless a queue of canned candidate-lists is provided.
    """

    def __init__(
        self,
        fact_candidates: list[list[FactCandidate]] | None = None,
        followup_questions: list[str] | None = None,
        sufficiency_results: list[SufficiencyResult] | None = None,
        draft_answers: list[str] | None = None,
        documents: list[DraftDocument] | None = None,
        category_suggestions: list | None = None,
        period_suggestion=_DEFAULT_PERIOD_SUGGESTION,
        drilldown_decisions: list[DrilldownDecision] | None = None,
        activity_items: list[list[str]] | None = None,
        job_info_categories: list["JobInfoCategoryQuery"] | None = None,
        draft_job_info_query: str | None = None,
    ):
        self._facts_queue = list(fact_candidates) if fact_candidates else None
        self._followup_queue = list(followup_questions) if followup_questions else None
        self._sufficiency_queue = list(sufficiency_results) if sufficiency_results else None
        self._draft_answer_queue = list(draft_answers) if draft_answers else None
        self._document_queue = list(documents) if documents else None
        self._category_suggestions = category_suggestions
        self._period_suggestion = period_suggestion
        self._drilldown_queue = list(drilldown_decisions) if drilldown_decisions else None
        self._activity_items_queue = list(activity_items) if activity_items else None
        self._job_info_categories = job_info_categories
        self._draft_job_info_query = draft_job_info_query
        self.job_info_query_calls: list[str] = []
        self.draft_job_info_query_calls: list[list] = []
        self.activity_items_calls: list[tuple[str, str]] = []
        self.extract_facts_calls: list[tuple[str, str, str]] = []
        self.followup_calls: list[str] = []
        self.sufficiency_calls: list[str] = []
        self.draft_answer_calls: list[str] = []
        self.document_calls: list[tuple[list[str], str]] = []
        self.extract_calls: list[str] = []
        self.period_calls: list[str] = []
        self.drilldown_calls: list[str] = []

    async def draft_answer(self, context, question_text):
        self.draft_answer_calls.append(question_text)
        if self._draft_answer_queue:
            return self._draft_answer_queue.pop(0)
        return f"({question_text}에 대한 AI 초안)"

    async def extract_facts(self, context, question_text, answer_text, fact_type_hint):
        self.extract_facts_calls.append((context.category_label, question_text, answer_text))
        if self._facts_queue:
            return self._facts_queue.pop(0)
        if not answer_text.strip():
            return []
        return [FactCandidate(content=answer_text, fact_type=fact_type_hint, based_on=BasedOn(type="generic_pattern"))]

    async def extract_activity_items(self, category_label, answer_text):
        self.activity_items_calls.append((category_label, answer_text))
        if self._activity_items_queue:
            return self._activity_items_queue.pop(0)
        return []

    async def followup_question(self, context):
        self.followup_calls.append(context.category_label)
        if self._followup_queue:
            return self._followup_queue.pop(0)
        return f"{context.category_label}에 대해 더 이야기해 주실 수 있나요?"

    async def judge_sufficiency(self, context):
        self.sufficiency_calls.append(context.category_label)
        if self._sufficiency_queue:
            return self._sufficiency_queue.pop(0)
        return SufficiencyResult(sufficient=True, reason="충분한 정보가 모였습니다")

    async def judge_drilldown(self, context):
        self.drilldown_calls.append(context.category_label)
        if self._drilldown_queue:
            return self._drilldown_queue.pop(0)
        # Default: never interject a drill-down — tests that want to exercise
        # the interleaved drill-down path queue an explicit DrilldownDecision.
        return DrilldownDecision(should_ask=False)

    async def generate_document(self, facts, tone, category_label):
        self.document_calls.append(([f.id for f in facts], tone))
        if self._document_queue:
            return self._document_queue.pop(0)
        # Default: one paragraph holding all facts, one sentence per fact
        # (citing that fact only) — keeps existing single-paragraph-shaped
        # tests passing while still exercising the paragraph structure.
        return DraftDocument(paragraphs=[
            ParagraphDraft(
                topic=category_label,
                sentences=[
                    SentenceWithEvidence(text=f"[{tone}] {f.content}", fact_indices=[i])
                    for i, f in enumerate(facts)
                ],
            )
        ])

    async def extract_categories(self, free_text, gap_start, gap_end):
        self.extract_calls.append(free_text)
        if self._category_suggestions is not None:
            return self._category_suggestions
        return [CategorySuggestion(category_type="part_time", custom_label="편의점 아르바이트")]

    async def extract_period(self, free_text, today):
        self.period_calls.append(free_text)
        if self._period_suggestion is _DEFAULT_PERIOD_SUGGESTION:
            return PeriodSuggestion(start_date=date(2025, 1, 1), end_date=date(2025, 6, 30))
        return self._period_suggestion

    async def classify_job_info_query(self, query):
        self.job_info_query_calls.append(query)
        if self._job_info_categories is not None:
            return self._job_info_categories
        return []

    async def draft_job_info_query_from_facts(self, confirmed_facts):
        self.draft_job_info_query_calls.append(confirmed_facts)
        if self._draft_job_info_query is not None:
            return self._draft_job_info_query
        return ""

    async def health_check(self) -> bool:
        return True


class FakeEmbeddingProvider:
    """Deterministic stand-in for FallbackEmbedding used by consistency_check —
    every text maps to the same default vector unless overridden, so cosine
    similarity is 1.0 (passes) by default. Tests that need a
    consistency_check_passed=False case register a distinct vector for that
    one sentence.
    """

    model_name = "fake"

    def __init__(self, vectors: dict[str, list[float]] | None = None, default: list[float] | None = None):
        self._vectors = vectors or {}
        self._default = default or [1.0, 0.0]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors.get(t, self._default) for t in texts]

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
        GeneratedParagraph.__table__,
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
        GeneratedParagraph.__table__,
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
    process_document_record_calls: list = []

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

    async def fake_process_document_record(record_id):
        process_document_record_calls.append(record_id)
        async with test_session_local() as session:
            record = await session.get(Record, record_id)
            if record is not None:
                record.parse_status = "DONE"
                record.raw_text = "document text"
                await session.commit()

    fake_storage = FakeStorage()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_process_record] = lambda: fake_process_record
    app.dependency_overrides[get_process_image_record] = lambda: fake_process_image_record
    app.dependency_overrides[get_process_document_record] = lambda: fake_process_document_record
    app.dependency_overrides[get_storage] = lambda: fake_storage
    try:
        with TestClient(app) as test_client:
            test_client.fake_storage = fake_storage
            test_client.process_record_calls = process_record_calls
            test_client.process_image_record_calls = process_image_record_calls
            test_client.process_document_record_calls = process_document_record_calls
            yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@pytest.fixture
def document_client():
    """Like `session_client`, but with generated_documents/generated_sentences
    tables and fake LLM + embedding providers so document generation (B-4) can
    be driven end to end (generate -> regenerate -> patch -> finalize ->
    export) without real Ollama/Gemini/pgvector.
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
        RecordChunk.__table__,
        GeneratedDocument.__table__,
        GeneratedParagraph.__table__,
        GeneratedSentence.__table__,
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
    fake_embedding = FakeEmbeddingProvider()

    async def override_chunk_search(session_id, label):
        return []

    async def override_fact_citations(fact_ids, db):
        return {}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm
    app.dependency_overrides[get_embedding_provider] = lambda: fake_embedding
    app.dependency_overrides[get_chunk_search] = lambda: override_chunk_search
    app.dependency_overrides[get_fact_citations] = lambda: override_fact_citations
    try:
        with TestClient(app) as test_client:
            test_client.fake_llm = fake_llm
            test_client.fake_embedding = fake_embedding
            yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
