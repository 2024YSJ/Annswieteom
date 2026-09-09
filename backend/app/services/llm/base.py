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


def clamp_activity_period(
    start: date, end: date, gap_start: date, gap_end: date
) -> PeriodSuggestion | None:
    """활동 기간 추정치를 공백 기간 안으로 자른다.

    커버리지 계산(app/services/coverage.py)은 활동 기간이 공백 기간 안에 있다고
    가정한다 — 모델이 공백기 밖으로 삐져나간 날짜를 뱉으면 "채워진 개월 수"가
    전체 개월 수를 넘어가는 이상한 값이 나온다. 겹치는 구간이 아예 없으면
    (환각으로 엉뚱한 연도를 준 경우) 추정 자체를 버리고 None을 돌려준다 —
    잘못된 기간을 넣는 것보다 "모름"으로 두는 편이 정직하다.

    공백 기간과 **정확히 같은** 구간도 버린다. 실 로컬 모델 검증(2026-09-09)에서
    qwen2.5:3b는 단서가 없는 사실을 받으면 공백 기간 전체를 그대로 베껴 돌려줬다 —
    프롬프트로 막아지지 않았다. 이건 "이 활동이 공백기 내내 이어졌다"는 관찰이
    아니라 모델이 입력을 되뱉은 것이고, 그대로 저장하면 커버리지가 100%가 되어
    빈 구간이 하나도 안 남는다.

    실제로 공백기 전체를 채운 활동은 이 규칙에 억울하게 걸린다. 그쪽을 택한
    이유는 두 오류의 대가가 다르기 때문이다 — 과소 보고는 이미 설명한 구간에
    대해 질문을 한 번 더 받는 것으로 끝나지만, 과대 보고는 빈 구간을 통째로
    숨겨 기능을 무의미하게 만든다. 사용자는 기간을 직접 지정해 정정할 수 있다
    (PATCH /sessions/{id}/categories/{id}/period).
    """
    if start > end:
        return None
    clamped_start = max(start, gap_start)
    clamped_end = min(end, gap_end)
    if clamped_start > clamped_end:
        return None
    if clamped_start == gap_start and clamped_end == gap_end:
        return None
    return PeriodSuggestion(start_date=clamped_start, end_date=clamped_end)


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
    관련 있다고 LLM이 판단했다는 뜻. 한 질문이 여러 카테고리에 동시에 걸릴 수
    있으므로 리스트로 여러 개 온다. 이 카테고리 안에서 실제로 어떤 항목이
    관련 있는지는 select_relevant_job_info_results가 따로 판단한다(문자열
    부분일치 대신 — 예: "경기 북부"라고 물었을 때 실제 데이터엔 "의정부"/
    "파주"처럼 구체적인 지명만 있는 경우를 문자열 매칭으로는 못 잡는다,
    devlog 18)."""
    category: str


@dataclass
class JobInfoCandidate:
    """select_relevant_job_info_results에 넘기는 조회된 항목 하나 — 실제
    JobInfoResult 필드 중 LLM이 관련성을 판단하는 데 필요한 것만."""
    index: int
    title: str
    subtitle: str
    meta_lines: list[str] = field(default_factory=list)


class LLMUnavailableError(Exception):
    """로컬 Ollama에 요청을 보낼 수 없거나, 보냈는데 쓸 수 없는 응답이 온 경우.

    2026-09-09까지는 프로바이더가 던지는 ProviderUnavailableError를 폴백 계층이
    모아 AllProvidersFailedError로 바꿔 라우터에 넘겼다. Gemini를 제거하면서
    프로바이더가 하나뿐이 됐으므로 "전부 실패했다"는 이름이 거짓이 됐고, 두 예외를
    이 하나로 합쳤다. 타임아웃도 여기 포함된다 — 호출부 입장에서 "AI를 못 썼다"는
    결과는 같고, 잡아야 할 예외가 둘이면 한 곳에서 빠뜨리기 때문이다.

    라우터는 이걸 잡아 503 + detail="llm_unavailable"로 바꾼다(프론트가
    "AI 서버가 수리 중이예요."로 표시).
    """


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
    async def extract_activity_period(
        self, category_label: str, facts: list[ConfirmedFact], gap_start: date, gap_end: date
    ) -> PeriodSuggestion | None: ...
    async def classify_job_info_query(self, query: str) -> list[JobInfoCategoryQuery]: ...
    async def select_relevant_job_info_results(
        self, query: str, category_label: str, candidates: list[JobInfoCandidate]
    ) -> list[int]: ...
    async def draft_job_info_query_from_facts(self, confirmed_facts: list[ConfirmedFact]) -> str: ...
    async def health_check(self) -> bool: ...
