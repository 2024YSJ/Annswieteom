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


class AnswersResetRead(BaseModel):
    """`POST /me/answers/reset` 응답 — 지운 개수를 돌려줘 "N개를
    초기화했어요" 같은 확인 문구를 보여줄 수 있게 한다."""

    reset_count: int


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


class AttributeRead(BaseModel):
    """대화로 알게 됐거나 직접 입력한 속성 한 값.

    `status`: inferred(대화에서 추정, 아직 확인 안 함) / confirmed(사용자가 맞다고
    함) / user_edited(사용자가 고치거나 직접 입력). `evidence_text`는 추정 근거가
    된 사용자 본인의 말 — 화면에서 "이 말씀에서 알게 됐어요"로 보여준다.
    """

    id: uuid.UUID
    key: str
    key_label: str
    label: str
    status: str
    sensitive: bool
    source_kind: str
    evidence_text: str | None
    created_at: datetime | None


class AttributeKeyRead(BaseModel):
    key: str
    label: str
    sensitive: bool
    multi_valued: bool
    #: 비어 있으면 자유 텍스트 입력.
    choices: list[str]


class ConsentRead(BaseModel):
    granted: bool
    granted_at: datetime | None
    #: 동의 없이 민감정보를 말한 적이 있다 — 값은 저장하지 않았고, 화면이
    #: "저장하려면 동의가 필요해요"를 띄우는 신호다.
    sensitive_mentioned: bool


class AttributesRead(BaseModel):
    attributes: list[AttributeRead]
    keys: list[AttributeKeyRead]
    consent: ConsentRead


class AttributeCreate(BaseModel):
    key: str
    value: str = Field(min_length=1, max_length=60)


class AttributeUpdate(BaseModel):
    value: str = Field(min_length=1, max_length=60)


class ConsentUpdate(BaseModel):
    granted: bool


class AttributesResetRead(BaseModel):
    """`POST /me/attributes/reset` 응답 — 지운 개수를 돌려줘 "12개를
    초기화했어요" 같은 확인 문구를 보여줄 수 있게 한다."""

    reset_count: int
