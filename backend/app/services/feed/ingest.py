from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.feed_item import FeedItem
from app.models.feed_item_embedding import FeedItemEmbedding
from app.models.feed_refresh_state import FeedRefreshState
from app.services.embedding import LocalOllamaEmbedding
from app.services.feed.dedup import build_embed_text, compute_dedup_key
from app.services.feed.sources import FeedItemData, FeedSource, configured_sources, source_keys_for

logger = logging.getLogger(__name__)

#: 갱신 중이라고 표시된 뒤 이 시간이 지나면 락을 뺏는다. 불리언이 아니라
#: 시각인 이유는 갱신 도중 프로세스가 죽어도 저절로 풀리게 하기 위해서다.
FEED_REFRESH_LOCK = timedelta(minutes=10)

#: 실패한 소스를 다시 시도하기까지의 최소 간격. 이게 없으면 영구히 고장난
#: 인증키 하나가 메인 화면을 열 때마다 재시도를 유발한다.
FEED_FAILED_RETRY = timedelta(minutes=10)

#: 로컬 Ollama에 한 번에 보내는 임베딩 개수. /api/embed는 배치를 지원한다.
EMBED_BATCH = 16

#: 소스 목록에서 사라진 지 이만큼 지난 항목은 실제로 지운다.
PRUNE_AFTER = timedelta(days=14)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stale_before() -> datetime:
    return _now() - timedelta(seconds=settings.feed_refresh_ttl_seconds)


async def _load_states(db: AsyncSession, source_keys: list[str]) -> dict[str, FeedRefreshState]:
    if not source_keys:
        return {}
    rows = (
        await db.execute(select(FeedRefreshState).where(FeedRefreshState.source_key.in_(source_keys)))
    ).scalars().all()
    return {r.source_key: r for r in rows}


def _is_stale(state: FeedRefreshState | None, stale_before: datetime, now: datetime) -> bool:
    if state is None or state.last_succeeded_at is None:
        return True
    if _aware(state.last_succeeded_at) < stale_before:
        # 방금 실패한 키는 잠깐 쉬게 둔다.
        if state.last_failed_at is not None and _aware(state.last_failed_at) > now - FEED_FAILED_RETRY:
            return False
        return True
    return False


