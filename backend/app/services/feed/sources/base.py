from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

from app.models.feed_item import FEED_KIND_BY_CATEGORY
from app.services.job_pipeline.job_info_client import CATEGORY_LABELS as WORKNET_CATEGORY_LABELS

#: 카테고리 → 화면 라벨. 고용24 6개는 job_info_client에서 그대로 가져온다
#: (한국어를 두 군데 적어두면 반드시 갈라진다).
FEED_CATEGORY_LABELS = {**WORKNET_CATEGORY_LABELS, "youth_policy": "청년정책"}

FEED_SOURCE_LABELS = {"worknet": "고용24", "youthcenter": "온통청년"}


@dataclass
class FeedItemData:
    """모든 소스가 공유하는 정규화 모양.

    고용24 6종이 이미 쓰는 `JobInfoResult`를 그대로 재사용하지 않고 한 겹 더
    두는 이유는, 피드가 저장할 때 필요한 네 가지(source/category/feed_kind/
    source_key)가 대화형 검색 응답에는 전혀 필요 없기 때문이다. 그걸
    `JobInfoResult`에 밀어 넣으면 `schemas/job_search.py`의 응답 모양까지
    오염된다.
    """

    source: str
    category: str
    title: str
    subtitle: str = ""
    meta_lines: list[str] = field(default_factory=list)
    detail_url: str | None = None
    #: 소스가 주는 안정적인 항목 id. 없으면 None이고 내용 해시로 대체된다.
    source_key: str | None = None
    #: 소스가 등록일/게시일을 주는 경우에만. 대부분의 고용24 카테고리는 안 준다.
    source_published_at: date | None = None
    #: 구조화된 자격조건. 지금은 온통청년만 준다(youthcenter_source._parse_eligibility).
    eligibility: dict | None = None

    @property
    def feed_kind(self) -> str:
        return FEED_KIND_BY_CATEGORY[self.category]


@runtime_checkable
class FeedSource(Protocol):
    name: str
    categories: tuple[str, ...]

    def is_configured(self) -> bool: ...
    def is_category_configured(self, category: str) -> bool: ...
    async def fetch(self, category: str) -> list[FeedItemData]: ...
