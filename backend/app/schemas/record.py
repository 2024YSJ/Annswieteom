from __future__ import annotations

import uuid
from datetime import date, datetime
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


class UncitedChunkRead(BaseModel):
    """`GET /sessions/{id}/records/uncited` — 아직 어떤 확정 사실도 인용하지 않은
    기록물 조각. 사용자에게 "이건 안 쓰셨는데 넣을까요?"를 되물을 근거가 된다."""

    chunk_id: uuid.UUID
    text: str
    published_at: date | None
