from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class GeneratedParagraph(Base):
    """유사 주제의 문장들을 묶는 단위. 카테고리 하나가 여러 문단을 낼 수 있다
    (예: 같은 프로젝트 카테고리 안에서도 "무엇을 했다"와 "왜 했는지/동기"가
    서로 다른 문단으로 묶일 수 있음). 카테고리를 가로지르는 병합은 지원하지
    않는다 — document_generator.py가 카테고리 단위로만 문단을 생성한다.
    """

    __tablename__ = "generated_paragraphs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("generated_documents.id", ondelete="CASCADE"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    # 사용자가 "이 그룹핑 맞음"이라고 확인했는지 — 최종 확정(finalize) 자체를
    # 막지는 않는다(문장별 consistency_check_passed와 같은 성격의 참고 표시일
    # 뿐, 강제 게이트는 아니다).
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["GeneratedDocument"] = relationship("GeneratedDocument", back_populates="paragraphs")
    sentences: Mapped[list["GeneratedSentence"]] = relationship("GeneratedSentence", back_populates="paragraph")
