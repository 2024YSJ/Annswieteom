from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    tone: Literal["plain", "neutral", "assertive"] = "neutral"


class SentenceRead(BaseModel):
    id: uuid.UUID
    order_index: int
    text: str
    evidence_fact_ids: list[uuid.UUID]
    consistency_check_passed: bool

    model_config = {"from_attributes": True}


class SentenceUpdate(BaseModel):
    text: str


class DocumentRead(BaseModel):
    id: uuid.UUID
    tone: str
    version: int
    status: str
    sentences: list[SentenceRead]

    model_config = {"from_attributes": True}
