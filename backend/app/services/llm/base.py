from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

# 프로바이더 메서드는 호출 시점에 두 샘플링 모드 중 하나를 반드시 명시한다 —
# 기본값을 두지 않는 게 핵심이고, 새 메서드를 추가할 때 "이건 판단인가 생성인가"를
# 한 번 결정하게 만든다. 분류/추출/판단은 같은 입력에 같은 답이 나와야 하는데,
# 지정하지 않으면 모델 기본값(~0.7)이 걸려 회차마다 답이 달라진다(devlog 19).
TEMPERATURE_DETERMINISTIC = 0.0
# 초안/문서 생성처럼 표현의 다양성이 바람직한 호출. 대부분 모델의 기본값과
# 맞춰 둬서, 온도를 명시하는 이 변경이 생성 계열의 동작을 바꾸지 않게 했다.
TEMPERATURE_CREATIVE = 0.7


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
    #: 이 사용자에 대해 이미 아는 속성(비민감만) — "거주: 경기 수원" 같은 줄.
    #: followup_question / judge_drilldown 프롬프트에만 넣는다. draft_answer에
    #: 넣으면 추정 속성이 AI 초안에 섞이고, 사용자가 무심코 확인하는 순간
    #: confirmed_fact로 세탁된다(정직성 가드레일).
    profile_summary: list[str] = field(default_factory=list)


@dataclass
class AttributeCandidate:
    """사용자 발화에서 뽑은 속성 후보 하나.

    `value_label`은 프롬프트가 보여준 어휘 안의 라벨이다 — 코드는 서버가 붙인다
    (regions.py와 같은 원칙: LLM에게 코드를 외우게 하지 않는다). `evidence`는
    사용자가 실제로 한 말 그대로여야 하고, 원문에 없으면 서버가 버린다.
    """

    key: str
    value_label: str
    evidence: str


#: 취업 정보 종합 검색이 다루는 6개 카테고리 — 9개 고용24 엔드포인트를
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


@dataclass
class JobInfoQueryParams:
    """사용자 질문에서 뽑아낸 조회 조건 — 고용24 호출에 그대로 실린다.

    예전에는 이런 게 아예 없어서, 카테고리(=엔드포인트)만 고르고 조회는
    전국 첫 20건을 무조건 받아왔다. "경기 북부 백엔드"라고 물어도 후보에
    강원/경남 과정이 들어오니 관련성 판단이 아무리 정확해도 건질 게 없었다
    (devlog 20).

    같은 차원에 값이 여러 개 올 수 있어("서울이나 경기") 전부 리스트다 —
    API는 파라미터 하나에 값 하나만 받으므로(콤마는 0건, 반복 파라미터는 첫
    값만 적용) 값마다 호출을 쪼개는 건 조회 계층이 담당한다.
    """
    regions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


#: 활동을 못 떠올리는 사용자에게 짚어줄 갈래. 어느 것을 물을지는 서버가 고른다 —
#: 모델에게 "다양하게 물어라"라고 시켰더니 프롬프트를 고칠 때마다 쏠리는 갈래만
#: 바뀌었다(아르바이트 -> 운동/건강, 14b 실측 2026-09-09). 선택을 코드로 가져오면
#: 다양성이 보장되고, LLM은 잘하는 일(자연스러운 문장 만들기)만 하면 된다.
#: 같은 사용자가 계속 "모르겠다"고 해도 매번 다른 각도로 물어보게 된다.
PROBE_FOCUSES = (
    "아르바이트나 단기 근로",
    "공부, 자격증 준비, 인터넷 강의",
    "운동이나 건강 관리",
    "취미나 관심사",
    "가족 돌봄이나 집안일",
    "구직 활동(지원서 쓰기, 면접 등)",
    "특별한 일 없이 보낸 시간",
)


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
    #: 카테고리 추출이 빈 결과였을 때만 부른다 — "잘 모르겠어" 같은 답에
    #: 같은 질문을 되풀이하는 대신 구체적인 갈래를 콕 집어 되묻기 위한 것.
    #: 어느 갈래를 물을지(`focus`)는 서버가 고르고 LLM은 문장만 만든다 —
    #: 모델에게 맡겼더니 매번 한 갈래로 쏠렸다(14b 실측, PROBE_FOCUSES 참고).
    async def probe_activity_question(
        self, free_text: str, gap_start: date, gap_end: date, focus: str
    ) -> str: ...
    async def extract_activity_period(
        self, category_label: str, facts: list[ConfirmedFact], gap_start: date, gap_end: date
    ) -> PeriodSuggestion | None: ...
    async def classify_job_info_query(self, query: str) -> list[JobInfoCategoryQuery]: ...
    async def extract_job_info_query_params(self, query: str, known_regions: list[str]) -> JobInfoQueryParams: ...
    async def select_relevant_job_info_results(
        self, query: str, category_label: str, candidates: list[JobInfoCandidate]
    ) -> list[int]: ...
    async def draft_job_info_query_from_facts(self, confirmed_facts: list[ConfirmedFact]) -> str: ...
    #: 사람 단위 속성 추출(나이·거주지·학력·희망직무 …). 백그라운드에서만 부른다 —
    #: 요청 경로의 LLM 호출 수를 늘리지 않는다. 프롬프트는 `allow_sensitive`와
    #: 무관하게 민감 키도 보여준다 — 동의 없는 사용자가 스스로 말한 경우를 알아야
    #: "저장하려면 동의가 필요해요"를 띄울 수 있기 때문이다. 값을 버리는 최종
    #: 차단은 서버(services/profile/attributes.validate_candidates)가 한다.
    async def extract_profile_attributes(
        self, text: str, known: list[str], allow_sensitive: bool
    ) -> list[AttributeCandidate]: ...
    async def health_check(self) -> bool: ...
