from __future__ import annotations

import pytest

from app.services.job_pipeline import job_info_client as jic
from app.services.job_pipeline.job_info_client import JobInfoResult
from app.services.feed.sources.worknet_source import FEED_FETCH_LIMIT, WorknetFeedSource


@pytest.mark.asyncio
async def test_fetch_prefers_the_source_id_over_the_detail_url(monkeypatch):
    """중복 제거 키는 소스가 준 항목 id를 먼저 쓴다.

    상세 URL로 대신하면 소스가 링크만 바꿔도 새 항목으로 들어오고, 링크가
    없는 카테고리는 내용 해시로 떨어져 문구 한 줄 수정에도 카드가 복제된다.
    """
    async def fake_search(limit=None):
        return [
            JobInfoResult(title="채용행사", subtitle="서울", meta_lines=[], detail_url="https://x/1", source_key="49160"),
            JobInfoResult(title="링크만 있는 항목", subtitle="", meta_lines=[], detail_url="https://x/2"),
            JobInfoResult(title="둘 다 없는 항목", subtitle="", meta_lines=[]),
        ]

    monkeypatch.setitem(jic.CATEGORY_SEARCH_FUNCTIONS, "job_fair", fake_search)

    items = await WorknetFeedSource().fetch("job_fair")

    assert [i.source_key for i in items] == ["49160", "https://x/2", None]


@pytest.mark.asyncio
async def test_fetch_asks_for_more_than_the_llm_path_does(monkeypatch):
    """피드는 목록을 LLM 프롬프트에 넣지 않으므로 더 많이 받아도 된다.

    대화형 검색이 쓰는 `job_info_client._FETCH_LIMIT`을 그대로 따르면 메인
    화면의 "더보기"가 몇 번 만에 바닥난다.
    """
    seen = {}

    async def fake_search(limit=None):
        seen["limit"] = limit
        return []

    monkeypatch.setitem(jic.CATEGORY_SEARCH_FUNCTIONS, "promising_sme", fake_search)

    await WorknetFeedSource().fetch("promising_sme")

    assert seen["limit"] == FEED_FETCH_LIMIT
    assert FEED_FETCH_LIMIT > jic._FETCH_LIMIT


@pytest.mark.asyncio
async def test_training_course_is_called_without_a_limit(monkeypatch):
    """훈련과정만 시그니처가 다르다 — limit이 아니라 조회 조건을 받는다.

    구분 없이 limit을 넘기면 TypeError로 이 카테고리만 통째로 사라진다.
    """
    called = {}

    async def fake_training(params=None):
        called["params"] = params
        return []

    monkeypatch.setitem(jic.CATEGORY_SEARCH_FUNCTIONS, "training_course", fake_training)

    await WorknetFeedSource().fetch("training_course")

    assert called == {"params": None}
