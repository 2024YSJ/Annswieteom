from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feed_item import FeedItem
from app.models.feed_item_embedding import FeedItemEmbedding

logger = logging.getLogger(__name__)


@dataclass
class RankedFeed:
    items: list[FeedItem]
    total: int
    personalized: bool


def _base(feed_kind: str, category: str | None) -> Select:
    stmt = select(FeedItem).where(FeedItem.is_active.is_(True), FeedItem.feed_kind == feed_kind)
    if category is not None:
        stmt = stmt.where(FeedItem.category == category)
    return stmt


async def _count(db: AsyncSession, feed_kind: str, category: str | None) -> int:
    stmt = select(func.count(FeedItem.id)).where(
        FeedItem.is_active.is_(True), FeedItem.feed_kind == feed_kind
    )
    if category is not None:
        stmt = stmt.where(FeedItem.category == category)
    return int(await db.scalar(stmt) or 0)


def _recent_order(stmt: Select, by_published: bool) -> Select:
    """최신순.

    `FeedItem.id` 타이브레이커는 장식이 아니다 — 한 번의 수집 배치는
    first_seen_at이 마이크로초까지 같아서, 결정적 2차 키가 없으면
    limit/offset 페이지네이션이 조용히 행을 중복시키고 누락시킨다.

    정책 피드는 소스 등록일을 우선하되 없으면 수집 시각으로 갈음한다.
    nullslast() 대신 coalesce를 쓰는 이유는 SQLite와 Postgres 양쪽에서
    똑같이 동작해야 테스트가 되기 때문이다.
    """
    if by_published:
        return stmt.order_by(
            func.coalesce(FeedItem.source_published_at, func.date(FeedItem.first_seen_at)).desc(),
            FeedItem.first_seen_at.desc(),
            FeedItem.id,
        )
    return stmt.order_by(FeedItem.first_seen_at.desc(), FeedItem.id)


async def rank_feed_items(
    db: AsyncSession,
    *,
    feed_kind: str,
    category: str | None = None,
    profile_vector: list[float] | None = None,
    prefer_published_date: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> RankedFeed:
    """피드 한 페이지.

    프로필 벡터가 있으면 코사인 거리순, 없거나 실패하면 최신순.
    벡터 질의 실패(pgvector 없음 / 차원 불일치 / 테이블 없음)는 전부 조용히
    최신순으로 내려간다 — record_pipeline/search.py의 3단 폴백과 같은 방어이고,
    사용자가 잃는 건 정렬 품질이지 피드 자체가 아니어야 한다.
    피드 읽기는 아무것도 쓰지 않으므로 요청 세션에서 rollback을 불러도 안전하다.
    """
    total = await _count(db, feed_kind, category)

    if profile_vector is not None:
        stmt = (
            _base(feed_kind, category)
            .join(FeedItemEmbedding, FeedItemEmbedding.feed_item_id == FeedItem.id)
            .where(FeedItemEmbedding.embedding.is_not(None))
            .order_by(FeedItemEmbedding.embedding.cosine_distance(profile_vector), FeedItem.id)
            .limit(limit)
            .offset(offset)
        )
        try:
            rows = (await db.execute(stmt)).scalars().all()
        except Exception:
            await db.rollback()
            logger.warning("feed: vector ranking unavailable; falling back to recency", exc_info=True)
            rows = None
        if rows:
            return RankedFeed(items=list(rows), total=total, personalized=True)

    stmt = _recent_order(_base(feed_kind, category), prefer_published_date).limit(limit).offset(offset)
    return RankedFeed(items=list((await db.execute(stmt)).scalars().all()), total=total, personalized=False)


def get_feed_ranker():
    """FastAPI DI 훅 — 라우터가 rank_feed_items를 직접 import하지 않게 해서
    테스트가 정렬 결과를 고정할 수 있게 한다."""
    return rank_feed_items


__all__ = ["RankedFeed", "get_feed_ranker", "rank_feed_items"]
