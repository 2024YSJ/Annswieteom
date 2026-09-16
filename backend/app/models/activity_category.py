from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, func
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
    # 2026-09-17: 인턴십(정규직 채용 목적의 구조화된 근무)과 동호회/모임(목표
    # 주도적이지 않은 가벼운 사교 활동)을 각각 part_time/study로 억지로 분류하던
    # 문제(6인 페르소나 검증 라운드에서 재현)를 고치려고 추가 — 기존 8종 중
    # 어디에도 자연스럽게 안 맞았다.
    "internship",
    "club",
    "other",
)

CATEGORY_STATUSES = ("PENDING", "IN_PROGRESS", "DONE")

# period_start/period_end를 누가 채웠는지. "ai_inferred"는 확정 사실에서 LLM이
# 유추한 값이라 커버리지 계산과 UI 표시에만 쓰이고, "user_set"은 사용자가 직접
# 고친 값이다. 둘 다 confirmed_facts로는 절대 들어가지 않으므로 생성 문서에
# 인용될 일이 없다 — 정직성 가드레일 바깥의 메타데이터다.
PERIOD_SOURCES = ("ai_inferred", "user_set")


class ActivityCategory(Base):
    __tablename__ = "activity_categories"
    __table_args__ = (
        CheckConstraint(f"category_type IN {CATEGORY_TYPES}", name="ck_activity_categories_type"),
        CheckConstraint(f"status IN {CATEGORY_STATUSES}", name="ck_activity_categories_status"),
        # NULL은 CHECK를 통과한다(SQL 3값 논리) — "아직 기간을 모른다"가 정상 상태다.
        CheckConstraint(f"period_source IN {PERIOD_SOURCES}", name="ck_activity_categories_period_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    category_type: Mapped[str] = mapped_column(String(50), nullable=False)
    custom_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # 이 카테고리에서 지금까지 던진 고정 질문 개수. 고정 질문은 카테고리 유형별로
    # 정해진 짧은 목록(BASE_QUESTIONS)이라 예산 상한이 필요 없다 — 순전히 기록용.
    questions_asked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 고정 질문 사이/이후에 AI가 끼워넣는 드릴다운·후속 질문 개수. questions_asked와
    # 분리한 이유(2026-09-06): 예전엔 하나의 상한(MAX_QUESTIONS_PER_CATEGORY)이 고정+AI
    # 질문을 합쳐서 셌는데, 그래서 고정 질문이 5개인 카테고리(project/freelance/other)는
    # AI가 파고들 여지가 사실상 1턴뿐이었고, 예산이 바닥나면 고정 질문(특히 결과/성과
    # 질문)이 아직 안 나왔어도 강제로 다음 카테고리로 넘어가 버렸다. 이제 고정 질문은
    # 절대 건너뛰지 않고 전부 물어보며, 이 카운터만 interview_orchestrator.
    # MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY와 짝을 이뤄 별도로 상한을 강제한다.
    followup_questions_asked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    # 이 활동이 실제로 걸쳐 있던 기간. "공백기 채우기"라는 이름을 걸어놓고도
    # 2026-09-09까지 서비스는 공백기가 얼마나 채워졌는지 계산할 수 없었다 —
    # gap_periods에 전체 시작/끝만 있고 활동 쪽에는 날짜가 전혀 없었기 때문이다.
    # 이 두 컬럼이 app/services/coverage.py의 유일한 입력이다.
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 이 카테고리에서 답했지만 아직 확인받지 않은 턴들(카테고리 단위 확인, 2026-09-11).
    # 답변 하나 = 턴 하나: {turn_id, answer_log_id, question_text, question_source,
    # fact_type_hint, answer_text, drafts: [{content, based_on}]}. 카테고리 끝 확인
    # (POST /interview/review)에서 confirmed_facts로 옮겨지고 NULL로 비워진다.
    # **정직성 가드레일:** 이 값은 진행 판단과 LLM 컨텍스트에만 쓰이고 문서에는
    # 절대 인용되지 않는다 — 인용은 confirmed_facts뿐이다.
    # JSON 컬럼은 제자리 변경을 추적하지 않으므로 항상 새 리스트로 재할당한다.
    draft_turns: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship("Session", back_populates="categories", foreign_keys=[session_id])
    confirmed_facts: Mapped[list["ConfirmedFact"]] = relationship("ConfirmedFact", back_populates="category", cascade="all, delete-orphan")
    generated_sentences: Mapped[list["GeneratedSentence"]] = relationship("GeneratedSentence", back_populates="category", cascade="all, delete-orphan")
    records: Mapped[list["Record"]] = relationship("Record", back_populates="category", order_by="Record.created_at")

    @property
    def label(self) -> str:
        return self.custom_label or self.category_type
