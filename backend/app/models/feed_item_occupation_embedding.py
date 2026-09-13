from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.record_chunk import EMBEDDING_DIM


class FeedItemOccupationEmbedding(Base):
    """feed_items 한 행의 **제목만** 임베딩한 bge-m3 벡터 — 직무 관련성 전용.

    FeedItemEmbedding(embed_text = title+subtitle+meta_lines)과 별도인 이유는
    지역·회사명·날짜 같은 메타 텍스트가 직무 신호를 희석하기 때문이다
    (services/feed/matching.py의 occupation_score 참고). feed_kind와 무관하게
    채용공고·훈련과정·정책 전부 이 테이블에 한 행씩 갖는다 — 세 화면(맞춤
    공고/훈련/정책) 모두 같은 벡터를 재사용한다.

    1:1 곁테이블·nullable인 이유는 FeedItemEmbedding과 완전히 같다(pgvector
    Vector가 SQLite에서 컴파일 안 됨, 임베딩 실패해도 항목은 남아야 함).
    """

    __tablename__ = "feed_item_occupation_embeddings"

    feed_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feed_items.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
