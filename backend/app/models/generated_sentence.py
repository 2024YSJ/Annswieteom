from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class GeneratedSentence(Base):
    __tablename__ = "generated_sentences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("generated_documents.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("activity_categories.id", ondelete="CASCADE"), nullable=False)
    # nullable: 이 컬럼이 생기기 전 문장에는 소급 적용할 그룹 정보가 없다 —
    # 그런 문장은 "그 문장 하나짜리 문단"으로 취급한다(_document_read 참고).
    paragraph_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("generated_paragraphs.id", ondelete="CASCADE"), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # 제네릭 JSON(“JSONB 아님”): pending_draft(90edf5d28f6a)와 같은 이유 — 이 컬럼은
    # 내용으로 쿼리/인덱싱할 일이 없어 JSONB의 이점이 필요 없고, SQLite(테스트)와
    # Postgres 양쪽에서 컴파일되는 타입이어야 한다.
    evidence_fact_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    consistency_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 판정을 내린 실제 코사인 유사도. 예전에는 bool만 남기고 이 값을 버렸는데, 그래서
    # settings.consistency_threshold(0.55)를 실제 샘플에 맞춰 조정할 근거 데이터가
    # 아예 없었다 — 실패한 문장이 0.54였는지 0.11이었는지 구분이 안 됐다.
    # 마이그레이션 이전 문장은 NULL.
    consistency_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 사용자가 PATCH로 직접 고쳐 쓴 문장인지. consistency_check_passed는 사용자가
    # 쓴 문장에 대해서도 True로 두지만(본인이 쓴 말은 정의상 확인된 사실이다),
    # 그 True를 "임베딩 검증을 통과했다"와 같은 배지로 보여주면 거짓말이 된다 —
    # 프론트가 둘을 구분해 표시할 수 있도록 별도 플래그로 남긴다.
    edited_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["GeneratedDocument"] = relationship("GeneratedDocument", back_populates="sentences")
    category: Mapped["ActivityCategory"] = relationship("ActivityCategory", back_populates="generated_sentences")
    paragraph: Mapped["GeneratedParagraph | None"] = relationship("GeneratedParagraph", back_populates="sentences")
