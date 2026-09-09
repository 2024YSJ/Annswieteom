from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.record_chunk import EMBEDDING_DIM


class FeedItemEmbedding(Base):
    """feed_items 한 행의 bge-m3 벡터. 본체와 1:1이며 PK가 곧 FK다.

    별도 테이블인 이유는 feed_item.py의 docstring 참고 — Vector 컬럼이 붙은
    테이블은 SQLite에서 만들 수 없어서, 이걸 feed_items에 얹으면 피드 API를
    테스트할 수 없게 된다.

    PK == FK라서 "아직 임베딩 안 된 항목"이 LEFT JOIN ... IS NULL 한 줄로
    나온다. embedding이 nullable인 것도 의도적이다 — Gemini 제거 후 임베딩
    경로는 로컬 Ollama 하나뿐이라 터널이 끊기면 100% 실패하는데, 그때도
    항목 자체는 남고 최신순으로 노출돼야 한다(services/feed/ingest.py).
    """

    __tablename__ = "feed_item_embeddings"

    feed_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feed_items.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
