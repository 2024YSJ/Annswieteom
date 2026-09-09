from __future__ import annotations

import uuid
from datetime import datetime
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
    # 판정에 쓰인 실제 코사인 유사도. 근거가 없어 검사를 못 했거나, 이 컬럼이
    # 생기기 전(2026-09-09) 문장이면 None.
    consistency_score: float | None = None
    # 사용자가 직접 고쳐 쓴 문장인지. consistency_check_passed=True를 "임베딩
    # 검증 통과"로 읽으면 안 되는 경우가 바로 이 플래그가 켜진 문장이다.
    edited_by_user: bool = False
    #: record_backed | self_reported | unsupported — app/services/evidence.py
    evidence_grade: str = "unsupported"


class SentenceUpdate(BaseModel):
    text: str


class UnverifiedSentenceRead(BaseModel):
    """확정(finalize)을 막아선 문장 하나 — 어떤 문장을 손봐야 하는지 바로
    가리킬 수 있도록 409 응답 본문에 담긴다."""

    id: uuid.UUID
    order_index: int
    text: str
    consistency_score: float | None


class FinalizeRequest(BaseModel):
    # 정합성 검사에 걸린 문장이 남아 있어도 그대로 확정하겠다는 명시적 동의.
    # 기본값이 False라 "모르고 지나치는" 경로가 없다.
    acknowledge_unverified: bool = False


class DocumentVersionRead(BaseModel):
    id: uuid.UUID
    version: int
    tone: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


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
