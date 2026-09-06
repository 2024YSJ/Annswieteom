from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

RECORD_TYPES = ("blog_url", "image", "text", "document")
PLATFORMS = ("naver", "tistory", "velog", "brunch", "other", "unknown")
PARSE_STATUSES = ("PENDING", "PROCESSING", "DONE", "FAILED")


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (
        CheckConstraint(f"record_type IN {RECORD_TYPES}", name="ck_records_type"),
        CheckConstraint(f"platform IN {PLATFORMS}", name="ck_records_platform"),
        CheckConstraint(f"parse_status IN {PARSE_STATUSES}", name="ck_records_parse_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    # nullable at the DB level so pre-existing rows (created before categorized
    # uploads existed) don't need a backfill — application code always sets it
    # going forward, sourced from session.current_category_id (see app/api/records.py).
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("activity_categories.id", ondelete="CASCADE"), nullable=True)
    record_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 업로드된 파일(이미지/문서)의 원래 파일명 — storage_path는 UUID 기반이라 목록에서
    # 여러 파일을 구분할 방법이 없어서 추가(2026-09-06, 다중 파일 업로드 지원과 함께).
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship("Session", back_populates="records")
    category: Mapped["ActivityCategory | None"] = relationship("ActivityCategory", back_populates="records")
    chunks: Mapped[list["RecordChunk"]] = relationship("RecordChunk", back_populates="record", cascade="all, delete-orphan")
