from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class GapPeriodSet(BaseModel):
    start_date: date
    end_date: date


class GapPeriodRead(BaseModel):
    start_date: date
    end_date: date

    model_config = {"from_attributes": True}


class PeriodExtractRequest(BaseModel):
    text: str


class PeriodExtractRead(BaseModel):
    """Response of `POST /period/extract`.

    Invariant: either both fields are populated (a confident guess) or both
    are null (the model couldn't confidently determine a range) — never one
    without the other.
    """

    start_date: date | None
    end_date: date | None


class CategoryInput(BaseModel):
    category_type: str
    custom_label: str | None = None


class CategoryTypeUpdate(BaseModel):
    """`PATCH /{session_id}/categories/{category_id}/type` 요청 바디 — 분류가
    잘못돼 엉뚱한 질문 은행이 배정됐을 때(예: 인턴십이 아르바이트로) 사용자가
    직접 바로잡는다."""

    category_type: str


class CategorySelect(BaseModel):
    categories: list[CategoryInput]


class CategoryExtractRequest(BaseModel):
    text: str


class CategorySuggestionRead(BaseModel):
    category_type: str
    custom_label: str


class CategoryExtractRead(BaseModel):
    suggestions: list[CategorySuggestionRead]
    #: suggestions가 비었을 때만 채워진다. "잘 모르겠어" 같은 답에 같은 질문을
    #: 되풀이하는 대신 AI가 구체적인 갈래를 짚어 되묻는 문장이다. LLM을 못 쓰면
    #: None이고, 그때 프론트는 정적 예시 안내로 돌아간다.
    followup_question: str | None = None


class StatusRead(BaseModel):
    status: str


class RecordsSkipRead(BaseModel):
    status: str
    current_category_id: uuid.UUID


class RecordExcerptRead(BaseModel):
    chunk_id: str
    text: str
    published_at: date | None = None


class BasedOnRead(BaseModel):
    type: Literal["record", "generic_pattern"]
    excerpts: list[RecordExcerptRead] = []


class ConfirmedFactRead(BaseModel):
    id: uuid.UUID
    fact_type: str
    content: str
    source_type: str
    source_question_text: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConflictRefRead(BaseModel):
    """FactCandidateRead.conflict_with 항목 하나 — 모순 상대 draft를 turn_id+index로
    가리킨다(같은 카테고리 리뷰 카드 안이라도 다른 턴의 draft를 가리킬 수 있어
    전역 인덱스가 아니라 이 조합이 필요하다)."""

    turn_id: str
    index: int


class FactCandidateRead(BaseModel):
    index: int
    content: str
    fact_type: str
    based_on: BasedOnRead
    #: 같은 카테고리 리뷰 카드 안의 다른 draft와 논리적으로 모순된다고 LLM이
    #: 판단했을 때 그 상대 draft(들)을 가리킨다. 확정을 막지 않는다 — 사용자가
    #: 리뷰에서 직접 확인하라는 경고일 뿐이다(devlog 41, Case D).
    conflict_with: list[ConflictRefRead] = []


class ReviewGroupRead(BaseModel):
    """카테고리 끝 확인 화면의 한 묶음 — 질문 하나와 그 답에서 뽑은 초안 사실들."""

    turn_id: str
    question_text: str
    answer_text: str
    fact_type: str
    #: 비어 있어도 정상이다(답에서 뽑을 사실이 없었음). 사용자는 여기에 직접 추가할 수 있다.
    drafts: list[FactCandidateRead]


class CategoryReviewRead(BaseModel):
    """카테고리 단위 확인(2026-09-11) — 이 카테고리에서 답한 내용을 질문별로 모아
    한 번에 확인받는다. 확인 전에는 confirmed_facts에 아무것도 들어가지 않는다."""

    category_id: uuid.UUID
    category_label: str
    groups: list[ReviewGroupRead]


