from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.interview import ConfirmedFactRead, GapPeriodRead
from app.schemas.record import RecordRead


class SessionCreate(BaseModel):
    pass


class SessionRead(BaseModel):
    id: uuid.UUID
    title: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionRename(BaseModel):
    title: str = Field(max_length=200)


class ActivityCategoryRead(BaseModel):
    id: uuid.UUID
    category_type: str
    custom_label: str | None
    order_index: int
    status: str
    parent_category_id: uuid.UUID | None = None
    confirmed_facts: list[ConfirmedFactRead] = []
    records: list[RecordRead] = []

    model_config = {"from_attributes": True}


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
