from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BlogRecordCreate(BaseModel):
    record_type: Literal["blog_url"]
    source_url: str = Field(min_length=1)


class TextRecordCreate(BaseModel):
    text: str = Field(min_length=1)


class RecordRead(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    record_type: str
    source_url: str | None
    original_filename: str | None
    platform: str
    parse_status: str
    parse_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
