from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

# 명세서 8-2절 상태 전이표 그대로. 이전에는 다른 이름 세트(INTERVIEW_FREQ 등)가 들어있어
# 상태머신 구현 시 발견 후 이 값으로 교정했다 — app/services/interview_orchestrator.py 참고.
SESSION_STATUSES = (
    "PERIOD_INPUT",
    "CATEGORY_SELECT",
    "RECORD_UPLOAD",
    "FREQ_DRAFT",
    "FREQ_CONFIRM",
    "TASK_DRAFT",
    "TASK_CONFIRM",
    "ACHIEVEMENT_DRAFT",
    "ACHIEVEMENT_CONFIRM",
    "RESULT_GENERATE",
    "RESULT_REVIEW",
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
    # interview/next가 반환한 초안을 interview/confirm이 쓸 때까지 잠깐 들고 있는 임시 저장소
    # (02_interview_state_machine_api.md 4절). confirmed_facts에는 절대 직접 안 들어간다 —
    # 정직성 가드레일 위반은 이 컬럼이 아니라 insert 경로가 늘어나는 것이므로 무관하다.
    pending_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    gap_period: Mapped["GapPeriod | None"] = relationship("GapPeriod", back_populates="session", cascade="all, delete-orphan", uselist=False)
    categories: Mapped[list["ActivityCategory"]] = relationship("ActivityCategory", back_populates="session", cascade="all, delete-orphan", foreign_keys="ActivityCategory.session_id")
    records: Mapped[list["Record"]] = relationship("Record", back_populates="session", cascade="all, delete-orphan")
    documents: Mapped[list["GeneratedDocument"]] = relationship("GeneratedDocument", back_populates="session", cascade="all, delete-orphan")
