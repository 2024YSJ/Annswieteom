from __future__ import annotations

import logging

from app.services.feed.sources.base import (
    FEED_CATEGORY_LABELS,
    FEED_SOURCE_LABELS,
    FeedItemData,
    FeedSource,
)
from app.services.feed.sources.worknet_source import WorknetFeedSource
from app.services.feed.sources.youthcenter_source import YouthCenterFeedSource

logger = logging.getLogger(__name__)


def all_sources() -> list[FeedSource]:
    return [WorknetFeedSource(), YouthCenterFeedSource()]


def configured_sources() -> list[FeedSource]:
    """인증키가 설정된 소스만 돌려준다.

    **키가 없는 소스는 조용히 빠진다 — 예외도 아니고 실패 기록도 아니다.**
    고용24 키가 카테고리마다 사람 심사를 거쳐 따로 발급된 전례가 있고(devlog
    15/16) 온통청년도 같은 게이트라, "아직 승인 안 남"은 정상적인 설정 상태지
    오류가 아니다. 오류로 취급하면 승인될 때까지 메인 화면에 빨간 배너가 계속
    뜬다. 대신 INFO 로그를 한 줄 남겨 왜 항목이 없는지는 추적 가능하게 한다.
    """
    available: list[FeedSource] = []
    skipped: list[FeedSource] = []
    for source in all_sources():
        (available if source.is_configured() else skipped).append(source)
    if skipped:
        logger.info("feed: skipping unconfigured sources: %s", [s.name for s in skipped])
    return available


def source_keys_for(source: FeedSource) -> list[str]:
    """수집/락 단위 키. "worknet:job_fair" 형태.

    소스가 아니라 카테고리 단위인 이유는 고용24 인증키가 카테고리마다 따로
    발급되기 때문이다 — 하나가 미승인이어도 나머지는 살아 있어야 하고, 어느
    키가 죽었는지도 구분돼야 한다.
    """
    return [f"{source.name}:{c}" for c in source.categories if source.is_category_configured(c)]


def configured_source_keys() -> list[str]:
    return [key for source in configured_sources() for key in source_keys_for(source)]


__all__ = [
    "FEED_CATEGORY_LABELS",
    "FEED_SOURCE_LABELS",
    "FeedItemData",
    "FeedSource",
    "WorknetFeedSource",
    "YouthCenterFeedSource",
    "all_sources",
    "configured_source_keys",
    "configured_sources",
    "source_keys_for",
]
