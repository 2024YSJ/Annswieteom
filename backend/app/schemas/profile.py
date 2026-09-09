from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ArchivedFactRead(BaseModel):
    content: str
    fact_type: str
    source_type: str


class ArchivedAnswerRead(BaseModel):
    """계정에 쌓인 문답 한 건 — 질문, 사용자가 실제로 쓴 답변 원문, 그 답변에서
    확정된 사실들의 스냅샷.

    `session_id`가 None이면 원래 세션이 삭제된 뒤에도 남은 기록이다.
    """

    id: uuid.UUID
    session_id: uuid.UUID | None
    category_label: str
    category_type: str
    question_text: str
    question_source: str
    answer_text: str
    confirmed_facts: list[ArchivedFactRead]
    created_at: datetime

    model_config = {"from_attributes": True}


class ArchiveSummaryRead(BaseModel):
    total_answers: int
    total_confirmed_facts: int
    category_types: list[str]
