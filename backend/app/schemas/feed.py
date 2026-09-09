from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class FeedItemRead(BaseModel):
    """피드 카드 한 장. `source_label`/`category_label`은 라우터가 라벨
    딕셔너리에서 채워 넣는다 — 프론트가 한국어를 하드코딩하지 않게."""

    id: uuid.UUID
    source: str
    source_label: str
    category: str
    category_label: str
    feed_kind: str
    title: str
    subtitle: str
    meta_lines: list[str]
    detail_url: str | None
    source_published_at: date | None
    first_seen_at: datetime


class FeedRead(BaseModel):
    """`GET /feed/*` 공통 응답.

    `personalized`가 False라고 오류가 아니다 — 최신순은 정상 경로이고,
    로그아웃 방문자와 문답 기록이 없는 신규 사용자에게는 오히려 기본값이다.
    왜 개인화가 아닌지는 `fallback_reason`이 구분해준다.

    - `None`: 개인화가 적용됐거나(personalized=True), 애초에 개인화를 시도하지
      않는 엔드포인트(정책/일반 공고 피드).
    - `"no_profile"`: 문답 기록이 아직 없다. 프론트는 "공백기 정리를 해보시면
      맞춤 공고를 찾아드려요" 쪽으로 유도한다.
    - `"preparing"`: 기록은 있는데 아직 벡터가 없다. 방금 백그라운드 계산을
      예약했으므로 다음 방문이면 개인화된다. **문답을 처음 남긴 사용자는
      반드시 한 번 이 상태를 지나간다** — 여기에 고장 안내를 띄우면 정상
      동작에 오경보를 내는 셈이라 따로 나눴다.
    - `"ai_unavailable"`: 벡터는 있는데 정렬 질의가 실패했다(pgvector 없음,
      차원 불일치 등). 진짜 고장이므로 "AI 서버가 수리 중이예요."를 보여준다.

    셋으로 나눈 이유는, 신규 사용자에게 고장 안내를 띄우면 안 되고 실제 고장을
    "정보 부족"으로 숨겨도 안 되기 때문이다. 어느 쪽이든 items는 최신순으로
    채워지므로 화면이 비지는 않는다.
    """

    items: list[FeedItemRead]
    total: int
    limit: int
    offset: int
    personalized: bool
    fallback_reason: Literal["no_profile", "preparing", "ai_unavailable"] | None = None
    #: 캐시가 비어 있어 방금 수집을 예약한 상태. BackgroundTasks가 응답 이후에
    #: 돌기 때문에 최초 1회는 구조적으로 items가 빈 채로 나간다.
    is_warming: bool
    refreshed_at: datetime | None
