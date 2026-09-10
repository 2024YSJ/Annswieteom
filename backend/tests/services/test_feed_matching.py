from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.feed_item import FeedItem
from app.services.feed.matching import MatchProfile, rank_by_region, rank_tiered, region_hit, score_item

TODAY = date(2026, 9, 11)

#: 2000년생(만 25~26세), 수원 거주, 미취업.
SUWON = MatchProfile(birth_year=2000, residence_code="41110", employment_code="0013003")

_GYEONGGI_ALL = [f"41{i:03d}" for i in range(47)] + ["41111", "41113"]


def elig(**overrides) -> dict:
    """전 필드 "제한없음"인 정책에서 필요한 필드만 바꾼다."""
    base = {
        "age": None,
        "zip_codes": [],
        "nationwide": True,
        "school": ["0049010"],
        "major": ["0011009"],
        "job_status": ["0013010"],
        "special": ["0014010"],
        "marital": "0055003",
        "income": {"cond": "0043001", "min": 0, "max": 0},
    }
    base.update(overrides)
    return base


def test_policy_without_any_condition_is_not_an_intersection_hit():
    # 조건 없는 정책까지 "모든 조건 일치"로 세면 교집합 칸이 그걸로 도배된다
    # (실측: 학력 제한없음 2,304/2,673건).
    assert score_item(elig(), SUWON, TODAY).tier == "none"


def test_every_restricted_field_matching_is_the_intersection_tier():
    match = score_item(
        elig(age={"min": 19, "max": 39}, nationwide=False, zip_codes=["41111", "41113"], job_status=["0013003"]),
        SUWON,
        TODAY,
    )
    assert match.tier == "all"
    assert match.matched_labels == ["만 19~39세", "수원 거주", "미취업자"]
    assert match.unmet_labels == []


def test_a_soft_mismatch_demotes_to_the_union_tier():
    match = score_item(elig(age={"min": 19, "max": 39}, job_status=["0013001"]), SUWON, TODAY)
    assert match.tier == "some"
    assert "취업상태: 재직자" in match.unmet_labels


def test_an_unknown_field_also_keeps_it_out_of_the_intersection():
    # 학력 조건이 있는데 사용자 학력을 모른다 — "모두 일치"라고 말할 수 없다.
    match = score_item(elig(age={"min": 19, "max": 39}, school=["0049005"]), SUWON, TODAY)
    assert match.tier == "some"
    assert any(label.startswith("학력 확인 필요") for label in match.unmet_labels)


def test_age_outside_the_range_excludes_the_policy():
    assert score_item(elig(age={"min": 19, "max": 24}), MatchProfile(birth_year=1990), TODAY).tier == "excluded"


def test_age_on_the_boundary_is_unknown_not_excluded():
    # 2000년생은 만 25 또는 26세. 상한 25세면 판정 불가 — 제외하면 멀쩡한 자격을 숨긴다.
    match = score_item(elig(age={"min": 19, "max": 25}), SUWON, TODAY)
    assert match.tier != "excluded"


def test_zero_and_one_age_bounds_mean_no_limit():
    assert score_item(elig(age={"min": 1, "max": 99}), SUWON, TODAY).tier == "none"


def test_policy_for_another_city_in_the_same_province_is_excluded():
    goyang_only = elig(nationwide=False, zip_codes=["41281", "41285"])
    assert score_item(goyang_only, SUWON, TODAY).tier == "excluded"


def test_province_only_user_matches_province_wide_policies_but_not_partial_ones():
    gyeonggi = MatchProfile(residence_code="41")
    whole = score_item(elig(nationwide=False, zip_codes=_GYEONGGI_ALL), gyeonggi, TODAY)
    partial = score_item(elig(nationwide=False, zip_codes=["41281"], job_status=["0013003"]), gyeonggi, TODAY)
    assert whole.tier == "all"
    # 시·군을 모르니 제외도 일치도 아니다.
    assert partial.tier == "none"
    assert any("시·군 확인 필요" in label for label in partial.unmet_labels)


def test_gwangju_users_match_the_merged_jeonnam_gwangju_code():
    # 2026년 광주·전남 통합 이후 온통청년은 29/46이 아니라 12를 쓴다.
    whole_province = [f"12{i:03d}" for i in range(27)]
    match = score_item(elig(nationwide=False, zip_codes=whole_province), MatchProfile(residence_code="29"), TODAY)
    assert match.tier == "all"
    assert match.matched_labels == ["전남광주 거주"]


def test_not_having_said_you_are_in_a_special_group_is_unknown_not_a_mismatch():
    match = score_item(elig(age={"min": 19, "max": 39}, special=["0014004"]), SUWON, TODAY)
    assert match.tier == "some"
    assert match.mismatch_count == 0


