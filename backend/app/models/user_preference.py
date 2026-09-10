from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

#: 사용자가 직접 쓰는 희망사항 길이 상한. 임베딩 입력의 일부라 무한정 길면
#: 문답 쪽 신호를 덮어버린다(profile_adapter의 4000자 상한과 같은 맥락).
WISH_TEXT_MAX_CHARS = 1000


class UserPreference(Base):
    """사용자가 직접 적는 "맞춤 정보" — 어떤 일을 찾고 있는지 자유 텍스트.

    맞춤 공고 정렬은 지금까지 `interview_answers`(인터뷰 답변 원문)에서만
    만들어졌다. 그래서 **공백기 정리를 아직 안 한 사용자는 손댈 수 있는 게
    아무것도 없었다** — 정렬이 마음에 안 들어도 인터뷰를 처음부터 하는 것 말고는
    방법이 없었다(2026-09-10 요청).

    이 테이블은 그 조종간이다. 여기 적은 내용은 문답과 함께 프로필 텍스트로
    합쳐져 임베딩된다(services/feed/profile_adapter.py).

    **`user_profile_embeddings`와 다르다.** 그쪽은 언제든 지워도 되는 파생
    캐시지만, 이건 사용자가 직접 입력한 원본이라 지우면 복구가 안 된다.
    그래서 별도 테이블로 둔다.
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    wish_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
