from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.record_chunk import EMBEDDING_DIM


class UserOccupationEmbedding(Base):
    """희망직무(desired_job) 한 줄짜리 텍스트의 bge-m3 벡터. users.id에 1:1.

    UserProfileEmbedding(문답 아카이브 전체를 요약한 커지는 텍스트)과 달리
    지문/개수/시각 삼종 검사가 필요 없다 — 원본이 "백엔드 프로그래머" 같은
    짧은 고정 문자열 하나뿐이라 source_text와의 단순 등가 비교로 충분하다
    (services/feed/occupation_adapter.py). 과설계를 피하려고 일부러 뺐다.
    """

    __tablename__ = "user_occupation_embeddings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 이 임베딩을 만든 원문 desired_job. 값이 바뀌면 그것만으로 재계산 트리거.
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
