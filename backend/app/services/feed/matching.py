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
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feed_item import FeedItem
from app.models.feed_item_embedding import FeedItemEmbedding
from app.models.feed_item_occupation_embedding import FeedItemOccupationEmbedding
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
    #: 희망 근무지역 코드들. 정책 자격조건과는 무관해(정책은 "거주지" 기준) 티어
    #: 매칭에는 안 쓰고, 맞춤 직업훈련의 지역 우선 정렬에만 쓴다.
    desired_region_codes: frozenset[str] = frozenset()
    #: 희망 직무 자유 텍스트(예: "프로그래머"). 정책 티어 매칭에는 안 쓰고, 맞춤
    #: 공고의 직무 관련성 정렬에만 쓴다 — 온통청년 정책엔 직무 자격조건 자체가 없다.
    desired_job: str | None = None

    @property
    def region_codes(self) -> tuple[str, ...]:
        """지역 우선 정렬에 쓰는 코드 — 거주지 먼저, 그다음 희망지역."""
        return tuple(c for c in (self.residence_code, *sorted(self.desired_region_codes)) if c)

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


async def _vector_distances(
    db: AsyncSession,
    feed_kind: str,
    profile_vector: list[float] | None,
    *,
    embedding_cls: type = FeedItemEmbedding,
) -> tuple[dict, bool]:
    """(항목 id → 코사인 거리, 벡터 질의가 실패했는가).

    embedding_cls로 FeedItemEmbedding(문답·희망사항 통짜 프로필 벡터) 또는
    FeedItemOccupationEmbedding(희망직무 전용 벡터)을 고른다 — 두 테이블이
    같은 모양(feed_item_id PK/FK + embedding)이라 조인 질의를 그대로 재사용한다.

    **항목을 읽기 전에** 불러야 한다. 실패하면 rollback하는데, rollback은 세션에
    올라온 ORM 객체를 전부 expire시켜 이후 속성 접근이 lazy load(IO)가 되고 요청
    핸들러에서 MissingGreenlet으로 터진다(api/feed.py 주석 참고). SQLite 테스트에는
    벡터 테이블이 없어 여기서 조용히 빈 dict가 된다.
    """
    if profile_vector is None:
        return {}, False
    try:
        rows = (
            await db.execute(
                select(embedding_cls.feed_item_id, embedding_cls.embedding.cosine_distance(profile_vector))
                .join(FeedItem, FeedItem.id == embedding_cls.feed_item_id)
                .where(
                    FeedItem.is_active.is_(True),
                    FeedItem.feed_kind == feed_kind,
                    embedding_cls.embedding.is_not(None),
                )
            )
        ).all()
    except Exception:
        await db.rollback()
        logger.warning("feed: vector distances unavailable", exc_info=True)
        return {}, True
    return {item_id: float(d) for item_id, d in rows if d is not None}, False


def _same_area(area_code: str, user_code: str) -> bool:
    """개설 지역(시군구 5자리)이 사용자 지역(광역 2자리 또는 시·군 5자리) 안인가.

    통합 전 코드(29/46)는 양쪽 다 12로 맞춘다. 시 코드(41110)는 구 코드
    (41111·41113 …)와 앞 4자리를 공유한다(_region과 같은 규칙).
    """
    area_sido = yc.REGION_ALIASES.get(area_code[:2], area_code[:2])
    user_sido = yc.REGION_ALIASES.get(user_code[:2], user_code[:2])
    if area_sido != user_sido:
        return False
    if len(user_code) == 5 and user_code[:2] not in yc.REGION_ALIASES:
        return area_code[:4] == user_code[:4]
    return True


def region_hit(area_code: str | None, profile: MatchProfile) -> str | None:
    """가까운 과정이면 카드에 보일 이유("수원 거주지역"), 아니면 None."""
    if not area_code:
        return None
    if profile.residence_code and _same_area(area_code, profile.residence_code):
        return f"{region_label_for(profile.residence_code) or profile.residence_code} 거주지역"
    for code in sorted(profile.desired_region_codes):
        if _same_area(area_code, code):
            return f"희망지역 {region_label_for(code) or code}"
    return None


