from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

# frequency/task/achievement는 예전 고정 3턴 인터뷰의 유물 — 기존 행과의 하위호환을 위해
# 남겨뒀다. 카테고리별 고정 질문 세트는 이보다 구체적인 타입을 쓰고
# (interview_question_bank.py), AI가 즉흥적으로 던지는 후속 질문에서 나온 사실은 전부
# "followup"로 통일한다 (질문 문구가 매번 달라 안정적인 fact_type을 줄 수 없으므로 —
# 실제 질문 텍스트는 ConfirmedFact.source_question_text에 별도로 저장한다).
FACT_TYPES = (
    "frequency", "task", "achievement",
    "hardship_and_coping", "motivation",
    "study_method", "study_goal",
    "role_and_responsibility", "outcome", "context",
    "followup",
    "content_application", "technical_detail",
)
SOURCE_TYPES = ("user_confirmed", "user_edited", "record_cited")


class ConfirmedFact(Base):
    """정직성 가드레일의 핵심 테이블.

    source_type은 반드시 user_confirmed / user_edited / record_cited 중 하나여야 한다.
    AI가 임의로 생성한 사실을 여기에 삽입해서는 안 된다.
    """

    __tablename__ = "confirmed_facts"
    __table_args__ = (
        CheckConstraint(f"fact_type IN {FACT_TYPES}", name="ck_confirmed_facts_fact_type"),
        CheckConstraint(f"source_type IN {SOURCE_TYPES}", name="ck_confirmed_facts_source_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("activity_categories.id", ondelete="CASCADE"), nullable=False)
    fact_type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("record_chunks.id", ondelete="SET NULL"), nullable=True)
    ai_draft_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 실제로 던진 질문 문구. fact_type이 대부분 "followup"으로 뭉뚱그려지는 새 엔진에서는
    # 이 컬럼이 "무엇에 대한 답이었는지"의 유일한 근거다. 마이그레이션 이전 행은 NULL.
    source_question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    category: Mapped["ActivityCategory"] = relationship("ActivityCategory", back_populates="confirmed_facts")
    source_chunk: Mapped["RecordChunk | None"] = relationship("RecordChunk")