def test_consented_special_group_matches():
    profile = MatchProfile(birth_year=2000, special_codes=frozenset({"0014004"}))
    assert score_item(elig(special=["0014004"]), profile, TODAY).matched_labels == ["한부모가정"]


def test_items_without_eligibility_have_no_tier_to_claim():
    assert score_item(None, SUWON, TODAY).tier == "none"


def test_region_hit_matches_city_province_and_desired_regions():
    # 수원(41110) 사용자 — 권선구(41113)에서 열리는 과정은 가깝다, 고양(41285)은 아니다.
    assert region_hit("41113", SUWON) == "수원 거주지역"
    assert region_hit("41285", SUWON) is None
    # 희망지역이 서울이면 서울 과정도 가깝다.
    seoul_hope = MatchProfile(residence_code="41110", desired_region_codes=frozenset({"11"}))
    assert region_hit("11110", seoul_hope) == "희망지역 서울"
    # 통합 전 광주 코드(29)로 저장된 사용자도 12xxx 과정과 맞는다.
    assert region_hit("12110", MatchProfile(residence_code="29")) == "전남광주 거주지역"
    assert region_hit(None, SUWON) is None


@pytest.fixture
def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[FeedItem.__table__])

    asyncio.run(_create())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


def _policy(title: str, eligibility: dict | None, seen_offset: int) -> FeedItem:
    return FeedItem(
        source="youthcenter",
        category="youth_policy",
        feed_kind="policy",
        dedup_key=f"k:{title}",
        title=title,
        eligibility=eligibility,
        first_seen_at=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(minutes=seen_offset),
    )


@pytest.mark.asyncio
async def test_rank_tiered_orders_by_tier_and_pages_without_overlap(db_session):
    async with db_session() as db:
        db.add_all(
            [
                _policy("open-newest", elig(), 9),
                _policy("all", elig(age={"min": 19, "max": 39}, job_status=["0013003"]), 1),
                _policy("some", elig(age={"min": 19, "max": 39}, school=["0049005"]), 2),
                _policy("excluded-age", elig(age={"min": 30, "max": 39}), 3),
                _policy("no-eligibility", None, 8),
                _policy("open-older", elig(), 4),
            ]
        )
        await db.commit()

        # SQLite에는 벡터가 없으므로 티어 안에서는 최신순이다.
        pages = []
        for offset in range(0, 6, 2):
            ranked = await rank_tiered(db, feed_kind="policy", profile=SUWON, limit=2, offset=offset, today=TODAY)
            pages.extend(ranked.items)
            assert ranked.total == 5

        titles = [p.title for p in pages]
        assert titles == ["all", "some", "open-newest", "no-eligibility", "open-older"]
        assert len(set(titles)) == len(titles)

        with_excluded = await rank_tiered(
            db, feed_kind="policy", profile=SUWON, include_excluded=True, limit=10, offset=0, today=TODAY
        )
        assert with_excluded.items[-1].title == "excluded-age"
        assert with_excluded.matches[with_excluded.items[0].id].tier == "all"


def _training(title: str, area_code: str | None, seen_offset: int, category: str = "training_course") -> FeedItem:
    return FeedItem(
        source="worknet",
        category=category,
        feed_kind="policy",
        dedup_key=f"k:{title}",
        title=title,
        eligibility={"area_code": area_code} if area_code else None,
        first_seen_at=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(minutes=seen_offset),
    )


@pytest.mark.asyncio
async def test_rank_by_region_puts_nearby_courses_first_but_keeps_the_rest(db_session):
    async with db_session() as db:
        db.add_all(
            [
                _training("고양 최신", "41285", 9),
                _training("수원 과정", "41113", 1),
                _training("서울 과정", "11110", 5),
                _training("지역 모름", None, 8),
                _training("수원 특강", "41111", 2, category="job_seeker_program"),
                _policy("청년정책", elig(), 7),  # 다른 섹션 — 섞이면 안 된다
            ]
        )
        await db.commit()

        profile = MatchProfile(residence_code="41110", desired_region_codes=frozenset({"11"}))
        ranked = await rank_by_region(
            db, feed_kind="policy", categories=("training_course", "job_seeker_program"), profile=profile, limit=10
        )

        titles = [i.title for i in ranked.items]
        # 가까운 과정(수원 거주지역·희망지역 서울) 먼저 — 그 안에서는 벡터가 없으니 최신순.
        assert titles[:3] == ["서울 과정", "수원 특강", "수원 과정"]
        # 먼 과정도 빠지지 않는다 — 훈련은 지역에 자격이 묶이지 않는다.
        assert titles[3:] == ["고양 최신", "지역 모름"]
        assert ranked.total == 5
        assert ranked.matches[ranked.items[0].id].matched_labels == ["희망지역 서울"]
        assert ranked.matches[ranked.items[3].id].matched_labels == []
