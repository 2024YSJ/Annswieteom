from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

TONES = ("plain", "neutral", "assertive")
DOC_STATUSES = ("DRAFT", "FINAL")


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"
    __table_args__ = (
        CheckConstraint(f"tone IN {TONES}", name="ck_generated_documents_tone"),
        CheckConstraint(f"status IN {DOC_STATUSES}", name="ck_generated_documents_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    tone: Mapped[str] = mapped_column(Text, nullable=False, default="neutral")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="DRAFT")
    # 공유 링크(D)의 불투명 토큰. 대부분의 문서는 절대 공유되지 않으므로 nullable —
    # POST /sessions/{id}/document/share가 처음 호출될 때만 채워진다.
    share_slug: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship("Session", back_populates="documents")
    sentences: Mapped[list["GeneratedSentence"]] = relationship("GeneratedSentence", back_populates="document", cascade="all, delete-orphan")
    paragraphs: Mapped[list["GeneratedParagraph"]] = relationship("GeneratedParagraph", back_populates="document", cascade="all, delete-orphan")
