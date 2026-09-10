from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.user_preference import WISH_TEXT_MAX_CHARS


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


class PreferenceRead(BaseModel):
    """사용자가 직접 쓴 "맞춤 정보"(희망사항).

    맞춤 공고 정렬은 인터뷰 답변에서만 만들어졌기 때문에, 공백기 정리를 아직
    안 한 사용자에게는 정렬을 조종할 수단이 전혀 없었다. 이 필드가 그 조종간이다.
    """

    wish_text: str
    updated_at: datetime | None


class PreferenceUpdate(BaseModel):
    #: 비우면(빈 문자열) 희망사항을 지운 것으로 처리한다 — 별도 삭제 API를 두지
    #: 않는 이유는 "지우기"가 곧 "빈 값으로 저장"이기 때문이다.
    wish_text: str = Field(default="", max_length=WISH_TEXT_MAX_CHARS)
