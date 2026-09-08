from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class JobSearchPreferences(Base):
    """Confirmed job-search preferences for a `kind="job_search"` session —
    one row per session, same 1:1 shape as `GapPeriod` for gap-fill sessions.

    Populated only via the confirm step (`POST /job-search/preferences`) —
    never written directly from an LLM suggestion, same honesty-guardrail
    principle as `confirmed_facts`.
    """

    __tablename__ = "job_search_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # 직무/분야 키워드(예: "백엔드 개발", "마케팅") — 워크넷 검색의 실질적인
    # 1순위 검색어. desired_ 접두어는 다른 desired_* 컬럼과의 일관성.
    desired_keyword: Mapped[str | None] = mapped_column(String(200), nullable=True)
    desired_salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desired_salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desired_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    education_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    career_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_style_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 최초 1회차 대화형 질문(job_search_question_bank.JOB_SEARCH_QUESTIONS) 중
    # 이미 답한 필드 id 목록 — 다음 질문을 고르는 데만 쓰인다. 6개 다 채워지면
    # 그 시점부터 이 세션은 "확정 후 재편집" 플로우로 넘어가고 이 컬럼은
    # 더 이상 안 쓰인다.
    completed_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    free_text_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 마지막 검색+적합도 판단 결과 캐시 — 새로고침 시 외부 API/LLM을 다시
    # 호출하지 않고 바로 보여주기 위함. 세션당 가장 최근 검색 1건만 보관한다
    # (스펙 결정: 저장/북마크 기능은 후속 과제).
    last_searched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_results: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    session: Mapped["Session"] = relationship("Session", back_populates="job_search_preferences")
