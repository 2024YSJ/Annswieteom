from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class FeedRefreshState(Base):
    """소스별 마지막 수집 상태. source_key는 "worknet:job_fair" 같은 형태다.

    프로세스 메모리 대신 테이블인 이유가 둘 있다.

    1. **동시 갱신 방지.** 캐시가 비었거나 만료된 상태에서 메인 화면에 동시
       접속 10건이 들어오면, 락이 없으면 백그라운드 갱신이 10개 뜨고 담당자
       심사를 거쳐 받은 API 쿼터를 10배로 태운다. last_started_at을 조건에 건
       단일 UPDATE로 compare-and-swap 해서 한 번만 돌게 만든다.
    2. **소스별 실패 가시성.** 어떤 키가 언제 왜 실패했는지가 남아야
       "온통청년 키가 아직 승인 안 난 건지 코드가 깨진 건지"를 구분할 수 있다
       (devlog 15에서 두 번 아쉬웠던 부분).

    락이 불리언이 아니라 시각인 건 의도적이다 — 갱신 도중 프로세스가 죽어도
    FEED_REFRESH_LOCK_SECONDS가 지나면 저절로 풀린다. 진짜 락이 아니라
    권고적(advisory) 장치이고, Railway 단일 인스턴스 전제에서 충분하다.
    """

    __tablename__ = "feed_refresh_states"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
