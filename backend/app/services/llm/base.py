from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass
class RecordExcerpt:
    chunk_id: str
    text: str
    published_at: date | None


@dataclass
class BasedOn:
    """Source attribution for an extracted fact candidate."""
    type: str  # "record" | "generic_pattern"
    excerpts: list[RecordExcerpt] = field(default_factory=list)


@dataclass
class FactCandidate:
    content: str
    fact_type: str
    based_on: BasedOn


@dataclass
class SufficiencyResult:
    sufficient: bool
    reason: str


@dataclass
class DrilldownDecision:
    """Whether the answer just confirmed is worth an immediate, narrower
    follow-up before continuing — e.g. a base question answered with "기획과
    개발" (planning and development) is a candidate for drilling into one of
    those with a concrete-example question, rather than moving straight to
    the next, unrelated fixed question (2026-09-05 request)."""
    should_ask: bool
    question_text: str | None = None


@dataclass
class SentenceWithEvidence:
    text: str
    fact_indices: list[int]


@dataclass
class ParagraphDraft:
    """A group of sentences about the same specific sub-topic within a
    category (e.g. "무엇을 했다" vs "그 동기/이유"의 별도 문단) — lets the
    exported document read as themed paragraphs instead of one flat list
    of disconnected STAR sentences (2026-09-05 request)."""
    topic: str
    sentences: list[SentenceWithEvidence]


@dataclass
class DraftDocument:
    paragraphs: list[ParagraphDraft]


@dataclass
class CategorySuggestion:
    category_type: str
    custom_label: str


@dataclass
class PeriodSuggestion:
    start_date: date
    end_date: date


@dataclass
class ConfirmedFact:
    id: str
    content: str
    source_type: str  # user_confirmed | user_edited | record_cited
    fact_type: str    # see app.models.confirmed_fact.FACT_TYPES


@dataclass
class InterviewContext:
    session_id: str
    category_label: str
    gap_start: date
    gap_end: date
    confirmed_facts_so_far: list[ConfirmedFact]
    record_excerpts: list[RecordExcerpt] = field(default_factory=list)
    asked_questions: list[str] = field(default_factory=list)


#: 취업 정보 종합 검색이 다루는 6개 카테고리 — 9개 워크넷/고용24 엔드포인트를
#: 사용자 개념 단위로 묶은 것(직업훈련과정 하나가 실제로는 4개 엔드포인트를
#: 가리킴). classify_job_info_query가 이 중에서 고른다.
JOB_INFO_CATEGORIES = (
    "job_fair",
    "public_recruitment",
    "public_recruitment_company",
    "training_course",
    "job_seeker_program",
    "promising_sme",
)


@dataclass
class JobInfoCategoryQuery:
    """classify_job_info_query 한 건 — 사용자의 자유 텍스트 질문이 이 카테고리와
    관련 있다고 LLM이 판단했다는 뜻. keywords는 그 카테고리 안에서 결과를
    좁히는 데 쓸 검색어(서버 API가 자유 키워드 검색을 지원 안 하는 경우가
    많아 응답 텍스트에 대한 부분일치 필터로 쓰인다 — job_info_client 참고).
    한 질문이 여러 카테고리에 동시에 걸릴 수 있으므로 리스트로 여러 개 온다."""
    category: str
    keywords: list[str] = field(default_factory=list)


class ProviderUnavailableError(Exception):
    pass


class AllProvidersFailedError(Exception):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    async def draft_answer(self, context: InterviewContext, question_text: str) -> str: ...
    async def extract_facts(
        self, context: InterviewContext, question_text: str, answer_text: str, fact_type_hint: str
    ) -> list[FactCandidate]: ...
    async def followup_question(self, context: InterviewContext) -> str: ...
    async def extract_activity_items(self, category_label: str, answer_text: str) -> list[str]: ...
    async def judge_sufficiency(self, context: InterviewContext) -> SufficiencyResult: ...
    async def judge_drilldown(self, context: InterviewContext) -> DrilldownDecision: ...
    async def generate_document(self, facts: list[ConfirmedFact], tone: str, category_label: str) -> DraftDocument: ...
    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]: ...
    async def extract_period(self, free_text: str, today: date) -> PeriodSuggestion | None: ...
    async def classify_job_info_query(self, query: str) -> list[JobInfoCategoryQuery]: ...
    async def draft_job_info_query_from_facts(self, confirmed_facts: list[ConfirmedFact]) -> str: ...
    async def health_check(self) -> bool: ...
