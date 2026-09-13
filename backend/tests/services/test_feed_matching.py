from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.feed_item import FeedItem
from app.models.feed_item_embedding import FeedItemEmbedding
from app.models.feed_item_occupation_embedding import FeedItemOccupationEmbedding
from app.services.feed import matching
from app.services.feed.matching import (
    MatchProfile,
    job_region_hit,
    occupation_score,
    rank_by_region,
    rank_jobs_by_profile,
    rank_tiered,
    region_hit,
    score_item,
)

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


def _job(title: str, subtitle: str = "", meta_lines: list[str] | None = None, category: str = "public_recruitment") -> FeedItem:
    return FeedItem(
        source="worknet",
        category=category,
        feed_kind="job",
        dedup_key=f"k:{title}",
        title=title,
        subtitle=subtitle,
        meta_lines=meta_lines or [],
        first_seen_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def test_occupation_score_ranks_substring_over_token_overlap_over_none():
    programmer_job = _job("경기 프로그래머 채용")
    assert occupation_score("프로그래머", programmer_job) == 2
    token_overlap_job = _job("경기 IT 프로그래머 모집 공고")
    assert occupation_score("백엔드 프로그래머", token_overlap_job) == 1
    unrelated_job = _job("부산 조리사 채용")
    assert occupation_score("프로그래머", unrelated_job) == 0
    assert occupation_score(None, programmer_job) == 0


def test_job_region_hit_matches_text_not_eligibility_code():
    # 구인공고는 eligibility에 지역 코드가 없다 — region_hit(코드 비교)이 아니라
    # 텍스트 부분일치로 지역을 본다.
    gyeonggi_job = _job("채용공고", meta_lines=["지역: 경기도 수원시"])
    seoul_job = _job("채용공고", meta_lines=["지역: 서울 강남구"])
    profile = MatchProfile(desired_region_codes=frozenset({"41"}))
    assert job_region_hit(gyeonggi_job, profile) == "경기 관련"
    assert job_region_hit(seoul_job, profile) is None
    assert job_region_hit(gyeonggi_job, MatchProfile()) is None


@pytest.mark.asyncio
async def test_rank_jobs_by_profile_puts_occupation_and_region_matches_first(db_session):
    async with db_session() as db:
        db.add_all(
            [
                _job("부산 조리사 채용", meta_lines=["지역: 부산 해운대구"], category="public_recruitment"),
                _job("경기 프로그래머 채용", meta_lines=["지역: 경기도 수원시"], category="public_recruitment"),
                _job("서울 회계사 채용", meta_lines=["지역: 서울 강남구"], category="promising_sme"),
            ]
        )
        await db.commit()

        profile = MatchProfile(desired_region_codes=frozenset({"41"}), desired_job="프로그래머")
        ranked = await rank_jobs_by_profile(
            db,
            feed_kind="job",
            categories=("public_recruitment", "promising_sme"),
            profile=profile,
            limit=10,
        )

        assert ranked.total == 3
        assert ranked.items[0].title == "경기 프로그래머 채용"
        assert ranked.matches[ranked.items[0].id].matched_labels == ["희망직무 프로그래머 관련", "경기 관련"]
        # 직무·지역 둘 다 안 맞는 항목도 빠지지 않고 뒤로 밀린다.
        assert {i.title for i in ranked.items[1:]} == {"부산 조리사 채용", "서울 회계사 채용"}


def _fake_vector_distances(by_class: dict[type, dict]):
    """matching._vector_distances를 대신할 스텁 — SQLite에는
    feed_item_occupation_embeddings가 없어 실제 코사인 질의를 못 하므로, 이
    함수로 embedding_cls별 거리표를 직접 주입한다."""

    async def fake(db, feed_kind, profile_vector, *, embedding_cls=FeedItemEmbedding):
        if profile_vector is None:
            return {}, False
        return by_class.get(embedding_cls, {}), False

    return fake


@pytest.mark.asyncio
async def test_rank_jobs_by_profile_prefers_a_measured_vector_over_a_guessed_text_score(db_session, monkeypatch):
    async with db_session() as db:
        vector_match = _job("경기 마케터 채용", meta_lines=["지역: 경기도 수원시"])
        text_match = _job("경기 프로그래머 채용", meta_lines=["지역: 경기도 수원시"])
        db.add_all([vector_match, text_match])
        await db.commit()
        await db.refresh(vector_match)
        await db.refresh(text_match)

        # vector_match는 제목에 "프로그래머"가 없어 텍스트 점수는 0이지만,
        # 벡터 거리가 측정돼 있다 — 측정된 신호가 추측(텍스트 점수)보다
        # 우선해야 하므로 text_match(텍스트 점수 2, 벡터 없음)보다 앞서야 한다.
        monkeypatch.setattr(
            matching,
            "_vector_distances",
            _fake_vector_distances({FeedItemOccupationEmbedding: {vector_match.id: 0.1}}),
        )

        profile = MatchProfile(desired_region_codes=frozenset({"41"}), desired_job="프로그래머")
        ranked = await rank_jobs_by_profile(
            db,
            feed_kind="job",
            categories=("public_recruitment",),
            profile=profile,
            occupation_vector=[0.0],
            limit=10,
        )

        assert ranked.items[0].id == vector_match.id
        assert ranked.matches[vector_match.id].matched_labels == ["희망직무 프로그래머 관련", "경기 관련"]


@pytest.mark.asyncio
async def test_rank_by_region_puts_region_before_a_closer_occupation_vector(db_session, monkeypatch):
    async with db_session() as db:
        near_but_off_topic = _training("수원 회계 과정", "41113", 1)
        far_but_on_topic = _training("고양 개발 과정", "41285", 2)
        db.add_all([near_but_off_topic, far_but_on_topic])
        await db.commit()
        await db.refresh(near_but_off_topic)
        await db.refresh(far_but_on_topic)

        # far_but_on_topic이 직무 벡터로는 훨씬 가깝지만(0.05 vs 0.9), 지역이
        # 안 맞으므로(수원 거주자에게 고양은 안 가까움) 여전히 뒤로 가야 한다.
        monkeypatch.setattr(
            matching,
            "_vector_distances",
            _fake_vector_distances(
                {FeedItemOccupationEmbedding: {near_but_off_topic.id: 0.9, far_but_on_topic.id: 0.05}}
            ),
        )

        profile = MatchProfile(residence_code="41110", desired_job="개발자")
        ranked = await rank_by_region(
            db,
            feed_kind="policy",
            categories=("training_course",),
            profile=profile,
            occupation_vector=[0.0],
            limit=10,
        )

        assert ranked.items[0].id == near_but_off_topic.id


@pytest.mark.asyncio
async def test_rank_tiered_never_lets_occupation_cross_a_tier_boundary(db_session, monkeypatch):
    async with db_session() as db:
        # some 티어(학력 불일치) — 직무 벡터는 아주 가깝다.
        some_tier = _policy(
            "some-tier-on-topic", elig(age={"min": 19, "max": 39}, school=["0049005"]), 1
        )
        # all 티어(전부 열림/일치) — 직무 벡터는 안 뽑혀 있다(무관하게).
        all_tier = _policy("all-tier-off-topic", elig(age={"min": 19, "max": 39}, job_status=["0013003"]), 2)
        db.add_all([some_tier, all_tier])
        await db.commit()
        await db.refresh(some_tier)
        await db.refresh(all_tier)

        monkeypatch.setattr(
            matching, "_vector_distances", _fake_vector_distances({FeedItemOccupationEmbedding: {some_tier.id: 0.01}})
        )

        ranked = await rank_tiered(
            db, feed_kind="policy", profile=SUWON, occupation_vector=[0.0], limit=10, offset=0, today=TODAY
        )

        # all 티어가 여전히 먼저 온다 — 직무 벡터가 아무리 가까워도 some 티어가
        # all 티어를 앞지르면 안 된다(온통청년 정책엔 직무 자격조건이 없다).
        assert ranked.items[0].id == all_tier.id
        assert ranked.matches[all_tier.id].tier == "all"
        assert ranked.matches[some_tier.id].tier == "some"
