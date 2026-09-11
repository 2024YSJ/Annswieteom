from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.interview import ConfirmedFactRead, GapPeriodRead
from app.schemas.record import RecordRead


class SessionCreate(BaseModel):
    kind: str = "gap_fill"
    # kind="job_search"이고 이 값이 있으면, 새 세션이 해당 공백기 채우기
    # 세션의 확정 사실에서 선호도를 연동(seed)받을 수 있다 — 실제 연동은
    # POST /sessions/{id}/job-search/seed-from-gap가 수행한다.
    linked_gap_session_id: uuid.UUID | None = None


class SessionRead(BaseModel):
    id: uuid.UUID
    title: str | None
    kind: str
    linked_gap_session_id: uuid.UUID | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionRename(BaseModel):
    title: str = Field(max_length=200)


class DraftTurnRead(BaseModel):
    """아직 확인 전인 답변 한 턴 — 대화 화면이 새로고침 뒤에도 "질문·내 답" 말풍선을
    다시 그릴 수 있게 질문과 답 원문만 내려준다(초안 사실은 확인 화면에서만)."""

    turn_id: str
    question_text: str
    answer_text: str = ""


class ActivityCategoryRead(BaseModel):
    id: uuid.UUID
    category_type: str
    custom_label: str | None
    order_index: int
    status: str
    parent_category_id: uuid.UUID | None = None
    confirmed_facts: list[ConfirmedFactRead] = []
    draft_turns: list[DraftTurnRead] = []
    records: list[RecordRead] = []

    model_config = {"from_attributes": True}

    @field_validator("draft_turns", mode="before")
    @classmethod
    def _none_to_empty(cls, value):
        # 확인이 끝났거나 아직 답이 없으면 컬럼이 NULL이다.
        return value or []


class RecordChunkExcerptRead(BaseModel):
    chunk_id: uuid.UUID
    text: str
    published_at: date | None


class SessionContextRead(BaseModel):
    """`GET /sessions/{id}` 응답 — 8-1절 InterviewContext.

    LLM 프롬프트 조립에 쓰이는 `app.services.llm.base.InterviewContext`(dataclass)와는
    이름만 같고 용도가 다르다: 이쪽은 프론트에 그대로 내려주는 API 응답 스키마다.
    """

    session_id: uuid.UUID
    status: str
    gap_period: GapPeriodRead | None
    categories: list[ActivityCategoryRead]
    current_category: ActivityCategoryRead | None
    confirmed_facts: list[ConfirmedFactRead]
    available_record_chunks: list[RecordChunkExcerptRead]
