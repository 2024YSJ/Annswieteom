from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.feed_item import FeedItem
from app.models.feed_item_embedding import FeedItemEmbedding

logger = logging.getLogger(__name__)


@dataclass
class RankedFeed:
    items: list[FeedItem]
    total: int
    personalized: bool
    #: 벡터 질의가 **실패**해서 최신순으로 내려왔는가. `personalized=False`만으로는
    #: 세 가지가 구분되지 않는다 — 프로필이 없거나, 아직 임베딩이 안 채워졌거나,
    #: 정말 고장났거나. 라우터가 "AI 서버가 수리 중" 안내를 띄울지 정하는 데 쓴다.
    vector_ranking_failed: bool = False
    #: 티어 매칭(services/feed/matching.py)이 채운다 — 항목 id → ItemMatch.
    #: 벡터/최신순 경로에서는 비어 있다.
    matches: dict = field(default_factory=dict)


def _scope(stmt: Select, category: str | None, categories: tuple[str, ...] | None) -> Select:
    """카테고리 하나(사용자가 고른 필터) 또는 섹션의 카테고리 묶음으로 좁힌다.

    같은 feed_kind 안에서도 섹션이 갈린다 — "policy"에는 온통청년 정책과 고용24
    훈련과정·구직자프로그램이 함께 저장돼 있다(models/feed_item.py 섹션 상수 참고).
    """
    if category is not None:
        return stmt.where(FeedItem.category == category)
    if categories is not None:
        return stmt.where(FeedItem.category.in_(categories))
    return stmt


def _base(feed_kind: str, category: str | None, categories: tuple[str, ...] | None = None) -> Select:
    stmt = select(FeedItem).where(FeedItem.is_active.is_(True), FeedItem.feed_kind == feed_kind)
    return _scope(stmt, category, categories)


async def _count(
    db: AsyncSession, feed_kind: str, category: str | None, categories: tuple[str, ...] | None = None
) -> int:
    stmt = select(func.count(FeedItem.id)).where(
        FeedItem.is_active.is_(True), FeedItem.feed_kind == feed_kind
    )
    return int(await db.scalar(_scope(stmt, category, categories)) or 0)


async def _count_embedded(
    db: AsyncSession, feed_kind: str, category: str | None, categories: tuple[str, ...] | None = None
) -> int:
    """개인화 정렬로 실제 도달 가능한 행 수.

    전체 활성 행 수를 그대로 `total`로 내보내면 벡터가 아직 없는 행까지 세는
    셈이라, 프론트의 "더보기"가 갈 수 없는 페이지로 가는 버튼을 그린다.
    """
    stmt = (
        select(func.count(FeedItem.id))
        .join(FeedItemEmbedding, FeedItemEmbedding.feed_item_id == FeedItem.id)
        .where(
            FeedItem.is_active.is_(True),
            FeedItem.feed_kind == feed_kind,
            FeedItemEmbedding.embedding.is_not(None),
        )
    )
    return int(await db.scalar(_scope(stmt, category, categories)) or 0)


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


def _interleaved_order(stmt: Select) -> Select:
    """카테고리를 라운드로빈으로 섞은 최신순.

    순수 최신순으로 두면 목록이 **카테고리 덩어리**가 된다. 한 번의 수집이
    카테고리를 차례로 넣으므로 마지막에 들어간 카테고리가 통째로 맨 위를
    차지하기 때문이다. 실측(2026-09-10, 공고 200건)에서는 강소기업 50건이
    앞을 다 막고 있었는데, 하필 그 카테고리만 고용24가 상세 URL도 항목 id도
    주지 않아 **링크를 달 수 없는 카드 50장을 지나야 눌리는 카드가 나왔다.**

    그래서 카테고리별 최신 1건씩을 먼저 모으고, 그다음 2건씩을 모은다.
    limit/offset 페이지네이션이 그대로 성립하도록 순서는 완전히 결정적이어야
    하므로 (순번, 수집시각, id) 세 단계로 정렬한다.
    """
    rank = func.row_number().over(
        partition_by=FeedItem.category,
        order_by=(FeedItem.first_seen_at.desc(), FeedItem.id),
    ).label("category_rank")
    sub = stmt.add_columns(rank).subquery()
    item = aliased(FeedItem, sub)
    return select(item).order_by(sub.c.category_rank, sub.c.first_seen_at.desc(), sub.c.id)


async def rank_feed_items(
    db: AsyncSession,
    *,
    feed_kind: str,
    category: str | None = None,
    categories: tuple[str, ...] | None = None,
    profile_vector: list[float] | None = None,
    prefer_published_date: bool = False,
    interleave_categories: bool = False,
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
    total = await _count(db, feed_kind, category, categories)
    vector_failed = False

    if profile_vector is not None:
        stmt = (
            _base(feed_kind, category, categories)
            .join(FeedItemEmbedding, FeedItemEmbedding.feed_item_id == FeedItem.id)
            .where(FeedItemEmbedding.embedding.is_not(None))
            .order_by(FeedItemEmbedding.embedding.cosine_distance(profile_vector), FeedItem.id)
            .limit(limit)
            .offset(offset)
        )
        try:
            embedded_total = await _count_embedded(db, feed_kind, category, categories)
            rows = (await db.execute(stmt)).scalars().all() if embedded_total else None
        except Exception:
            await db.rollback()
            logger.warning("feed: vector ranking unavailable; falling back to recency", exc_info=True)
            rows = None
            vector_failed = True
        # `rows == []`를 실패로 읽으면 안 된다. 개인화 목록의 끝을 넘어선
        # offset(= "더보기"의 마지막 클릭)에서 같은 offset으로 최신순 분기에
        # 떨어지면, 정렬이 다른 목록의 N번째 페이지가 나와 **이미 본 카드가
        # 다시 보인다.** 벡터가 하나도 없을 때(embedded_total == 0)만
        # 최신순으로 내려간다.
        if rows is not None:
            return RankedFeed(items=list(rows), total=embedded_total, personalized=True)

    base = _base(feed_kind, category, categories)
    # 카테고리를 하나만 골라 본다면 섞을 게 없다.
    ordered = (
        _interleaved_order(base)
        if interleave_categories and category is None
        else _recent_order(base, prefer_published_date)
    )
    stmt = ordered.limit(limit).offset(offset)
    return RankedFeed(
        items=list((await db.execute(stmt)).scalars().all()),
        total=total,
        personalized=False,
        vector_ranking_failed=vector_failed,
    )


def get_feed_ranker():
    """FastAPI DI 훅 — 라우터가 rank_feed_items를 직접 import하지 않게 해서
    테스트가 정렬 결과를 고정할 수 있게 한다."""
    return rank_feed_items


__all__ = ["RankedFeed", "get_feed_ranker", "rank_feed_items"]
