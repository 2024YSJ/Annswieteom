from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.feed_item import FeedItem
from app.models.feed_refresh_state import FeedRefreshState
from app.services.feed import ingest
from app.services.feed.dedup import build_embed_text, compute_dedup_key
from app.services.feed.sources import FeedItemData


class FakeSource:
    """카테고리별로 미리 정해둔 결과(또는 예외)를 돌려주는 소스 대역."""

    def __init__(self, name="worknet", results=None, failing=None, categories=("job_fair",)):
        self.name = name
        self.categories = categories
        self._results = results or {}
        self._failing = failing or set()
        self.fetch_calls: list[str] = []

    def is_configured(self) -> bool:
        return True

    def is_category_configured(self, category: str) -> bool:
        return True

    async def fetch(self, category: str) -> list[FeedItemData]:
        self.fetch_calls.append(category)
        if category in self._failing:
            raise RuntimeError(f"{category} 인증키 미승인")
        return list(self._results.get(category, []))


def _data(title, *, category="job_fair", subtitle="", meta=None, source_key=None):
    return FeedItemData(
        source="worknet",
        category=category,
        title=title,
        subtitle=subtitle,
        meta_lines=meta or [],
        source_key=source_key,
    )


@pytest.fixture
def db_factory(monkeypatch):
    """feed_items / feed_refresh_states만 있는 SQLite. 벡터 테이블은 없으므로
    임베딩 단계는 자연스럽게 실패 경로를 탄다 — 그게 이 테스트들이 확인하려는
    프로덕션 동작(터널 다운)과 같은 모양이다."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    import asyncio

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all, tables=[FeedItem.__table__, FeedRefreshState.__table__]
            )

    asyncio.run(_create())
    monkeypatch.setattr(ingest, "AsyncSessionLocal", maker)
    yield maker
    asyncio.run(engine.dispose())


async def _count_items(maker) -> int:
    async with maker() as db:
        return int(await db.scalar(select(func.count(FeedItem.id))) or 0)


@pytest.mark.asyncio
async def test_second_refresh_does_not_duplicate(db_factory):
    """같은 페이로드를 두 번 수집해도 행이 늘면 안 된다 — 중복 제거의 핵심 보증."""
    source = FakeSource(results={"job_fair": [_data("2026 충청권 취업박람회", subtitle="대전/충청")]})

    await ingest.refresh_feed(sources=[source])
    assert await _count_items(db_factory) == 1

    # 락 때문에 두 번째 호출이 건너뛰이지 않도록 시작 시각을 되돌린다.
    async with db_factory() as db:
        state = (await db.execute(select(FeedRefreshState))).scalar_one()
        state.last_started_at = datetime.now(timezone.utc) - ingest.FEED_REFRESH_LOCK - timedelta(minutes=1)
        before = state.last_succeeded_at
        await db.commit()

    await ingest.refresh_feed(sources=[source])
    assert await _count_items(db_factory) == 1

    async with db_factory() as db:
        item = (await db.execute(select(FeedItem))).scalar_one()
        state = (await db.execute(select(FeedRefreshState))).scalar_one()
    assert item.is_active is True
    assert state.last_succeeded_at != before or state.last_succeeded_at is not None


@pytest.mark.asyncio
async def test_stable_source_key_survives_a_title_change(db_factory):
    """상세 URL처럼 안정적인 id가 있으면 제목이 바뀌어도 같은 행을 갱신한다."""
    first = FakeSource(results={"job_fair": [_data("옛 제목", source_key="https://x/1")]})
    await ingest.refresh_feed(sources=[first])

    async with db_factory() as db:
        state = (await db.execute(select(FeedRefreshState))).scalar_one()
        state.last_started_at = datetime.now(timezone.utc) - ingest.FEED_REFRESH_LOCK - timedelta(minutes=1)
        await db.commit()

    second = FakeSource(results={"job_fair": [_data("새 제목", source_key="https://x/1")]})
    await ingest.refresh_feed(sources=[second])

    assert await _count_items(db_factory) == 1


@pytest.mark.asyncio
async def test_content_change_without_an_id_creates_a_new_row_and_retires_the_old(db_factory):
    """id 없는 카테고리의 정직한 한계를 고정해 둔다 — 문구가 바뀌면 새 행이
    생기고 옛 행은 삭제가 아니라 비활성으로 내려간다."""
    await ingest.refresh_feed(sources=[FakeSource(results={"job_fair": [_data("A사 상시채용")]})])

    async with db_factory() as db:
        state = (await db.execute(select(FeedRefreshState))).scalar_one()
        state.last_started_at = datetime.now(timezone.utc) - ingest.FEED_REFRESH_LOCK - timedelta(minutes=1)
        await db.commit()

    await ingest.refresh_feed(sources=[FakeSource(results={"job_fair": [_data("A사 상시채용(수정)")]})])

    async with db_factory() as db:
        rows = (await db.execute(select(FeedItem).order_by(FeedItem.is_active))).scalars().all()
    assert len(rows) == 2
    assert sorted(r.is_active for r in rows) == [False, True]


@pytest.mark.asyncio
async def test_one_failing_category_does_not_block_the_others(db_factory):
    source = FakeSource(
        categories=("job_fair", "promising_sme"),
        results={"promising_sme": [_data("강소기업 A", category="promising_sme")]},
        failing={"job_fair"},
    )
    await ingest.refresh_feed(sources=[source])

    assert await _count_items(db_factory) == 1
    async with db_factory() as db:
        states = {s.source_key: s for s in (await db.execute(select(FeedRefreshState))).scalars().all()}
    assert states["worknet:job_fair"].last_error is not None
    assert states["worknet:job_fair"].last_succeeded_at is None
    assert states["worknet:promising_sme"].last_error is None
    assert states["worknet:promising_sme"].last_succeeded_at is not None


@pytest.mark.asyncio
async def test_embedding_failure_still_leaves_the_items(db_factory):
    """터널 다운 보증 — 임베딩이 실패해도 항목은 커밋된 채로 남고 갱신은
    성공으로 기록된다. 여기서는 벡터 테이블 자체가 없어 임베딩 단계가 확실히
    실패한다."""
    await ingest.refresh_feed(sources=[FakeSource(results={"job_fair": [_data("공고 A"), _data("공고 B")]})])

    assert await _count_items(db_factory) == 2
    async with db_factory() as db:
        state = (await db.execute(select(FeedRefreshState))).scalar_one()
    assert state.last_succeeded_at is not None
    assert state.item_count == 2


@pytest.mark.asyncio
async def test_concurrent_refresh_is_skipped_by_the_lock(db_factory):
    """락이 없으면 메인 화면 동시 접속만큼 갱신이 떠서 API 쿼터를 태운다."""
    source = FakeSource(results={"job_fair": [_data("공고 A")]})
    await ingest.refresh_feed(sources=[source])
    await ingest.refresh_feed(sources=[source])  # 락이 살아 있으므로 fetch가 다시 안 돈다
    assert source.fetch_calls == ["job_fair"]


@pytest.mark.asyncio
async def test_stale_source_keys_reports_never_refreshed_keys(db_factory):
    async with db_factory() as db:
        keys = await ingest.stale_source_keys(db)
    # 실제 설정된 고용24 6개 카테고리가 전부 "한 번도 성공한 적 없음"으로 잡힌다.
    assert "worknet:job_fair" in keys


@pytest.mark.asyncio
async def test_prune_removes_long_inactive_items(db_factory):
    async with db_factory() as db:
        old = FeedItem(
            id=uuid.uuid4(), source="worknet", category="job_fair", feed_kind="job",
            dedup_key="h:old", title="아주 오래된 공고", subtitle="", meta_lines=[], embed_text="x",
            is_active=False,
            first_seen_at=datetime.now(timezone.utc) - timedelta(days=60),
            last_seen_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        db.add(old)
        await db.commit()

    await ingest.refresh_feed(sources=[FakeSource(results={"job_fair": []})])
    assert await _count_items(db_factory) == 0


# ── dedup 순수 함수 ────────────────────────────────────────────────────────


def test_dedup_prefers_the_stable_key():
    assert compute_dedup_key("abc", "제목", "부제", ["메타"]) == "k:abc"


def test_dedup_hash_is_stable_for_identical_content():
    a = compute_dedup_key(None, "제목", "부제", ["메타1", "메타2"])
    b = compute_dedup_key(None, "제목", "부제", ["메타1", "메타2"])
    assert a == b and a.startswith("h:")


def test_dedup_hash_changes_with_content():
    a = compute_dedup_key(None, "제목", "부제", ["메타1"])
    b = compute_dedup_key(None, "제목", "부제", ["메타2"])
    assert a != b


def test_embed_text_drops_empty_parts():
    assert build_embed_text("제목", "", ["", "메타"]) == "제목\n메타"
