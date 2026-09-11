from __future__ import annotations

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.services.llm import get_llm_provider
from app.api.records import get_process_document_record, get_process_record
from app.db.session import Base, get_background_session_factory, get_db
from app.main import app
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.feed_item import FeedItem
from app.models.feed_refresh_state import FeedRefreshState
from app.models.gap_period import GapPeriod
from app.models.generated_document import GeneratedDocument
from app.models.generated_paragraph import GeneratedParagraph
from app.models.generated_sentence import GeneratedSentence
from app.models.interview_answer import InterviewAnswer
from app.models.record import Record
from app.models.record_chunk import RecordChunk
from app.models.refresh_token import RefreshToken
from app.models.session import Session as SessionModel
from app.models.user import User
from app.models.user_attribute import UserAttribute
from app.models.user_consent import UserConsent
from app.models.user_preference import UserPreference
from app.services.embedding import get_embedding_provider
from app.services.profile.attributes import get_profile_extractor
from app.services.feed.ingest import get_feed_refresher
from app.services.feed.profile_adapter import get_profile_embedder
from app.services.llm.base import (
    LLMUnavailableError,
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
    """Deterministic stand-in for LocalOllamaProvider — the interview loop must be
    verifiable with stub text before real Ollama calls are involved.
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
        job_info_relevant_indices: list[int] | None = None,
        job_info_query_params=None,
        draft_job_info_query: str | None = None,
        activity_period=None,
        probe_question: str | None = None,
        profile_attributes: list[list] | None = None,
    ):
        self._profile_attributes_queue = list(profile_attributes) if profile_attributes else None
        self.profile_attribute_calls: list[tuple[str, list[str], bool]] = []
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
        self._job_info_relevant_indices = job_info_relevant_indices
        self._job_info_query_params = job_info_query_params
        self._draft_job_info_query = draft_job_info_query
        # 기본 None = "기간을 알 수 없다" — 커버리지를 다루는 테스트만 명시적으로 준다.
        self._activity_period = activity_period
        # 기본 None = "되묻는 질문을 못 만들었다" — 라우터가 그걸 정적 예시
        # 폴백으로 처리하는지 확인하는 게 기본 경로다.
        self._probe_question = probe_question
        self.probe_question_calls: list[str] = []
        self.probe_focus_calls: list[str] = []
        self.activity_period_calls: list[str] = []
        self.job_info_query_calls: list[str] = []
        self.select_relevant_calls: list[tuple] = []
        self.extract_query_params_calls: list[tuple] = []
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

    async def extract_activity_period(self, category_label, facts, gap_start, gap_end):
        self.activity_period_calls.append(category_label)
        return self._activity_period

    async def probe_activity_question(self, free_text, gap_start, gap_end, focus):
        self.probe_question_calls.append(free_text)
        self.probe_focus_calls.append(focus)
        if self._probe_question is None:
            raise LLMUnavailableError("fake: no probe question configured")
        return self._probe_question

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

    async def extract_job_info_query_params(self, query, known_regions):
        from app.services.llm.base import JobInfoQueryParams

        self.extract_query_params_calls.append((query, known_regions))
        if self._job_info_query_params is not None:
            return self._job_info_query_params
        # 기본값은 "조건 없음" — 카테고리 라우팅/집계만 보는 테스트가 이걸
        # 일일이 설정하지 않아도 되게 한다(조건 없이 조회하던 예전 동작과 동일).
        return JobInfoQueryParams()

    async def select_relevant_job_info_results(self, query, category_label, candidates):
        self.select_relevant_calls.append((query, category_label, candidates))
        if self._job_info_relevant_indices is not None:
            return self._job_info_relevant_indices
        # Default: everything the client fetched is "relevant" — tests that
        # only care about category routing/aggregation don't need to also
        # configure this.
        return [c.index for c in candidates]

    async def draft_job_info_query_from_facts(self, confirmed_facts):
        self.draft_job_info_query_calls.append(confirmed_facts)
        if self._draft_job_info_query is not None:
            return self._draft_job_info_query
        return ""

    async def extract_profile_attributes(self, text, known, allow_sensitive):
        self.profile_attribute_calls.append((text, list(known), allow_sensitive))
        if self._profile_attributes_queue:
            return self._profile_attributes_queue.pop(0)
        return []

    async def health_check(self) -> bool:
        return True


class FakeEmbeddingProvider:
    """Deterministic stand-in for LocalOllamaEmbedding used by consistency_check —
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


class FakeFeedRefresher:
    """수집 워커 대역. 호출만 기록하고 네트워크는 건드리지 않는다.

    실제 refresh_feed_if_stale은 자기 DB 세션을 열기 때문에 get_db 오버라이드
    만으로는 못 막는다 — get_feed_refresher 훅이 존재하는 이유다.
    """

    def __init__(self):
        self.calls = 0

    async def __call__(self):
        self.calls += 1


class FakeProfileEmbedder:
    def __init__(self):
        self.calls: list = []

    async def __call__(self, user_id):
        self.calls.append(user_id)


class FakeProfileExtractor:
    """속성 추출 워커 대역. 진짜 워커는 자기 DB 세션(AsyncSessionLocal)을 열어
    get_db 오버라이드를 우회하므로, 테스트에서는 호출만 기록한다."""

    def __init__(self):
        self.calls: list[tuple] = []

    async def __call__(self, user_id, source_kind, text, source_answer_id=None):
        self.calls.append((user_id, source_kind, text, source_answer_id))


@pytest.fixture
def feed_client():
    """피드 API용. 벡터 테이블 두 개(feed_item_embeddings /
    user_profile_embeddings)는 **일부러 만들지 않는다** — pgvector의 Vector는
    SQLite 컴파일러가 없다. 덕분에 이 픽스처는 프로덕션의 폴백 경로(벡터 질의
    실패 -> 최신순)를 자연스럽게 그대로 태운다.

    get_feed_ranker는 오버라이드하지 않는다 — 진짜 최신순 SQL(`.id`
    타이브레이커 포함)이 SQLite에서 실제로 돌아야 페이지네이션 회귀를 잡는다.
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
        InterviewAnswer.__table__,
        UserPreference.__table__,
        UserAttribute.__table__,
        UserConsent.__table__,
        FeedItem.__table__,
        FeedRefreshState.__table__,
    ]

    async def _create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=tables)

    asyncio.run(_create_tables())

    test_session_local = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with test_session_local() as session:
            yield session

    fake_refresher = FakeFeedRefresher()
    fake_embedder = FakeProfileEmbedder()
    fake_extractor = FakeProfileExtractor()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_feed_refresher] = lambda: fake_refresher
    app.dependency_overrides[get_profile_embedder] = lambda: fake_embedder
    app.dependency_overrides[get_profile_extractor] = lambda: fake_extractor
    try:
        with TestClient(app) as test_client:
            test_client.session_local = test_session_local
            test_client.fake_refresher = fake_refresher
            test_client.fake_embedder = fake_embedder
            test_client.fake_extractor = fake_extractor
            yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@pytest.fixture
def session_client():
    """Like `client`, but with the session/interview model graph created and
    the LLM + embedding-search dependencies stubbed out (no real Ollama/
    pgvector required to exercise the state machine).
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
        InterviewAnswer.__table__,
        UserPreference.__table__,
        UserAttribute.__table__,
        UserConsent.__table__,
        # Empty but must exist: deleting a Session lazy-loads these
        # cascade="all, delete-orphan" relationships even with zero rows.
        Record.__table__,
        GeneratedDocument.__table__,
        GeneratedParagraph.__table__,
        # 카테고리를 지울 때 ActivityCategory.generated_sentences(cascade
        # all, delete-orphan)를 lazy-load하므로 행이 없어도 테이블은 있어야 한다 —
        # 세션 삭제가 이 경로를 탄다.
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

    async def override_chunk_search(session_id, category_id, query_text=None):
        return []

    app.dependency_overrides[get_db] = override_get_db
    # confirm 뒤 백그라운드 기간 추론이 같은 테스트 DB에 쓰게 한다.
    app.dependency_overrides[get_background_session_factory] = lambda: test_session_local
    fake_extractor = FakeProfileExtractor()

    app.dependency_overrides[get_llm_provider] = lambda: fake_llm
    app.dependency_overrides[get_chunk_search] = lambda: override_chunk_search
    app.dependency_overrides[get_profile_extractor] = lambda: fake_extractor
    try:
        with TestClient(app) as test_client:
            test_client.fake_llm = fake_llm
            test_client.fake_extractor = fake_extractor
            test_client.session_local = test_session_local
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
        InterviewAnswer.__table__,
        UserPreference.__table__,
        UserAttribute.__table__,
        UserConsent.__table__,
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
    process_document_record_calls: list = []

    async def fake_process_record(record_id):
        process_record_calls.append(record_id)
        async with test_session_local() as session:
            record = await session.get(Record, record_id)
            if record is not None:
                record.parse_status = "DONE"
                record.raw_text = record.raw_text or "parsed text"
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
    app.dependency_overrides[get_process_document_record] = lambda: fake_process_document_record
    app.dependency_overrides[get_storage] = lambda: fake_storage
    app.dependency_overrides[get_profile_extractor] = lambda: FakeProfileExtractor()
    try:
        with TestClient(app) as test_client:
            test_client.fake_storage = fake_storage
            test_client.process_record_calls = process_record_calls
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
    export) without real Ollama/pgvector.
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
        InterviewAnswer.__table__,
        UserPreference.__table__,
        UserAttribute.__table__,
        UserConsent.__table__,
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

    async def override_chunk_search(session_id, category_id, query_text=None):
        return []

    async def override_fact_citations(fact_ids, db):
        return {}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_background_session_factory] = lambda: test_session_local
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm
    app.dependency_overrides[get_embedding_provider] = lambda: fake_embedding
    app.dependency_overrides[get_chunk_search] = lambda: override_chunk_search
    app.dependency_overrides[get_fact_citations] = lambda: override_fact_citations
    app.dependency_overrides[get_profile_extractor] = lambda: FakeProfileExtractor()
    try:
        with TestClient(app) as test_client:
            test_client.fake_llm = fake_llm
            test_client.fake_embedding = fake_embedding
            yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
