from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.record_chunk import EMBEDDING_DIM


class UserProfileEmbedding(Base):
    """맞춤 공고 정렬에 쓰는 사용자 1명분 벡터. users.id에 1:1.

    **이 테이블은 우리 것이다.** 개인화 신호의 원천은 interview_answers(다른
    작업에서 만든 계정 단위 문답 아카이브)지만, 그 테이블에 컬럼을 붙이거나
    users에 얹지 않고 별도로 둔다 — 이건 사용자 데이터가 아니라 우리 모델
    (bge-m3, 1024차원)의 파생 캐시이고, 원천 테이블이 나중에 바뀌어도 스키마가
    끌려가면 안 되기 때문이다. 통째로 TRUNCATE 해도 source_fingerprint 덕에
    다음 요청부터 알아서 다시 채워진다.

    source_fingerprint는 실제로 임베딩한 프로필 텍스트의 sha256이다. 문답이
    늘었는지 확인하려고 매번 텍스트를 다시 만들 필요 없이,
    source_answer_count / source_latest_answer_at만 세어보는 싼 1차 검사로
    거른 뒤 지문으로 2차 확인한다(services/feed/profile_adapter.py).
    """

    __tablename__ = "user_profile_embeddings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_answer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_latest_answer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 디버깅용으로 남긴다 — "왜 이 사용자에게 이 공고가 위로 왔나"를 볼 때
    # 벡터만 있으면 아무것도 알 수 없다.
    profile_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
