from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, JSON, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

#: 대화에서 뽑아 저장하는 사람 단위 속성. 온통청년 통합검색의 조건 필드(지역·연령·
#: 학력·전공·취업상태·특화분야·혼인·소득)가 곧 매칭 축이라 그걸 뼈대로 하고,
#: 취업 쪽 검색에 쓰는 희망직무·지역·고용형태·보유기술을 더했다.
NON_SENSITIVE_KEYS = (
    "birth_year",
    "residence_region",
    "desired_region",
    "education_level",
    "major_field",
    "employment_status",
    "desired_job",
    "desired_employment_type",
    "skills",
    "certificates",
    "interests",
)

#: 소득·특화분야(장애·수급·한부모 등)·혼인은 **동의 없이는 저장하지 않는다.**
#: 장애는 개인정보보호법상 민감정보(건강)이고, 나머지도 같은 무게로 다룬다.
SENSITIVE_KEYS = ("annual_income", "special_groups", "marital_status")

ATTRIBUTE_KEYS = NON_SENSITIVE_KEYS + SENSITIVE_KEYS

#: 값이 여러 개 공존할 수 있는 키. 나머지는 활성 값이 하나뿐이고 새 값이
#: 옛 추정을 대체한다(services/profile/attributes.py reconcile).
MULTI_VALUED_KEYS = frozenset(
    {"desired_region", "desired_job", "skills", "certificates", "interests", "special_groups"}
)

#: inferred    — 대화에서 자동 추출, 사용자가 아직 안 봤다
#: confirmed   — 사용자가 "맞아요"를 눌렀다
#: user_edited — 사용자가 직접 고치거나 입력했다
#: rejected    — 사용자가 지웠다. 행을 남겨 두는 이유는 같은 값이 다음 대화에서
#:               다시 추출돼도 **되살리지 않기 위해서다.**
ATTRIBUTE_STATUSES = ("inferred", "confirmed", "user_edited", "rejected")

ATTRIBUTE_SOURCE_KINDS = ("interview_answer", "job_search", "wish_text", "profile_form")


class UserAttribute(Base):
    """사용자에 대해 알게 된 속성 하나(나이·거주지·학력·희망직무 …).

    **정직성 가드레일과의 관계:** 이 테이블은 추천(어떤 공개 공고를 위로 올릴지)과
    대화(무엇을 다시 묻지 않을지)에만 쓴다. 생성 문서(STAR)는 여전히
    confirmed_facts만 인용한다 — 여기 값은 document_generator로 절대 흐르지 않는다.
    추정 값이 AI 초안에 섞여 사용자가 무심코 확인하면 confirmed_fact로 세탁되므로
    draft_answer 프롬프트에도 넣지 않는다.

    값은 행 단위 이력으로 남는다. 추정 값이 바뀌면 옛 행에 `invalidated_at`을
    찍고 새 행을 넣는다(Mem0가 그래프판에서 삭제 대신 무효화를 쓰는 것과 같은
    이유 — 언제 무엇이 바뀌었는지가 남는다). 활성 = invalidated_at IS NULL.
    """

    __tablename__ = "user_attributes"
    __table_args__ = (
        CheckConstraint(f"key IN {ATTRIBUTE_KEYS}", name="ck_user_attributes_key"),
        CheckConstraint(f"status IN {ATTRIBUTE_STATUSES}", name="ck_user_attributes_status"),
        CheckConstraint(f"source_kind IN {ATTRIBUTE_SOURCE_KINDS}", name="ck_user_attributes_source_kind"),
        Index("ix_user_attributes_user_key", "user_id", "key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    # {"label": "경기 수원", "code": "41110"} 처럼 표시용 라벨 + (있으면) 매칭용 코드.
    # 제네릭 JSON인 이유는 feed_items.meta_lines와 같다(SQLite 테스트).
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    # 같은 값인지 비교하는 정규화 문자열(코드가 있으면 코드, 없으면 라벨 소문자·공백 제거).
    value_norm: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="inferred")
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_answer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_answers.id", ondelete="SET NULL"), nullable=True
    )
    # 사용자가 실제로 한 말 그대로(추출 근거). 원문 복제이므로 원 답변을 지우면
    # 같이 지운다(api/profile.py delete_archived_answer).
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
