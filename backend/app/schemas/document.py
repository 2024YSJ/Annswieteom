from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    tone: Literal["plain", "neutral", "assertive"] = "neutral"


class CitationRead(BaseModel):
    source_url: str | None
    published_at: str | None


class EvidenceRead(BaseModel):
    fact_id: uuid.UUID
    content: str
    source_type: str
    citation: CitationRead | None


class SentenceRead(BaseModel):
    """GET /document 응답의 문장 하나 — 28절: evidence_fact_ids를 그대로 내려주면
    프론트가 EvidenceTag를 그릴 수 없어서, 각 근거를 content/citation까지
    확장한 `evidence` 배열로 채운다. ORM에서 직접 매핑되지 않고(citation 조회가
    끼어들어야 함) API 레이어가 수동으로 조립한다.
    """

    id: uuid.UUID
    order_index: int
    text: str
    evidence: list[EvidenceRead]
    consistency_check_passed: bool


class SentenceUpdate(BaseModel):
    text: str


class MoveSentenceRequest(BaseModel):
    direction: Literal["prev", "next"]


class ParagraphUpdate(BaseModel):
    topic: str | None = None
    user_confirmed: bool | None = None


class ParagraphRead(BaseModel):
    """유사 주제로 묶인 문장 그룹 — 28절 요청(2026-09-05): 평평한 문장 목록 대신
    문단 단위로 보여주고, 사용자가 그 그룹핑을 확인/조정할 수 있게 한다.
    """

    id: uuid.UUID
    order_index: int
    topic: str
    user_confirmed: bool
    sentences: list[SentenceRead]


class DocumentRead(BaseModel):
    id: uuid.UUID
    tone: str
    version: int
    status: str
    paragraphs: list[ParagraphRead]
