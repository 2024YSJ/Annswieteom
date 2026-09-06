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
    # 이 카테고리에서 지금까지 던진 질문 총 개수(고정+AI 추가 합산) — /interview/ask가
    # 새 질문을 만들 때마다 하나씩 올라간다(같은 질문을 idempotent하게 재반환할 때는
    # 안 올라감). interview_orchestrator.MAX_QUESTIONS_PER_CATEGORY와 짝을 이뤄
    # 카테고리당 총 질문 수 상한을 강제하는 근거 데이터다.
    questions_asked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 이 카테고리 하나 안에 서로 다른 개별 활동이 여러 개 있는지("공모전을 3개 했어요" 같은
    # 경우) 이미 물어봤는지 — 카테고리당 딱 한 번만 묻고, 자식으로 쪼개져 생성된 카테고리는
    # 생성 시점에 바로 True로 만들어 재귀적으로 다시 쪼개려 들지 않게 막는다
    # (interview_orchestrator.py, app/api/interview.py 참고).
    activity_split_checked: Mapped[bool] = mapped_column(nullable=False, default=False)
    # 소분류(예: "공모전" 카테고리 아래의 "OO 공모전", "XX 공모전")를 표현하는 자기참조 FK.
    # 소분류도 평범한 ActivityCategory 행이라 질문은행 조회/questions_asked 카운팅/
    # confirmed_facts.category_id/문서 생성이 전부 그대로 재사용된다 — 카테고리 순회만
    # 트리를 인식하도록 interview_orchestrator._walk_order()가 부모 자리에 자식들을 끼워
    # 넣는다. 부모(컨테이너)는 이 필드가 채워진 자식이 하나라도 있으면 직접 인터뷰되지 않는다.
    parent_category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("activity_categories.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship("Session", back_populates="categories", foreign_keys=[session_id])
    confirmed_facts: Mapped[list["ConfirmedFact"]] = relationship("ConfirmedFact", back_populates="category", cascade="all, delete-orphan")
    generated_sentences: Mapped[list["GeneratedSentence"]] = relationship("GeneratedSentence", back_populates="category", cascade="all, delete-orphan")
    records: Mapped[list["Record"]] = relationship("Record", back_populates="category", order_by="Record.created_at")

    @property
    def label(self) -> str:
        return self.custom_label or self.category_type
