from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

CONSENT_TYPES = ("sensitive_profiling",)


class UserConsent(Base):
    """사용자 동의 기록. 지금은 `sensitive_profiling` 하나 — 소득·특화분야
    (장애·기초생활수급·한부모 등)·혼인 정보를 대화에서 묻고 저장해도 되는가.

    `sensitive_mentioned_at`은 동의가 **없는** 상태에서 사용자가 스스로 그런
    정보를 말했을 때 찍힌다. 값 자체는 저장하지 않는다 — 프로필 화면이 "말씀하신
    정보를 저장하려면 동의가 필요해요"를 띄우는 신호로만 쓴다.
    """

    __tablename__ = "user_consents"
    # f"IN {CONSENT_TYPES}"를 쓰면 원소가 하나인 튜플이 "('sensitive_profiling',)"로
    # 찍혀 SQL 문법 오류가 난다 — 목록을 직접 이어 붙인다.
    __table_args__ = (
        CheckConstraint(
            "consent_type IN (" + ", ".join(f"'{t}'" for t in CONSENT_TYPES) + ")", name="ck_user_consents_type"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    consent_type: Mapped[str] = mapped_column(Text, primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sensitive_mentioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
