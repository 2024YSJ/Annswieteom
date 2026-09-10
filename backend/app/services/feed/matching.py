"""교집합 → 합집합 티어 매칭.

사용자 속성(나이·거주지·학력·전공·취업상태 …)과 정책 자격조건을 필드별로
대조해 세 티어로 나눈다. 벡터 하나로 코사인 정렬만 하던 기존 방식은 "경기 남부 +
반도체 + 신입"을 평균된 한 방향으로 뭉개서 "모든 조건이 맞는 것 먼저"를 표현할 수
없었다(2026-09-11 요청).

필드마다 판정은 네 가지다.

- `match`    — 정책이 조건을 걸었고 사용자가 그 조건에 명시적으로 맞는다
- `open`     — 정책이 조건을 걸지 않았다("제한없음")
- `unknown`  — 조건은 있는데 사용자 값을 모른다(또는 경계라 판단 불가)
- `mismatch` — 조건이 있고 사용자가 맞지 않는다

`open`을 `match`와 같이 세면 조건 없는 정책이 전부 "모든 조건 일치"로 올라온다.
실측으로 학력 제한없음이 2,304/2,673건이라 교집합 칸이 그걸로 도배된다. 그래서
**티어 A(교집합)는 명시 일치가 1개 이상**이어야 한다.

티어:
- `all`  (교집합) — 불일치·미확인 없음 + 명시 일치 ≥ 1
- `some` (합집합) — 명시 일치 ≥ 1, 소프트 필드의 불일치·미확인은 허용
- `none`          — 명시 일치 0(전원 대상 정책 포함) → 의미 유사도순
- `excluded`      — 하드 필드(나이·거주지·혼인) 불일치. 신청 자격 자체가 없다

하드와 소프트를 가르는 기준: 나이·거주지는 신청하는 순간 걸러지는 자격요건이라
보여줘 봐야 헛걸음이다. 학력·전공·취업상태는 사용자가 곧 바뀌거나(졸업 예정)
정책 쪽 코드가 느슨하게 붙은 경우가 많아(샘플에서 "기타"가 흔하다) 순위만 내린다.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feed_item import FeedItem
from app.models.feed_item_embedding import FeedItemEmbedding
from app.services.feed import youthcenter_codes as yc
from app.services.feed.ranking import RankedFeed
from app.services.job_pipeline.regions import region_label_for

logger = logging.getLogger(__name__)

Verdict = Literal["match", "open", "unknown", "mismatch"]
Tier = Literal["all", "some", "none", "excluded"]

_TIER_ORDER: dict[str, int] = {"all": 0, "some": 1, "none": 2, "excluded": 3}
_HARD_FIELDS = frozenset({"age", "region", "marital"})

#: 온통청년 연령 값은 정책 원문과 한 살씩 어긋나는 경우가 있다(실측: 화순군 원문
#: "18세 이상 49세 이하"가 API에서는 17~48). 사용자 쪽도 출생연도만 알아 만 나이가
#: ±1이다. 그래서 경계 ±1년은 불일치(제외)가 아니라 미확인으로 둔다.
AGE_MARGIN = 1


@dataclass(frozen=True)
class MatchProfile:
    """매칭에 쓰는 사용자 속성. 코드는 전부 온통청년 코드 체계다.

    민감 필드(special_codes / marital_code / annual_income)는 동의가 있을 때만
    채워진다 — 채우는 쪽은 services/profile/attributes.py load_match_profile.
    """

    birth_year: int | None = None
    #: 광역 2자리("41") 또는 시·군 5자리("41110").
    residence_code: str | None = None
    education_code: str | None = None
    major_code: str | None = None
    employment_code: str | None = None
    special_codes: frozenset[str] = frozenset()
    marital_code: str | None = None
    #: 연소득(만원).
    annual_income: int | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.birth_year,
                self.residence_code,
                self.education_code,
                self.major_code,
                self.employment_code,
                self.special_codes,
                self.marital_code,
                self.annual_income is not None,
            )
        )


@dataclass(frozen=True)
class FieldResult:
    field: str
    verdict: Verdict
    label: str = ""


@dataclass
class ItemMatch:
    tier: Tier
    #: 명시 일치한 조건 — 카드에 "N개 조건 일치"와 함께 보여준다.
    matched_labels: list[str] = field(default_factory=list)
    #: 확인이 필요하거나 맞지 않는 조건.
    unmet_labels: list[str] = field(default_factory=list)
    mismatch_count: int = 0


def _age_span(lo: int | None, hi: int | None) -> str:
    if lo and hi:
        return f"만 {lo}~{hi}세"
    if lo:
        return f"만 {lo}세 이상"
    return f"만 {hi}세 이하"


def _age(eligibility: dict, profile: MatchProfile, today: date) -> FieldResult:
    age = eligibility.get("age") or {}
    raw_lo, raw_hi = age.get("min") or 0, age.get("max") or 0
    # 0과 1은 하한 없음, 0과 99 이상은 상한 없음이다(실측: "1~39", "1~99", "0~0").
    lo = raw_lo if raw_lo > 1 else None
    hi = raw_hi if 0 < raw_hi < 99 else None
    if lo is None and hi is None:
        return FieldResult("age", "open")
    span = _age_span(lo, hi)
    if profile.birth_year is None:
        return FieldResult("age", "unknown", f"나이 확인 필요({span})")

    # 생일을 모르므로 실제 만 나이는 years-1 또는 years 둘 중 하나다.
    years = today.year - profile.birth_year
    youngest, oldest = years - 1, years
    if (lo is None or youngest >= lo) and (hi is None or oldest <= hi):
        return FieldResult("age", "match", span)
    if (lo is not None and oldest < lo - AGE_MARGIN) or (hi is not None and youngest > hi + AGE_MARGIN):
        return FieldResult("age", "mismatch", f"나이 조건({span})")
    return FieldResult("age", "unknown", f"나이 확인 필요({span})")


def _region(eligibility: dict, profile: MatchProfile) -> FieldResult:
    zips = [z for z in eligibility.get("zip_codes") or [] if z]
    if eligibility.get("nationwide") or not zips:
        return FieldResult("region", "open")
    code = profile.residence_code
    if not code:
        return FieldResult("region", "unknown", "거주지 확인 필요")

    label = region_label_for(code) or code
    sido = yc.REGION_ALIASES.get(code[:2], code[:2])
    in_sido = {z for z in zips if z[:2] == sido}
    # 통합 전 코드(29/46)로 저장된 시·군은 새 코드로 옮길 표가 없다 — 광역으로만 본다.
    city_level = len(code) == 5 and code[:2] not in yc.REGION_ALIASES

    if city_level:
        # 시 코드(41110)는 끝자리가 0이고 그 아래 구 코드(41111, 41113 …)가 앞 4자리를
        # 공유한다. 온통청년은 구 단위로 나열하므로 앞 4자리로 비교해야 맞는다.
        if any(z == code or z[:4] == code[:4] for z in in_sido):
            return FieldResult("region", "match", f"{label} 거주")
        return FieldResult("region", "mismatch", "대상 지역 아님")

    full = yc.SIDO_ZIP_COUNTS.get(sido)
    if full and len(in_sido) >= full:
        return FieldResult("region", "match", f"{label} 거주")
    if in_sido:
        # 광역 일부 시·군만 대상인데 사용자의 시·군을 모른다.
        return FieldResult("region", "unknown", f"{label} 내 대상 시·군 확인 필요")
    return FieldResult("region", "mismatch", "대상 지역 아님")


def _marital(eligibility: dict, profile: MatchProfile) -> FieldResult:
    wanted = eligibility.get("marital")
    if not wanted or wanted in yc.UNRESTRICTED:
        return FieldResult("marital", "open")
    label = yc.MARITAL.get(wanted, "혼인 조건")
    if profile.marital_code is None:
        return FieldResult("marital", "unknown", f"혼인 조건 확인 필요({label})")
    if profile.marital_code == wanted:
        return FieldResult("marital", "match", label)
    return FieldResult("marital", "mismatch", f"혼인 조건({label})")


def _coded(field_name: str, codes: list[str] | None, user_code: str | None, table: dict[str, str], noun: str) -> FieldResult:
    codes = [c for c in codes or [] if c]
    if not codes or any(c in yc.UNRESTRICTED for c in codes):
        return FieldResult(field_name, "open")
    wanted = ", ".join(yc.labels(table, codes)) or "조건 있음"
    if user_code is None:
        return FieldResult(field_name, "unknown", f"{noun} 확인 필요({wanted})")
    if user_code in codes:
        return FieldResult(field_name, "match", table.get(user_code, noun))
    return FieldResult(field_name, "mismatch", f"{noun}: {wanted}")


def _special(eligibility: dict, profile: MatchProfile) -> FieldResult:
    codes = [c for c in eligibility.get("special") or [] if c]
    if not codes or any(c in yc.UNRESTRICTED for c in codes):
        return FieldResult("special", "open")
    hit = profile.special_codes & set(codes)
    if hit:
        return FieldResult("special", "match", ", ".join(yc.labels(yc.SPECIAL, sorted(hit))))
    # 사용자가 특정 대상에 해당한다고 말하지 않은 것은 해당하지 않는다는 증거가
    # 아니다 — 불일치가 아니라 미확인이다.
    return FieldResult("special", "unknown", f"대상: {', '.join(yc.labels(yc.SPECIAL, codes)) or '특정 대상'}")


def _income(eligibility: dict, profile: MatchProfile) -> FieldResult:
    income = eligibility.get("income") or {}
    cond = income.get("cond")
    if not cond or cond in yc.UNRESTRICTED:
        return FieldResult("income", "open")
    lo, hi = income.get("min") or 0, income.get("max") or 0
    if cond != "0043002" or (not lo and not hi):
        # 0043003(기타)은 금액 없이 자유 텍스트로만 온다 — 기계적으로 판정 불가.
        return FieldResult("income", "unknown", "소득 조건 확인 필요")
    span = f"연소득 {lo or ''}~{hi or ''}만원"
    if profile.annual_income is None:
        return FieldResult("income", "unknown", f"소득 조건 확인 필요({span})")
    if (not lo or profile.annual_income >= lo) and (not hi or profile.annual_income <= hi):
        return FieldResult("income", "match", "소득 조건")
    return FieldResult("income", "mismatch", f"소득 조건({span})")


def score_item(eligibility: dict | None, profile: MatchProfile, today: date | None = None) -> ItemMatch:
    """정책 하나를 티어로. 순수 함수 — DB도 LLM도 건드리지 않는다."""
    if not eligibility:
        # 자격조건 정보가 없는 항목(고용24 훈련과정·구직자프로그램)은 판정할 게 없다.
        return ItemMatch(tier="none")
    today = today or date.today()
    results = [
        _age(eligibility, profile, today),
        _region(eligibility, profile),
        _marital(eligibility, profile),
        _coded("education", eligibility.get("school"), profile.education_code, yc.SCHOOL, "학력"),
        _coded("major", eligibility.get("major"), profile.major_code, yc.MAJOR, "전공"),
        _coded("job_status", eligibility.get("job_status"), profile.employment_code, yc.JOB_STATUS, "취업상태"),
        _special(eligibility, profile),
        _income(eligibility, profile),
    ]
    matched = [r.label for r in results if r.verdict == "match"]
    unmet = [r.label for r in results if r.verdict in ("unknown", "mismatch") and r.label]
    mismatches = sum(1 for r in results if r.verdict == "mismatch")

    tier: Tier
    if any(r.verdict == "mismatch" and r.field in _HARD_FIELDS for r in results):
        tier = "excluded"
    elif not matched:
        tier = "none"
    elif any(r.verdict in ("mismatch", "unknown") for r in results):
        tier = "some"
    else:
        tier = "all"
    return ItemMatch(tier=tier, matched_labels=matched, unmet_labels=unmet, mismatch_count=mismatches)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _recency(item: FeedItem) -> float:
    """최신 우선 정렬 키(클수록 최신). 정책은 등록일을 우선한다."""
    if item.source_published_at is not None:
        return datetime.combine(item.source_published_at, time(), tzinfo=timezone.utc).timestamp()
    if item.first_seen_at is not None:
        return _aware(item.first_seen_at).timestamp()
    return 0.0


async def rank_tiered(
    db: AsyncSession,
    *,
    feed_kind: str,
    profile: MatchProfile,
    profile_vector: list[float] | None = None,
    category: str | None = None,
    include_excluded: bool = False,
    limit: int = 20,
    offset: int = 0,
    today: date | None = None,
) -> RankedFeed:
    """티어 순 → 명시 일치 수 → 불일치 수 → 벡터 거리 → 최신 → id.

    풀 전체(활성 정책 ≤ 수천 건)를 파이썬에서 정렬한 뒤 자른다. SQL로 옮기지
    않은 이유는 필드별 판정이 JSON 안의 코드 목록을 다뤄야 해서다. 정렬 키가
    완전히 결정적이라(마지막 id) limit/offset 페이지가 겹치거나 빠지지 않는다 —
    ranking.py가 지키는 것과 같은 보장이다.
    """
    distances: dict = {}
    vector_failed = False
    if profile_vector is not None:
        # 벡터 질의를 **항목을 읽기 전에** 한다. 실패하면 rollback하는데, rollback은
        # 세션에 올라온 ORM 객체를 전부 expire시켜 이후 속성 접근이 lazy load(IO)가
        # 되고 요청 핸들러에서 MissingGreenlet으로 터진다(api/feed.py 주석 참고).
        try:
            rows = (
                await db.execute(
                    select(FeedItemEmbedding.feed_item_id, FeedItemEmbedding.embedding.cosine_distance(profile_vector))
                    .join(FeedItem, FeedItem.id == FeedItemEmbedding.feed_item_id)
                    .where(
                        FeedItem.is_active.is_(True),
                        FeedItem.feed_kind == feed_kind,
                        FeedItemEmbedding.embedding.is_not(None),
                    )
                )
            ).all()
            distances = {item_id: float(d) for item_id, d in rows if d is not None}
        except Exception:
            await db.rollback()
            logger.warning("feed: vector distances unavailable for tiered ranking", exc_info=True)
            vector_failed = True

    stmt = select(FeedItem).where(FeedItem.is_active.is_(True), FeedItem.feed_kind == feed_kind)
    if category is not None:
        stmt = stmt.where(FeedItem.category == category)
    items = list((await db.execute(stmt)).scalars().all())

    scored: list[tuple[tuple, FeedItem, ItemMatch]] = []
    for item in items:
        match = score_item(item.eligibility, profile, today)
        if match.tier == "excluded" and not include_excluded:
            continue
        distance = distances.get(item.id)
        key = (
            _TIER_ORDER[match.tier],
            -len(match.matched_labels),
            match.mismatch_count,
            distance if distance is not None else math.inf,
            -_recency(item),
            str(item.id),
        )
        scored.append((key, item, match))
    scored.sort(key=lambda t: t[0])

    page = scored[offset : offset + limit]
    return RankedFeed(
        items=[item for _, item, _ in page],
        total=len(scored),
        personalized=True,
        vector_ranking_failed=vector_failed,
        matches={item.id: match for _, item, match in page},
    )


def get_tiered_ranker():
    """FastAPI DI 훅 — get_feed_ranker와 같은 이유."""
    return rank_tiered


__all__ = ["ItemMatch", "MatchProfile", "get_tiered_ranker", "rank_tiered", "score_item"]
