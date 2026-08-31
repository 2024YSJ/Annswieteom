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


class CategorySelect(BaseModel):
    category_types: list[str]


class InterviewConfirm(BaseModel):
    fact_type: Literal["frequency", "task", "achievement"]
    content: str
    source_type: Literal["user_confirmed", "user_edited", "record_cited"]
    ai_draft_text: str | None = None
    source_record_chunk_id: uuid.UUID | None = None
