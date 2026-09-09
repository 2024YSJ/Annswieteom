from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.core.config import settings
from app.models.feed_refresh_state import FeedRefreshState


def _register_and_login(client, email="ops@example.com"):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123", "nickname": "Ops"})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_state(client, **kwargs):
    async def _run():
        async with client.session_local() as db:
            db.add(FeedRefreshState(**kwargs))
            await db.commit()

    asyncio.run(_run())


def test_requires_authentication(feed_client):
    """외부 API 설정 상태를 익명에 노출하지 않는다."""
    assert feed_client.get("/api/v1/feed/sources").status_code == 401


def test_lists_every_source_category(feed_client):
    headers = _register_and_login(feed_client)

    rows = feed_client.get("/api/v1/feed/sources", headers=headers).json()

    keys = {r["source_key"] for r in rows}
    # 워크넷 6개 + 온통청년 1개. 설정 여부와 무관하게 전부 보여야 한다.
    assert "worknet:job_fair" in keys
    assert "worknet:training_course" in keys
    assert "youthcenter:youth_policy" in keys
    assert len(rows) == 7
    assert {r["category_label"] for r in rows} >= {"채용행사", "청년정책"}


def test_unconfigured_source_stays_in_the_list(feed_client, monkeypatch):
    """이 엔드포인트의 존재 이유다.

    키가 없는 소스는 수집에서 조용히 빠지는데(의도), 진단 목록에서까지 사라지면
    "설정 안 됨"과 "그런 소스가 없음"이 구분되지 않는다. 2026-09-09에 실제로
    이 구분이 안 돼서 프로덕션 API를 손으로 쳐야 했다.
    """
    monkeypatch.setattr(settings, "youthcenter_api_key", "")
    headers = _register_and_login(feed_client)

    rows = feed_client.get("/api/v1/feed/sources", headers=headers).json()
    youth = next(r for r in rows if r["source_key"] == "youthcenter:youth_policy")

    assert youth["configured"] is False
    assert youth["last_succeeded_at"] is None


def test_reports_last_error_and_counts(feed_client):
    """"키가 없다"와 "호출이 실패한다"를 구분할 수 있어야 한다."""
    now = datetime.now(timezone.utc)
    _seed_state(
        feed_client,
        source_key="worknet:job_fair",
        last_started_at=now,
        last_failed_at=now,
        last_error="인증키 미승인",
        item_count=0,
    )
    headers = _register_and_login(feed_client)

    rows = feed_client.get("/api/v1/feed/sources", headers=headers).json()
    job_fair = next(r for r in rows if r["source_key"] == "worknet:job_fair")

    assert job_fair["last_error"] == "인증키 미승인"
    assert job_fair["last_failed_at"] is not None
    assert job_fair["last_succeeded_at"] is None
    # 실패했으니 살아있는 항목도 없다.
    assert job_fair["active_item_count"] == 0


def test_counts_only_active_items(feed_client):
    from tests.api.test_feed import _item, _seed

    live = _item("살아있는 공고", category="job_fair")
    dead = _item("사라진 공고", category="job_fair")
    dead.is_active = False
    _seed(feed_client, [live, dead])
    headers = _register_and_login(feed_client)

    rows = feed_client.get("/api/v1/feed/sources", headers=headers).json()
    job_fair = next(r for r in rows if r["source_key"] == "worknet:job_fair")

    assert job_fair["active_item_count"] == 1
