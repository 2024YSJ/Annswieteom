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


class CategorySelect(BaseModel):
    categories: list[CategoryInput]


class CategoryExtractRequest(BaseModel):
    text: str


class CategorySuggestionRead(BaseModel):
    category_type: str
    custom_label: str


class CategoryExtractRead(BaseModel):
    suggestions: list[CategorySuggestionRead]


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


class InterviewAskRead(BaseModel):
    """`POST /interview/ask` 응답 — 이번 턴에 물어볼 질문.

    question_source가 "base"면 interview_question_bank.py의 고정 질문, "followup"이면
    AI가 즉흥적으로 만든 후속 질문이다. 이미 답변을 기다리는 중인 pending_turn이 있으면
    LLM을 다시 부르지 않고 같은 질문을 그대로 반환한다(서버 사이드 idempotent).

    draft_answer는 사용자가 입력창에 타이핑을 시작하기 전에 미리 채워볼 수 있는 답변
    초안이다 — 이걸 그대로 보내든, 고쳐서 보내든, 지우고 새로 쓰든 최종 판단은 여전히
    사용자 몫이고, interview/answer -> interview/confirm의 확인 절차는 그대로 거친다
    (정직성 가드레일은 "무엇을 답했는지"가 아니라 "그 답에서 뽑은 사실을 확인했는지"에서
    지켜지므로 이 필드는 그 절차를 건너뛰지 않는다).
    """

    category_id: uuid.UUID
    question_text: str
    question_source: Literal["base", "followup"]
    draft_answer: str


class InterviewAnswerRequest(BaseModel):
    text: str


class FactCandidateRead(BaseModel):
    index: int
    content: str
    fact_type: str
    based_on: BasedOnRead


class InterviewAnswerRead(BaseModel):
    """`POST /interview/answer` 응답. candidates가 빈 배열이어도 정상이다 —
    사용자가 무의미한 답을 했을 때 사실을 지어내지 않기 위해서다.
    """

    candidates: list[FactCandidateRead]


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


class InterviewConfirmRead(BaseModel):
    status: str
    current_category_id: uuid.UUID | None = None
    category_done: bool
    confirmed_facts: list[ConfirmedFactRead] = []
