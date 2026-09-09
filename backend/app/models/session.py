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
    # kind="job_search" 전용 — gap-fill의 6개와 같은 컬럼을 공유한다(별도 상태
    # 컬럼을 두지 않음, Session이 이미 상태머신 전용 모델이라 굳이 분리할
    # 이유가 없음). 취업 정보 종합 검색으로 전환하면서(2026-09-08, devlog 16)
    # 더 이상 단계 전이가 없는 상시 대화형 세션이 됐으므로 생성 시점부터
    # 계속 이 값 하나로 고정된다 — JOB_PREFERENCES_INPUT/JOB_RESULTS_REVIEW는
    # 이전 턴 기반 조건 입력 UI가 쓰던 값으로 이제 안 쓰이지만, CHECK 제약에서
    # 빼는 마이그레이션까지는 필요 없어 그대로 남겨둔다.
    "JOB_PREFERENCES_INPUT",
    "JOB_SEARCHING",
    "JOB_RESULTS_REVIEW",
)

SESSION_KINDS = ("gap_fill", "job_search")


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(f"status IN {SESSION_STATUSES}", name="ck_sessions_status"),
        CheckConstraint(f"kind IN {SESSION_KINDS}", name="ck_sessions_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # 사용자가 사이드바에서 붙인 이름. None이면 프론트가 생성일자로 대체 표시한다
    # (frontend/app/sessions/layout.tsx).
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # "gap_fill"(공백기 채우기, 기본값) | "job_search"(일자리 찾기) — 어느
    # 오케스트레이터/status enum을 쓸지 프론트가 이 값으로 분기한다.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="gap_fill")
    # kind="job_search" 세션이 공백기 채우기 결과에서 연동돼 만들어졌을 때만
    # 채워짐 — seed-from-gap 엔드포인트가 이 값을 보고 어느 세션의
    # confirmed_facts를 읽을지 결정한다. 원본 세션이 삭제돼도 이 세션 자체는
    # 남아야 하므로 SET NULL(CASCADE 아님).
    linked_gap_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
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
    # 위 넷과 달리 delete cascade가 없다 — 문답 기록은 계정에 쌓이는 것이라
    # 세션이 지워져도 살아남아야 한다. cascade를 생략하면 SQLAlchemy가 부모 삭제
    # 시 session_id를 NULL로 UPDATE하므로, DB의 ON DELETE SET NULL과 같은 결과를
    # ORM 레벨에서도 보장한다(SQLite는 기본적으로 FK 동작을 강제하지 않는다).
    interview_answers: Mapped[list["InterviewAnswer"]] = relationship("InterviewAnswer", back_populates="session")
