from __future__ import annotations

import uuid
from datetime import date
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