async def rank_by_region(
    db: AsyncSession,
    *,
    feed_kind: str,
    categories: tuple[str, ...],
    profile: MatchProfile,
    profile_vector: list[float] | None = None,
    occupation_vector: list[float] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> RankedFeed:
    """맞춤 직업훈련 — 거주지·희망지역에서 열리는 과정 먼저(통학 문제라 지역이
    직무보다 우선, 2026-09-11 결정 유지), 그 안에서 희망직무 벡터 유사도,
    그다음 프로필 벡터 유사도, 그다음 최신·id.

    지역이 안 맞는 과정도 **빼지 않고 뒤로 보낸다.** 정책과 달리 훈련은 신청
    자격이 지역에 묶이지 않는다(원격 과정, 통학 가능 거리). 정렬 키가 완전히
    결정적이라 limit/offset 페이지가 겹치거나 빠지지 않는다.

    occupation_vector가 없거나(직무 미설정) 항목 쪽 벡터가 아직 없으면 그
    항목은 occ_distance가 math.inf가 돼 이전과 동일하게 동점 처리된다 —
    순수 추가 차원이라 회귀 위험이 없다.
    """
    distances, vector_failed = await _vector_distances(db, feed_kind, profile_vector)
    occ_distances, occ_vector_failed = await _vector_distances(
        db, feed_kind, occupation_vector, embedding_cls=FeedItemOccupationEmbedding
    )
    vector_failed = vector_failed or occ_vector_failed
    items = list(
        (
            await db.execute(
                select(FeedItem).where(
                    FeedItem.is_active.is_(True),
                    FeedItem.feed_kind == feed_kind,
                    FeedItem.category.in_(categories),
                )
            )
        ).scalars().all()
    )

    scored: list[tuple[tuple, FeedItem, ItemMatch]] = []
    for item in items:
        hit = region_hit((item.eligibility or {}).get("area_code"), profile)
        occ_distance = occ_distances.get(item.id)
        distance = distances.get(item.id)
        key = (
            0 if hit else 1,
            occ_distance if occ_distance is not None else math.inf,
            distance if distance is not None else math.inf,
            -_recency(item),
            str(item.id),
        )
        # 티어 배지("조건 N개 모두 일치")는 정책 전용이라 none으로 두고, 가까운
        # 이유만 matched_labels로 싣는다 — 카드에 "✓ 수원 거주지역"으로 보인다.
        scored.append((key, item, ItemMatch(tier="none", matched_labels=[hit] if hit else [])))
    scored.sort(key=lambda t: t[0])

    page = scored[offset : offset + limit]
    return RankedFeed(
        items=[item for _, item, _ in page],
        total=len(scored),
        personalized=True,
        vector_ranking_failed=vector_failed,
        matches={item.id: match for _, item, match in page},
    )


async def rank_tiered(
    db: AsyncSession,
    *,
    feed_kind: str,
    profile: MatchProfile,
    profile_vector: list[float] | None = None,
    occupation_vector: list[float] | None = None,
    category: str | None = None,
    include_excluded: bool = False,
    limit: int = 20,
    offset: int = 0,
    today: date | None = None,
) -> RankedFeed:
    """티어 순 → 명시 일치 수 → 불일치 수 → 희망직무 벡터 거리 → 프로필 벡터
    거리 → 최신 → id.

    풀 전체(활성 정책 ≤ 수천 건)를 파이썬에서 정렬한 뒤 자른다. SQL로 옮기지
    않은 이유는 필드별 판정이 JSON 안의 코드 목록을 다뤄야 해서다. 정렬 키가
    완전히 결정적이라(마지막 id) limit/offset 페이지가 겹치거나 빠지지 않는다 —
    ranking.py가 지키는 것과 같은 보장이다.

    **희망직무는 티어를 절대 안 바꾼다** — score_item()이 desired_job을 아예
    보지 않는다(온통청년 정책엔 직무 자격조건 자체가 없다). 같은 티어 안에서만
    직무 관련성이 프로필 벡터보다 먼저 순서를 가른다 — 더 구체적인 신호라서다.
    """
    distances, vector_failed = await _vector_distances(db, feed_kind, profile_vector)
    occ_distances, occ_vector_failed = await _vector_distances(
        db, feed_kind, occupation_vector, embedding_cls=FeedItemOccupationEmbedding
    )
    vector_failed = vector_failed or occ_vector_failed

    stmt = select(FeedItem).where(FeedItem.is_active.is_(True), FeedItem.feed_kind == feed_kind)
    if category is not None:
        stmt = stmt.where(FeedItem.category == category)
    items = list((await db.execute(stmt)).scalars().all())

    scored: list[tuple[tuple, FeedItem, ItemMatch]] = []
    for item in items:
        match = score_item(item.eligibility, profile, today)
        if match.tier == "excluded" and not include_excluded:
            continue
        occ_distance = occ_distances.get(item.id)
        distance = distances.get(item.id)
        key = (
            _TIER_ORDER[match.tier],
            -len(match.matched_labels),
            match.mismatch_count,
            occ_distance if occ_distance is not None else math.inf,
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


_TOKEN_SPLIT = re.compile(r"[,\s/·|()\-]+")


def _job_text(item: FeedItem) -> str:
    return " ".join([item.title, item.subtitle or "", *(item.meta_lines or [])])


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT.split(text) if len(t) >= 2}


def occupation_score(desired_job: str | None, item: FeedItem) -> int:
    """desired_job과 공고 텍스트의 겹침 정도. 0=무관, 1=토큰 일부 겹침,
    2=통짜 문자열 포함(가장 강한 신호).

    구인공고(job_fair/공채속보/공채기업정보/강소기업)는 고용24 API가 직무
    필터를 지원하지 않아(2026-09-13 실측) 서버에 요청할 수 없다 — 이미 캐시된
    제목/부제/메타 텍스트에 대해 여기서 로컬로 채점한다. 훈련과정의
    srchTraProcessNm 부분일치와 같은 수준의 단순함을 유지한다 — NLP 유사도
    매칭은 하지 않는다.
    """
    if not desired_job:
        return 0
    haystack = _job_text(item)
    squashed_job = re.sub(r"\s+", "", desired_job)
    if squashed_job and squashed_job in re.sub(r"\s+", "", haystack):
        return 2
    return 1 if _tokens(desired_job) & _tokens(haystack) else 0


def job_region_hit(item: FeedItem, profile: MatchProfile) -> str | None:
    """구인공고 텍스트에 프로필의 지역 라벨이 포함되는가.

    job_fair/공채속보/공채기업정보/강소기업 항목은 eligibility에 지역 코드가
    안 채워져 있어(worknet_source.py가 training_course만 채운다) region_hit의
    코드 비교를 못 쓴다 — 텍스트 부분일치로 대신한다.
    """
    haystack = _job_text(item)
    for code in (profile.residence_code, *sorted(profile.desired_region_codes)):
        if code and (label := region_label_for(code)) and label in haystack:
            return f"{label} 관련"
    return None


#: 벡터 거리가 이 값 이하면 "희망직무 관련" 라벨을 붙인다. bge-m3 실측 코사인
#: 거리 분포로 튜닝해야 하는 값이다 — SQLite에는 pgvector가 없어 자동 테스트로
#: 검증 불가능하고, 스테이징에서 실제 벡터를 찍어보고 조정한다.
OCCUPATION_VECTOR_LABEL_THRESHOLD = 0.35


async def rank_jobs_by_profile(
    db: AsyncSession,
    *,
    feed_kind: str,
    categories: tuple[str, ...],
    profile: MatchProfile,
    profile_vector: list[float] | None = None,
    occupation_vector: list[float] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> RankedFeed:
    """맞춤 공고 — 희망직무 겹침 우선, 그다음 지역 겹침, 그다음 프로필 벡터
    (문답·희망사항 텍스트) 유사도, 마지막 최신·id.

    직무 겹침은 벡터가 있으면(사용자+항목 둘 다) 코사인 거리로, 없으면 기존
    occupation_score(부분일치/토큰겹침) 텍스트 점수로 판단한다 — **측정된
    벡터 신호가 항상 추측(텍스트 점수)보다 우선한다.** 그래서 정렬 키를
    2단계로 나눈다: 벡터가 있는 항목은 거리 오름차순으로 먼저 오고, 벡터가
    없는 항목은(백필 전·Ollama 다운·직무 미설정) 텍스트 점수 내림차순으로
    그 뒤에 온다. 백필 지연 중인 항목이 완벽한 텍스트 일치라도 벡터 매칭
    항목 뒤로 밀리는 대가가 있지만, 다음 refresh_feed()에서 해소되는 일시적
    현상이고 오늘(벡터 없음)보다 나빠지지 않는다.

    구조화된 desired_job/희망지역이 하나도 없는 사용자는 이 함수를 타지 않는다
    (api/feed.py가 분기) — 벡터 전용 경로를 그대로 타야 회귀가 없다.
    """
    distances, vector_failed = await _vector_distances(db, feed_kind, profile_vector)
    occ_distances, occ_vector_failed = await _vector_distances(
        db, feed_kind, occupation_vector, embedding_cls=FeedItemOccupationEmbedding
    )
    vector_failed = vector_failed or occ_vector_failed

    items = list(
        (
            await db.execute(
                select(FeedItem).where(
                    FeedItem.is_active.is_(True),
                    FeedItem.feed_kind == feed_kind,
                    FeedItem.category.in_(categories),
                )
            )
        )
        .scalars()
        .all()
    )

    scored: list[tuple[tuple, FeedItem, ItemMatch]] = []
    for item in items:
        occ_score = occupation_score(profile.desired_job, item)
        occ_distance = occ_distances.get(item.id)
        has_occ_vector = occ_distance is not None
        region_reason = job_region_hit(item, profile)
        distance = distances.get(item.id)
        key = (
            0 if has_occ_vector else 1,
            occ_distance if has_occ_vector else -occ_score,
            0 if region_reason else 1,
            distance if distance is not None else math.inf,
            -_recency(item),
            str(item.id),
        )
        occ_label = (has_occ_vector and occ_distance <= OCCUPATION_VECTOR_LABEL_THRESHOLD) or occ_score > 0
        labels = [
            l for l in (f"희망직무 {profile.desired_job} 관련" if occ_label else None, region_reason) if l
        ]
        scored.append((key, item, ItemMatch(tier="none", matched_labels=labels)))
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


def get_region_ranker():
    """FastAPI DI 훅 — 맞춤 직업훈련용."""
    return rank_by_region


def get_jobs_ranker():
    """FastAPI DI 훅 — 맞춤 공고용."""
    return rank_jobs_by_profile


__all__ = [
    "ItemMatch",
    "MatchProfile",
    "get_jobs_ranker",
    "get_region_ranker",
    "get_tiered_ranker",
    "job_region_hit",
    "occupation_score",
    "rank_by_region",
    "rank_jobs_by_profile",
    "rank_tiered",
    "region_hit",
    "score_item",
]
