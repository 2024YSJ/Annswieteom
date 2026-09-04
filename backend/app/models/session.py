from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

# 원래는 카테고리당 FREQ/TASK/ACHIEVEMENT x DRAFT/CONFIRM 6개 상태로 정확히 3턴만
# 진행했다 — 카테고리별 진행 상황(어떤 질문까지 답했는지, 몇 턴째인지)을 세션 상태
# 문자열이 아니라 ActivityCategory/ConfirmedFact 데이터에서 파생시키는 에이전틱
# 인터뷰 엔진으로 옮기며 단일 INTERVIEWING으로 합쳤다 — app/services/interview_orchestrator.py,
# app/services/interview_question_bank.py 참고.
SESSION_STATUSES = (
    "PERIOD_INPUT",
    "CATEGORY_SELECT",
    "RECORD_UPLOAD",
    "INTERVIEWING",
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
    # 사용자가 사이드바에서 붙인 이름. None이면 프론트가 생성일자로 대체 표시한다
    # (frontend/app/sessions/layout.tsx).
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PERIOD_INPUT")
    current_category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("activity_categories.id", ondelete="SET NULL"), nullable=True)
    # 현재 턴의 질문+답변 추출 후보를 interview/confirm이 쓸 때까지 들고 있는 임시 저장소.
    # 모양: {category_id, question_text, question_source, fact_type_hint,
    #        context_excerpt_ids, candidate_facts}. candidate_facts는 /interview/answer가
    # 채우기 전까지 None이다. confirmed_facts에는 절대 직접 안 들어간다 — 정직성 가드레일
    # 위반은 이 컬럼이 아니라 insert 경로가 늘어나는 것이므로 무관하다.
    pending_turn: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    gap_period: Mapped["GapPeriod | None"] = relationship("GapPeriod", back_populates="session", cascade="all, delete-orphan", uselist=False)
    categories: Mapped[list["ActivityCategory"]] = relationship("ActivityCategory", back_populates="session", cascade="all, delete-orphan", foreign_keys="ActivityCategory.session_id")
    records: Mapped[list["Record"]] = relationship("Record", back_populates="session", cascade="all, delete-orphan")
    documents: Mapped[list["GeneratedDocument"]] = relationship("GeneratedDocument", back_populates="session", cascade="all, delete-orphan")