def _aware(value: datetime) -> datetime:
    """SQLite는 timezone을 안 붙여 돌려주므로 비교 전에 UTC로 맞춘다.

    이걸 안 하면 로컬 테스트에서만 "can't compare offset-naive and
    offset-aware datetimes"로 터진다.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def stale_source_keys(db: AsyncSession) -> list[str]:
    """지금 갱신이 필요한 소스 키 목록. 읽기 경로가 이걸 보고 백그라운드
    갱신을 예약할지 정한다(응답은 언제나 캐시에서 즉시 나간다)."""
    keys = [k for source in configured_sources() for k in source_keys_for(source)]
    states = await _load_states(db, keys)
    stale_before, now = _stale_before(), _now()
    return [k for k in keys if _is_stale(states.get(k), stale_before, now)]


async def feed_is_empty(db: AsyncSession) -> bool:
    return (await db.scalar(select(FeedItem.id).limit(1))) is None


async def last_refreshed_at(db: AsyncSession) -> datetime | None:
    return await db.scalar(select(FeedRefreshState.last_succeeded_at).order_by(FeedRefreshState.last_succeeded_at.desc()).limit(1))


async def _claim(db: AsyncSession, source_key: str) -> bool:
    """동시 갱신 방지용 compare-and-swap.

    캐시가 비어 있을 때 메인 화면 동시 접속 10건이 들어오면, 락이 없으면
    백그라운드 갱신이 10개 떠서 심사받아 얻은 API 쿼터를 10배로 태운다.
    조건부 UPDATE 한 방으로 처리하고 rowcount로 승패를 가른다.
    """
    now = _now()
    state = (
        await db.execute(select(FeedRefreshState).where(FeedRefreshState.source_key == source_key))
    ).scalar_one_or_none()
    if state is None:
        db.add(FeedRefreshState(source_key=source_key, last_started_at=now))
        await db.commit()
        return True

    result = await db.execute(
        update(FeedRefreshState)
        .where(
            FeedRefreshState.source_key == source_key,
            (FeedRefreshState.last_started_at.is_(None)) | (FeedRefreshState.last_started_at < now - FEED_REFRESH_LOCK),
        )
        .values(last_started_at=now)
        # synchronize_session=False: 끄지 않으면 ORM이 WHERE 절을 파이썬에서
        # 다시 평가해 세션에 올라온 객체와 맞춰보려 하는데, SQLite가 돌려준
        # naive datetime과 여기 aware 값을 비교하다 TypeError로 터진다. CAS는
        # DB에서만 판정되면 되고 결과는 rowcount로 읽으므로 동기화가 필요 없다.
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if result.rowcount:
        return True
    # 락은 못 잡았지만, 아직 한 번도 성공한 적이 없고 락이 방금 걸린 게
    # 아니라면(=이전 시도가 실패로 끝났다면) 재시도할 가치가 있다.
    return False


async def _upsert(db: AsyncSession, source_key: str, items: list[FeedItemData]) -> int:
    """수집 결과를 반영한다. 이미 있는 항목은 last_seen_at만 올리고, 없는
    항목만 새로 넣는다.

    postgresql의 ON CONFLICT를 **일부러 안 쓴다** — 그러면 이 워커를 SQLite로
    테스트할 수 없다. 카테고리당 수십 건 규모라 왕복 비용은 의미가 없고,
    UNIQUE 제약이 최후의 방어로 남아 있다.
    """
    if not items:
        return 0

    source, category = source_key.split(":", 1)
    keyed: dict[str, FeedItemData] = {}
    for item in items:
        keyed[compute_dedup_key(item.source_key, item.title, item.subtitle, item.meta_lines)] = item

    existing = {
        row.dedup_key: row
        for row in (
            await db.execute(
                select(FeedItem).where(
                    FeedItem.source == source,
                    FeedItem.category == category,
                    FeedItem.dedup_key.in_(list(keyed)),
                )
            )
        ).scalars().all()
    }

    now = _now()
    for dedup_key, item in keyed.items():
        embed_text = build_embed_text(item.title, item.subtitle, item.meta_lines)
        row = existing.get(dedup_key)
        if row is not None:
            row.last_seen_at = now
            row.is_active = True
            row.embed_text = embed_text
            row.detail_url = item.detail_url
            row.source_published_at = item.source_published_at
            continue
        db.add(
            FeedItem(
                source=source,
                category=category,
                feed_kind=item.feed_kind,
                dedup_key=dedup_key,
                title=item.title,
                subtitle=item.subtitle,
                meta_lines=list(item.meta_lines),
                detail_url=item.detail_url,
                source_published_at=item.source_published_at,
                embed_text=embed_text,
                first_seen_at=now,
                last_seen_at=now,
            )
        )

    # 이번에 못 본 항목은 비활성으로. 삭제가 아닌 이유는 models/feed_item.py 참고.
    await db.flush()
    stale_rows = (
        await db.execute(
            select(FeedItem).where(
                FeedItem.source == source,
                FeedItem.category == category,
                FeedItem.is_active.is_(True),
                FeedItem.dedup_key.not_in(list(keyed)),
            )
        )
    ).scalars().all()
    for row in stale_rows:
        row.is_active = False

    await db.commit()
    return len(keyed)


async def _embed_pending(db: AsyncSession) -> None:
    """아직 벡터가 없거나 본문이 바뀐 항목을 임베딩한다.

    **fetch 성공 여부와 무관하게 항상 실행되고, 실패해도 갱신을 실패로 만들지
    않는다.** Gemini를 제거한 뒤 임베딩 경로는 로컬 Ollama bge-m3 하나뿐이라
    터널이 끊기면 100% 실패하는데, 항목 행은 이미 커밋됐으므로 피드는 최신순
    으로 멀쩡히 돌아간다. 그리고 이 루프 자체가 다음 갱신 때 비어 있는 벡터를
    메우는 backfill 경로다 — 별도 재시도 장치가 필요 없다.
    """
    try:
        rows = (
            await db.execute(
                select(FeedItem, FeedItemEmbedding)
                .outerjoin(FeedItemEmbedding, FeedItemEmbedding.feed_item_id == FeedItem.id)
                .where(FeedItem.is_active.is_(True))
            )
        ).all()
    except Exception:
        # feed_item_embeddings가 없는 환경(pgvector 없는 SQLite 테스트,
        # 마이그레이션 이전)에서는 임베딩 단계를 통째로 건너뛴다. 항목은 이미
        # 커밋됐고 피드는 최신순으로 정상 동작한다.
        await db.rollback()
        logger.info("feed: embedding table unavailable, skipping the embedding stage")
        return
    pending = [(item, emb) for item, emb in rows if emb is None or emb.embedding is None]
    if not pending:
        return

    provider = LocalOllamaEmbedding()
    for start in range(0, len(pending), EMBED_BATCH):
        batch = pending[start : start + EMBED_BATCH]
        try:
            vectors = await provider.embed([item.embed_text or item.title for item, _ in batch])
        except Exception:
            logger.warning(
                "feed: embedding unavailable, leaving %d item(s) unvectorised (they still show, recency-ordered)",
                len(pending) - start,
                exc_info=True,
            )
            await db.rollback()
            return
        for (item, emb), vector in zip(batch, vectors):
            if emb is None:
                db.add(
                    FeedItemEmbedding(
                        feed_item_id=item.id, embedding=vector, embedding_model=provider.model_name
                    )
                )
            else:
                emb.embedding = vector
                emb.embedding_model = provider.model_name
        await db.commit()


async def _prune(db: AsyncSession) -> None:
    cutoff = _now() - PRUNE_AFTER
    rows = (
        await db.execute(
            select(FeedItem).where(FeedItem.is_active.is_(False), FeedItem.last_seen_at < cutoff)
        )
    ).scalars().all()
    for row in rows:
        await db.delete(row)
    if rows:
        await db.commit()


async def refresh_feed(sources: list[FeedSource] | None = None, source_keys: list[str] | None = None) -> None:
    """백그라운드 수집 워커. 절대 호출자에게 예외를 던지지 않는다.

    요청의 get_db가 아니라 자기 세션을 연다 — record_pipeline/pipeline.py와
    같은 규칙이다(BackgroundTasks는 응답을 보낸 뒤에 돌기 때문에 요청 세션은
    이미 닫혀 있다).

    소스는 인자로 받는다. FastAPI 의존성이 아니라 워커라서, 테스트는 가짜
    소스를 그냥 넘겨주면 된다 — 쓰지도 않을 get_feed_sources() 훅을 만드는
    것보다 정직하다.
    """
    active = sources if sources is not None else configured_sources()
    async with AsyncSessionLocal() as db:
        for source in active:
            for key in source_keys_for(source):
                if source_keys is not None and key not in source_keys:
                    continue
                await _refresh_one(db, source, key)
        # 각 단계는 독립적으로 실패할 수 있어야 한다 — 임베딩이 안 됐다고
        # 오래된 항목 정리까지 건너뛸 이유는 없다.
        for stage in (_embed_pending, _prune):
            try:
                await stage(db)
            except Exception:
                await db.rollback()
                logger.warning("feed: %s failed", stage.__name__, exc_info=True)


async def _refresh_one(db: AsyncSession, source: FeedSource, source_key: str) -> None:
    if not await _claim(db, source_key):
        return

    category = source_key.split(":", 1)[1]
    state = (
        await db.execute(select(FeedRefreshState).where(FeedRefreshState.source_key == source_key))
    ).scalar_one_or_none()
    try:
        items = await source.fetch(category)
    except Exception as exc:
        # 한 카테고리의 실패가 나머지를 막지 않는다 — api/job_search.py가
        # 카테고리별로 격리하는 것과 같은 원리.
        logger.warning("feed: source %s failed: %s", source_key, exc)
        if state is not None:
            state.last_failed_at = _now()
            state.last_error = str(exc)[:500]
            await db.commit()
        return

    count = await _upsert(db, source_key, items)
    if state is not None:
        state.last_succeeded_at = _now()
        state.last_failed_at = None
        state.last_error = None
        state.item_count = count
        await db.commit()


async def refresh_feed_if_stale() -> None:
    async with AsyncSessionLocal() as db:
        keys = await stale_source_keys(db)
    if keys:
        await refresh_feed(source_keys=keys)


def get_feed_refresher():
    """FastAPI DI 훅. refresh_feed는 자기 세션을 열기 때문에 get_db를
    오버라이드하는 것만으로는 테스트에서 못 바꾼다 — get_chunk_search가
    같은 이유로 존재한다.
    """
    return refresh_feed_if_stale


__all__ = [
    "EMBED_BATCH",
    "FEED_FAILED_RETRY",
    "FEED_REFRESH_LOCK",
    "PRUNE_AFTER",
    "feed_is_empty",
    "get_feed_refresher",
    "last_refreshed_at",
    "refresh_feed",
    "refresh_feed_if_stale",
    "stale_source_keys",
]
