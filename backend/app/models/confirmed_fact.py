from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

FACT_TYPES = ("frequency", "task", "achievement")
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    category: Mapped["ActivityCategory"] = relationship("ActivityCategory", back_populates="confirmed_facts")
    source_chunk: Mapped["RecordChunk | None"] = relationship("RecordChunk")
