from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

CATEGORY_TYPES = (
    "part_time",
    "freelance",
    "volunteer",
    "study",
    "project",
    "caregiving",
    "travel",
    "other",
)

CATEGORY_STATUSES = ("PENDING", "IN_PROGRESS", "DONE")


class ActivityCategory(Base):
    __tablename__ = "activity_categories"
    __table_args__ = (
        CheckConstraint(f"category_type IN {CATEGORY_TYPES}", name="ck_activity_categories_type"),
        CheckConstraint(f"status IN {CATEGORY_STATUSES}", name="ck_activity_categories_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    category_type: Mapped[str] = mapped_column(String(50), nullable=False)
    custom_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship("Session", back_populates="categories", foreign_keys=[session_id])
    confirmed_facts: Mapped[list["ConfirmedFact"]] = relationship("ConfirmedFact", back_populates="category", cascade="all, delete-orphan")
    generated_sentences: Mapped[list["GeneratedSentence"]] = relationship("GeneratedSentence", back_populates="category", cascade="all, delete-orphan")