class InterviewAskRead(BaseModel):
    """`POST /interview/ask` 응답 — 이번 턴에 물어볼 질문, 또는 카테고리 끝 확인.

    `mode="question"`: question_source가 "base"면 interview_question_bank.py의 고정
    질문, "followup"이면 AI가 즉흥적으로 만든 후속 질문이다. 이미 답변을 기다리는 중인
    pending_turn이 있으면 LLM을 다시 부르지 않고 같은 질문을 그대로 반환한다(서버 사이드
    idempotent).

    `mode="review"`: 카테고리 질문이 끝나 확인을 기다리는 중이다(새로고침 복원 경로).
    `review`에 확인할 내용이 실린다.

    `mode="candidates"`: "여러 활동 있나요?" 답변에서 후보가 이미 뽑혔지만 아직
    `/interview/confirm`으로 확정되지 않은 중이다(새로고침 복원 경로). `candidates`에
    복원할 후보가 실린다 — 이 상태를 처리 안 하면 같은 분리질문이 새로고침마다
    반복되고 후보가 버려지는 버그가 된다(2026-09-12 확인).

    2026-09-12까지는 `draft_answer`(AI가 미리 써둔 답변으로 입력창을 채우는 값)가
    함께 왔다. 사용자 요청으로 기능을 제거했고, 덕분에 질문마다 돌던 LLM 호출도 하나
    줄었다 — 입력창은 항상 빈 칸으로 시작한다.
    """

    category_id: uuid.UUID
    mode: Literal["question", "review", "candidates"] = "question"
    question_text: str | None = None
    question_source: Literal["base", "followup", "split_check"] | None = None
    review: CategoryReviewRead | None = None
    candidates: list[FactCandidateRead] = []


class InterviewAnswerRequest(BaseModel):
    text: str


class InterviewAnswerRead(BaseModel):
    """`POST /interview/answer` 응답.

    - `mode="candidates"`: "여러 활동 있나요?"(소분류) 질문 전용 — 지금처럼 바로
      확인받는다(/interview/confirm). candidates가 빈 배열이어도 정상이다.
    - `mode="question"`: 답은 초안으로 쌓였고 다음 질문이 `question`에 있다.
    - `mode="review"`: 이 카테고리 질문이 끝났다 — `review`를 확인받는다.
    """

    mode: Literal["candidates", "question", "review"] = "candidates"
    candidates: list[FactCandidateRead] = []
    question: InterviewAskRead | None = None
    review: CategoryReviewRead | None = None


class InterviewSkipRead(BaseModel):
    """`POST /interview/skip` 응답 — records/skip과 달리 다음 질문/리뷰까지
    바로 실어 보낸다(추가 /ask 호출 없이). `mode="question"`이면 `question`에,
    `mode="review"`면 `review`에 내용이 있다. 건너뛰기는
    `question_source == "followup"`일 때만 가능하다(devlog 54) — 고정 질문·
    소분류 확인 질문은 건너뛸 수 없다."""

    mode: Literal["question", "review"]
    question: InterviewAskRead | None = None
    review: CategoryReviewRead | None = None


class FactConfirmation(BaseModel):
    index: int
    final_text: str
    was_edited: bool
    include: bool = True


class InterviewConfirmRequest(BaseModel):
    """`POST /interview/confirm` 요청 바디.

    의도적으로 `source_type`/`fact_type`을 클라이언트가 지정하지 못하게 한다 — 그걸
    허용하면 클라이언트가 아무 텍스트나 `record_cited`라고 주장할 수 있어 정직성
    가드레일이 뚫린다. 둘 다 서버가 interview/answer에서 캐시해둔 pending_turn의
    candidate_facts/based_on/was_edited로부터만 도출한다.
    """

    confirmations: list[FactConfirmation]


class ReviewConfirmation(BaseModel):
    """카테고리 끝 확인의 한 항목. `index`가 그 턴의 초안 수를 넘으면 사용자가 직접
    추가한 항목이다. source_type/fact_type은 여기서 받지 않는다(InterviewConfirmRequest와
    같은 이유 — 서버가 저장해 둔 턴에서만 도출한다)."""

    turn_id: str
    index: int
    final_text: str
    was_edited: bool
    include: bool = True


class InterviewReviewRequest(BaseModel):
    confirmations: list[ReviewConfirmation]


class InterviewConfirmRead(BaseModel):
    status: str
    current_category_id: uuid.UUID | None = None
    category_done: bool
    confirmed_facts: list[ConfirmedFactRead] = []
