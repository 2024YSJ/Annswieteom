from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class SessionCreate(BaseModel):
    pass


class SessionRead(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GapPeriodSet(BaseModel):
    start_date: date
    end_date: date


class GapPeriodRead(BaseModel):
    start_date: date
    end_date: date

    model_config = {"from_attributes": True}


class CategoryInput(BaseModel):
    category_type: str


class CategorySelect(BaseModel):
    categories: list[CategoryInput]


class ConfirmedFactRead(BaseModel):
    id: uuid.UUID
    fact_type: str
    content: str
    source_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityCategoryRead(BaseModel):
    id: uuid.UUID
    category_type: str
    custom_label: str | None
    order_index: int
    status: str
    confirmed_facts: list[ConfirmedFactRead] = []

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


class InterviewNextRead(BaseModel):
    step: str
    category_id: uuid.UUID
    ai_draft: str
    based_on: BasedOnRead


class InterviewConfirm(BaseModel):
    """9-3절 `POST /interview/confirm` 요청 바디.

    의도적으로 `source_type`을 클라이언트가 지정하지 못하게 한다 — 그걸 허용하면
    클라이언트가 아무 텍스트나 `record_cited`라고 주장할 수 있어 정직성 가드레일이
    뚫린다. source_type은 서버가 interview/next에서 캐시해둔 `pending_draft`의
    based_on/was_edited로부터만 도출한다 (02_interview_state_machine_api.md 4절).
    """

    step: Literal["FREQ_CONFIRM", "TASK_CONFIRM", "ACHIEVEMENT_CONFIRM"]
    final_text: str
    was_edited: bool


class InterviewConfirmRead(BaseModel):
    status: str
    current_category_id: uuid.UUID | None = None
