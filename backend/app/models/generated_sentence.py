from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class GeneratedSentence(Base):
    __tablename__ = "generated_sentences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("generated_documents.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("activity_categories.id", ondelete="CASCADE"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # 제네릭 JSON(“JSONB 아님”): pending_draft(90edf5d28f6a)와 같은 이유 — 이 컬럼은
    # 내용으로 쿼리/인덱싱할 일이 없어 JSONB의 이점이 필요 없고, SQLite(테스트)와
    # Postgres 양쪽에서 컴파일되는 타입이어야 한다.
    evidence_fact_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    consistency_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["GeneratedDocument"] = relationship("GeneratedDocument", back_populates="sentences")
    category: Mapped["ActivityCategory"] = relationship("ActivityCategory", back_populates="generated_sentences")
