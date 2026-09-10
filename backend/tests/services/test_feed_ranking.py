from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.feed_item import FeedItem
from app.services.feed.ranking import rank_feed_items


@pytest.fixture
def db_factory():
    """feed_items만 있는 SQLite.

    `feed_item_embeddings`는 **일부러 만들지 않는다** — pgvector의 Vector는
    SQLite 컴파일러가 없다(tests/api/conftest.py의 feed_client와 같은 이유).
    덕분에 코사인 질의가 실제로 터지는 경로를 그대로 태울 수 있다.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[FeedItem.__table__])

    asyncio.run(_create())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _seed(db, count: int) -> None:
    base = datetime.now(timezone.utc)
    for n in range(count):
        db.add(
            FeedItem(
                id=uuid.uuid4(),
                source="worknet",
                category="job_fair",
                feed_kind="job",
                dedup_key=f"k:{n}",
                title=f"공고 {n}",
                subtitle="",
                meta_lines=[],
                embed_text=f"공고 {n}",
                # 최신순이 결정적이도록 1분씩 벌려둔다.
                first_seen_at=base - timedelta(minutes=n),
                last_seen_at=base,
                is_active=True,
            )
        )
    await db.commit()


@pytest.mark.asyncio
async def test_plain_recency_is_not_reported_as_a_vector_failure(db_factory):
    """프로필 벡터가 없는 평범한 최신순 조회.

    여기에 실패 플래그가 서면 라우터가 멀쩡한 피드에 "AI 서버가 수리 중이예요."를
    띄운다.
    """
    async with db_factory() as db:
        await _seed(db, 5)
        ranked = await rank_feed_items(db, feed_kind="job", limit=10, offset=0)

    assert len(ranked.items) == 5
    assert ranked.personalized is False
    assert ranked.vector_ranking_failed is False


@pytest.mark.asyncio
async def test_vector_query_failure_falls_back_to_recency_and_says_so(db_factory):
    """임베딩 테이블이 없어 코사인 질의가 터지는 경우.

    피드 자체는 최신순으로 살아 있어야 하고(사용자가 잃는 건 정렬 품질이지
    피드가 아니다), 동시에 그게 **진짜 고장**이라는 사실이 위로 올라가야 한다.
    """
    async with db_factory() as db:
        await _seed(db, 3)
        ranked = await rank_feed_items(db, feed_kind="job", profile_vector=[0.1] * 1024, limit=10, offset=0)

    assert [i.title for i in ranked.items] == ["공고 0", "공고 1", "공고 2"]
    assert ranked.personalized is False
    assert ranked.vector_ranking_failed is True


@pytest.mark.asyncio
async def test_offset_past_the_end_returns_an_empty_page_not_a_repeat(db_factory):
    """"더보기"의 마지막 클릭이 밟는 지점.

    여기서 뭔가가 돌아오면 이미 본 카드가 다시 보인다는 뜻이다.
    """
    async with db_factory() as db:
        await _seed(db, 4)
        ranked = await rank_feed_items(db, feed_kind="job", limit=10, offset=4)

    assert ranked.items == []
    assert ranked.total == 4


async def _seed_blocks(db, blocks: list[tuple[str, int]]) -> None:
    """카테고리를 덩어리로 넣는다 — 실제 수집이 만드는 모양 그대로.

    한 번의 갱신이 카테고리를 차례로 넣으므로 나중에 들어간 카테고리일수록
    first_seen_at이 최신이다.
    """
    base = datetime.now(timezone.utc) - timedelta(days=1)
    tick = 0
    for category, count in blocks:
        for n in range(count):
            db.add(
                FeedItem(
                    id=uuid.uuid4(),
                    source="worknet",
                    category=category,
                    feed_kind="job",
                    dedup_key=f"k:{category}:{n}",
                    title=f"{category} {n}",
                    subtitle="",
                    meta_lines=[],
                    embed_text=category,
                    first_seen_at=base + timedelta(seconds=tick),
                    last_seen_at=base,
                    is_active=True,
                )
            )
            tick += 1
    await db.commit()


@pytest.mark.asyncio
async def test_recency_alone_lets_one_category_bury_the_others(db_factory):
    """섞지 않으면 무슨 일이 벌어지는지 고정해둔다.

    마지막에 수집된 카테고리가 통째로 앞을 차지한다. 실제로 강소기업 50건이
    앞을 다 막았고, 하필 그 카테고리만 상세 링크를 못 단다.
    """
    async with db_factory() as db:
        await _seed_blocks(db, [("job_fair", 5), ("promising_sme", 5)])
        ranked = await rank_feed_items(db, feed_kind="job", limit=5, offset=0)

    assert {i.category for i in ranked.items} == {"promising_sme"}


@pytest.mark.asyncio
async def test_interleaving_puts_every_category_on_the_first_page(db_factory):
    """첫 화면 6장 안에 네 카테고리가 다 들어와야 한다."""
    async with db_factory() as db:
        await _seed_blocks(
            db,
            [("job_fair", 5), ("public_recruitment", 5), ("public_recruitment_company", 5), ("promising_sme", 5)],
        )
        ranked = await rank_feed_items(db, feed_kind="job", interleave_categories=True, limit=6, offset=0)

    assert len({i.category for i in ranked.items[:4]}) == 4


@pytest.mark.asyncio
async def test_interleaved_pagination_never_repeats_or_skips(db_factory):
    """"더보기"를 끝까지 눌러도 카드가 겹치거나 새지 않아야 한다.

    창 함수 정렬은 결정적 2차 키가 없으면 페이지 경계에서 조용히 어긋난다.
    """
    async with db_factory() as db:
        await _seed_blocks(db, [("job_fair", 7), ("public_recruitment", 4), ("promising_sme", 9)])

        seen = []
        for offset in range(0, 20, 3):
            page = await rank_feed_items(
                db, feed_kind="job", interleave_categories=True, limit=3, offset=offset
            )
            seen += [i.id for i in page.items]

    assert len(seen) == 20
    assert len(set(seen)) == 20


@pytest.mark.asyncio
async def test_interleaving_is_skipped_when_one_category_is_requested(db_factory):
    """카테고리를 하나만 고르면 섞을 게 없다 — 그 안에서는 최신순 그대로."""
    async with db_factory() as db:
        await _seed_blocks(db, [("job_fair", 3), ("promising_sme", 3)])
        ranked = await rank_feed_items(
            db, feed_kind="job", category="job_fair", interleave_categories=True, limit=10, offset=0
        )

    assert [i.title for i in ranked.items] == ["job_fair 2", "job_fair 1", "job_fair 0"]
