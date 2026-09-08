from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class JobPreferencesExtractRequest(BaseModel):
    text: str


class JobPreferencesSuggestionRead(BaseModel):
    """`POST /job-search/preferences/extract` 응답 — suggestion만, 미저장.

    카테고리/기간 추출과 동일한 원칙: 사용자가 이 값을 확인/수정한 뒤 직접
    `POST /job-search/preferences`를 호출해야 실제로 저장된다.
    """

    desired_keyword: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    location: str | None = None
    education_level: str | None = None
    career_years: int | None = None
    work_style_tags: list[str] = []


class JobPreferencesConfirmRequest(BaseModel):
    """확인 단계에서 사용자가 자유롭게 고친 최종 값 — 스칼라 필드는 폼
    수정으로, work_style_tags는 태그 추가/삭제/수정으로 반영된 뒤 이 값 그대로
    저장된다(카테고리 확정 후보와 동일하게, 서버는 사용자가 최종 제출한 값만
    받는다)."""

    desired_keyword: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    location: str | None = None
    education_level: str | None = None
    career_years: int | None = None
    work_style_tags: list[str] = Field(default_factory=list)


class JobPreferencesRead(BaseModel):
    desired_keyword: str | None
    salary_min: int | None
    salary_max: int | None
    location: str | None
    education_level: str | None
    career_years: int | None
    work_style_tags: list[str]

    model_config = {"from_attributes": True}


class JobPreferencesConfirmRead(BaseModel):
    status: str
    preferences: JobPreferencesRead


class JobPostingRead(BaseModel):
    source: str
    external_id: str
    title: str
    company: str
    salary_text: str
    location: str
    education_requirement: str
    career_requirement: str
    work_type: str
    url: str
    fit: bool
    reason: str


class JobSearchStateRead(BaseModel):
    """`GET /job-search`와 `POST /job-search/search` 공용 응답 — 새로고침 시
    외부 API/LLM을 다시 부르지 않고 캐시된 `last_results`를 그대로 보여줄 수
    있도록, 검색을 실제로 실행하는 엔드포인트와 조회만 하는 엔드포인트가 같은
    모양을 반환한다."""

    status: str
    linked_gap_session_id: str | None
    preferences: JobPreferencesRead | None
    # 최초 1회차 대화형 질문 중 이미 답한 필드 id 목록 — 프론트가 이걸로
    # "아직 첫 입력을 안 끝냈다"(JobSearchInterviewSection) vs "이미 한 번
    # 확정했다"(JobSearchPreferencesSection) 화면을 가른다.
    completed_fields: list[str]
    last_searched_at: datetime | None
    results: list[JobPostingRead]


class JobSearchQuestionRead(BaseModel):
    """`POST /job-search/preferences/ask`와 `.../turn-confirm` 공용 응답 —
    다음 질문이 있으면 그 질문을, 6개를 다 답했으면 done=true(이 시점에
    session.status는 이미 JOB_SEARCHING으로 전이돼 있다)."""

    done: bool
    status: str
    field: str | None = None
    question_text: str | None = None
    draft_answer: str = ""


class JobSearchTurnConfirmRequest(BaseModel):
    """진행 중인 턴(현재 질문)에 해당하는 값만 채워 보낸다 — 서버는
    `pending_turn`에 캐싱해둔 field로 어느 값을 실제로 반영할지 스스로
    판단하고 나머지는 무시한다(클라이언트가 엉뚱한 필드를 우길 수 없게)."""

    desired_keyword: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    location: str | None = None
    education_level: str | None = None
    career_years: int | None = None
    work_style_tags: list[str] | None = None


class JobSearchSeedRead(BaseModel):
    """`POST /job-search/seed-from-gap` 응답 — suggestion만, 미저장. 연동
    출처인 gap 세션의 confirmed_facts에서 추론한 힌트일 뿐, 급여/근무지는
    STAR 사실만으로는 알 수 없으므로 항상 비어 있다."""

    work_style_tags: list[str]
    keyword_hints: list[str]
    notes: str
