from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

SESSION_STATUSES = (
    "PERIOD_INPUT",
    "CATEGORY_SELECT",
    "INTERVIEW_FREQ",
    "INTERVIEW_TASK",
    "INTERVIEW_ACHIEVEMENT",
    "RECORD_UPLOAD",
    "GENERATING",
    "DONE",
)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(f"status IN {SESSION_STATUSES}", name="ck_sessions_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PERIOD_INPUT")
    current_category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("activity_categories.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    gap_period: Mapped["GapPeriod | None"] = relationship("GapPeriod", back_populates="session", cascade="all, delete-orphan", uselist=False)
    categories: Mapped[list["ActivityCategory"]] = relationship("ActivityCategory", back_populates="session", cascade="all, delete-orphan", foreign_keys="ActivityCategory.session_id")
    records: Mapped[list["Record"]] = relationship("Record", back_populates="session", cascade="all, delete-orphan")
    documents: Mapped[list["GeneratedDocument"]] = relationship("GeneratedDocument", back_populates="session", cascade="all, delete-orphan")
