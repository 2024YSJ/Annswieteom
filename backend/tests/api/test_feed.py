from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.models.feed_item import FeedItem
from app.models.feed_refresh_state import FeedRefreshState
from app.models.interview_answer import InterviewAnswer
from app.models.user import User
from app.models.user_attribute import UserAttribute


def _register_and_login(client, email="feed@example.com", password="password123", nickname="Feed"):
    client.post("/api/v1/auth/register", json={"email": email, "password": password, "nickname": nickname})
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed(client, items, refresh_states=None):
    async def _run():
        async with client.session_local() as db:
            for item in items:
                db.add(item)
            for state in refresh_states or []:
                db.add(state)
            await db.commit()

    asyncio.run(_run())


def _item(title, *, feed_kind="job", category="job_fair", source="worknet", seen=None, published=None, dedup=None):
    return FeedItem(
        id=uuid.uuid4(),
        source=source,
        category=category,
        feed_kind=feed_kind,
        dedup_key=dedup or f"h:{title}",
        title=title,
        subtitle="",
        meta_lines=[],
        embed_text=title,
        first_seen_at=seen or datetime.now(timezone.utc),
        last_seen_at=seen or datetime.now(timezone.utc),
        source_published_at=published,
        is_active=True,
    )


def _fresh_state(source_key="worknet:job_fair"):
    now = datetime.now(timezone.utc)
    return FeedRefreshState(source_key=source_key, last_started_at=now, last_succeeded_at=now, item_count=1)


# ── 익명/인증 ──────────────────────────────────────────────────────────────


def test_anonymous_visitor_gets_the_job_feed(feed_client):
    """랜딩을 실제로 보는 건 로그아웃 방문자라, 여기서 401을 내면 기능이
    사실상 안 보인다."""
    _seed(feed_client, [_item("채용행사 A")], [_fresh_state()])
    resp = feed_client.get("/api/v1/feed/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert [i["title"] for i in body["items"]] == ["채용행사 A"]
    assert body["personalized"] is False
    assert body["fallback_reason"] is None


def test_anonymous_visitor_gets_the_policy_feed(feed_client):
    _seed(
        feed_client,
        [_item("청년월세 지원", feed_kind="policy", category="youth_policy", source="youthcenter")],
        [_fresh_state()],
    )
    resp = feed_client.get("/api/v1/feed/policies")
    assert resp.status_code == 200
    assert [i["title"] for i in resp.json()["items"]] == ["청년월세 지원"]


def test_anonymous_visitor_gets_the_training_feed(feed_client):
    _seed(feed_client, [_item("국민내일배움카드 과정", feed_kind="policy", category="training_course")], [_fresh_state()])
    resp = feed_client.get("/api/v1/feed/trainings")
    assert resp.status_code == 200
    assert [i["title"] for i in resp.json()["items"]] == ["국민내일배움카드 과정"]


def test_invalid_token_still_401s(feed_client):
    """get_current_user_optional의 계약 — 헤더가 아예 없으면 익명이지만,
    있는데 못 쓰는 토큰이면 401이다."""
    resp = feed_client.get("/api/v1/feed/jobs", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401


def test_recommended_requires_authentication(feed_client):
    assert feed_client.get("/api/v1/feed/jobs/recommended").status_code == 401


# ── 정렬/페이지네이션 ──────────────────────────────────────────────────────


def test_job_feed_is_newest_first(feed_client):
    base = datetime.now(timezone.utc)
    _seed(
        feed_client,
        [
            _item("오래된 것", seen=base - timedelta(days=2)),
            _item("최신", seen=base),
            _item("중간", seen=base - timedelta(days=1)),
        ],
        [_fresh_state()],
    )
    titles = [i["title"] for i in feed_client.get("/api/v1/feed/jobs").json()["items"]]
    assert titles == ["최신", "중간", "오래된 것"]


def test_pagination_does_not_repeat_or_skip_when_first_seen_at_is_identical(feed_client):
    """한 번의 수집 배치는 first_seen_at이 마이크로초까지 같다. 결정적 2차
    정렬 키(FeedItem.id)가 없으면 limit/offset이 조용히 행을 중복시키고
    누락시킨다 — 이 테스트가 그 회귀를 막는다."""
    same = datetime.now(timezone.utc)
    _seed(feed_client, [_item(f"공고 {n}", seen=same) for n in range(25)], [_fresh_state()])

    first = feed_client.get("/api/v1/feed/jobs?limit=10&offset=0").json()
    second = feed_client.get("/api/v1/feed/jobs?limit=10&offset=10").json()
    third = feed_client.get("/api/v1/feed/jobs?limit=10&offset=20").json()

    ids = [i["id"] for i in first["items"] + second["items"] + third["items"]]
    assert len(ids) == 25
    assert len(set(ids)) == 25
    assert first["total"] == 25


def test_policy_feed_prefers_the_source_published_date(feed_client):
    base = datetime.now(timezone.utc)
    _seed(
        feed_client,
        [
            # 늦게 수집됐지만 등록일이 오래된 정책
            _item(
                "옛날 등록", feed_kind="policy", category="youth_policy", source="youthcenter",
                seen=base, published=(base - timedelta(days=30)).date(),
            ),
            # 먼저 수집됐지만 등록일이 최신인 정책
            _item(
                "최근 등록", feed_kind="policy", category="youth_policy", source="youthcenter",
                seen=base - timedelta(days=5), published=base.date(),
            ),
        ],
        [_fresh_state()],
    )
    titles = [i["title"] for i in feed_client.get("/api/v1/feed/policies").json()["items"]]
    assert titles == ["최근 등록", "옛날 등록"]


def test_job_policy_and_training_feeds_do_not_leak_into_each_other(feed_client):
    """훈련과정·구직자프로그램은 policy로 저장되지만 "청년 지원 정책"에는 안 나온다
    — 훈련기관 이름만 적힌 카드가 정책 사이에 섞였었다(2026-09-11)."""
    _seed(
        feed_client,
        [
            _item("공고", feed_kind="job", category="job_fair"),
            _item("청년정책", feed_kind="policy", category="youth_policy", source="youthcenter"),
            _item("훈련과정", feed_kind="policy", category="training_course"),
            _item("취업특강", feed_kind="policy", category="job_seeker_program"),
        ],
        [_fresh_state()],
    )
    assert [i["title"] for i in feed_client.get("/api/v1/feed/jobs").json()["items"]] == ["공고"]
    policies = feed_client.get("/api/v1/feed/policies").json()
    assert [i["title"] for i in policies["items"]] == ["청년정책"]
    assert policies["total"] == 1
    trainings = feed_client.get("/api/v1/feed/trainings").json()
    assert sorted(i["title"] for i in trainings["items"]) == ["취업특강", "훈련과정"]
    assert trainings["total"] == 2


def test_training_feed_interleaves_its_two_categories(feed_client):
    """한 번의 수집이 카테고리를 차례로 넣으므로 최신순만 쓰면 한쪽이 통째로 앞을 막는다."""
    base = datetime.now(timezone.utc)
    _seed(
        feed_client,
        [_item(f"훈련 {n}", feed_kind="policy", category="training_course", seen=base) for n in range(3)]
        + [_item(f"특강 {n}", feed_kind="policy", category="job_seeker_program", seen=base - timedelta(hours=1)) for n in range(3)],
        [_fresh_state()],
    )
    categories = [i["category"] for i in feed_client.get("/api/v1/feed/trainings?limit=4").json()["items"]]
    assert categories.count("training_course") == 2 and categories.count("job_seeker_program") == 2


def test_inactive_items_are_excluded_from_items_and_total(feed_client):
    live = _item("살아있는 공고")
    dead = _item("사라진 공고")
    dead.is_active = False
    _seed(feed_client, [live, dead], [_fresh_state()])
    body = feed_client.get("/api/v1/feed/jobs").json()
    assert [i["title"] for i in body["items"]] == ["살아있는 공고"]
    assert body["total"] == 1


# ── 파라미터 검증 ──────────────────────────────────────────────────────────


def test_limit_over_the_maximum_is_422(feed_client):
    assert feed_client.get("/api/v1/feed/jobs?limit=51").status_code == 422
    assert feed_client.get("/api/v1/feed/jobs?limit=0").status_code == 422
    assert feed_client.get("/api/v1/feed/jobs?offset=-1").status_code == 422


def test_category_from_the_other_feed_kind_is_422(feed_client):
    """training_course는 policy 쪽 카테고리다 — /feed/jobs에서 요청하면
    빈 목록이 아니라 명시적 오류여야 한다."""
    resp = feed_client.get("/api/v1/feed/jobs?category=training_course")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_feed_category"


def test_unknown_category_is_422(feed_client):
    assert feed_client.get("/api/v1/feed/jobs?category=nope").status_code == 422


def test_category_from_another_section_is_422(feed_client):
    """같은 policy로 저장돼 있어도 섹션이 다르면 명시적 오류다."""
    assert feed_client.get("/api/v1/feed/policies?category=training_course").status_code == 422
    assert feed_client.get("/api/v1/feed/trainings?category=youth_policy").status_code == 422
    assert feed_client.get("/api/v1/feed/trainings?category=job_seeker_program").status_code == 200


def test_category_filter_narrows_within_a_feed_kind(feed_client):
    _seed(
        feed_client,
        [
            _item("행사", category="job_fair"),
            _item("강소기업", category="promising_sme"),
        ],
        [_fresh_state()],
    )
    body = feed_client.get("/api/v1/feed/jobs?category=promising_sme").json()
    assert [i["title"] for i in body["items"]] == ["강소기업"]
    assert body["total"] == 1


# ── stale-while-revalidate ────────────────────────────────────────────────


def test_empty_cache_reports_warming_and_schedules_a_refresh(feed_client):
    """BackgroundTasks는 응답을 보낸 뒤에 돌기 때문에 최초 1회는 구조적으로
    비어 있다. 프론트가 로딩 상태로 그릴 수 있도록 is_warming으로 알린다."""
    resp = feed_client.get("/api/v1/feed/jobs")
    body = resp.json()
    assert body["items"] == []
    assert body["is_warming"] is True
    assert feed_client.fake_refresher.calls == 1


def test_stale_cache_still_returns_rows_and_schedules_a_refresh(feed_client):
    """SWR의 핵심 계약 — 만료됐다고 사용자를 기다리게 하지 않는다."""
    old = datetime.now(timezone.utc) - timedelta(days=3)
    _seed(
        feed_client,
        [_item("캐시된 공고")],
        [FeedRefreshState(source_key="worknet:job_fair", last_started_at=old, last_succeeded_at=old)],
    )
    body = feed_client.get("/api/v1/feed/jobs").json()
    assert [i["title"] for i in body["items"]] == ["캐시된 공고"]
    assert body["is_warming"] is False
    assert feed_client.fake_refresher.calls == 1


def test_fresh_cache_does_not_schedule_a_refresh(feed_client):
    # 고용24 6개를 하드코딩했더니 온통청년 인증키가 발급돼 소스가 7개가 된
    # 순간 깨졌다(2026-09-09). 이 테스트가 확인하려는 건 "전부 신선하면 갱신을
    # 예약하지 않는다"이지 소스가 몇 개냐가 아니므로, 실제 설정된 목록을 쓴다.
    from app.services.feed.sources import configured_source_keys

    states = [_fresh_state(key) for key in configured_source_keys()]
    _seed(feed_client, [_item("캐시된 공고")], states)
    body = feed_client.get("/api/v1/feed/jobs").json()
    assert body["is_warming"] is False
    assert feed_client.fake_refresher.calls == 0


# ── 맞춤 공고 폴백 구분 ────────────────────────────────────────────────────


def _add_answer(client, user_email="feed@example.com", answer="반도체 공정 부트캠프를 6개월 수료했습니다"):
    async def _run():
        async with client.session_local() as db:
            from sqlalchemy import select

            user = (await db.execute(select(User).where(User.email == user_email))).scalar_one()
            db.add(
                InterviewAnswer(
                    user_id=user.id,
                    session_id=None,
                    category_label="교육",
                    category_type="education",
                    question_text="무엇을 하셨나요?",
                    question_source="fixed",
                    answer_text=answer,
                    confirmed_facts=[{"content": "반도체 공정 교육 수료", "fact_type": "task", "source_type": "user_confirmed"}],
                )
            )
            await db.commit()

    asyncio.run(_run())


def _add_desired_job_and_region(client, user_email="feed@example.com", desired_job="프로그래머", region_code="41", region_label="경기"):
    """희망직무·희망지역 user_attributes를 직접 심는다 — /me/attributes API를
    거치지 않는 이유는 이 테스트가 매칭 결과만 확인하면 되기 때문이다."""

    async def _run():
        async with client.session_local() as db:
            from sqlalchemy import select

            user = (await db.execute(select(User).where(User.email == user_email))).scalar_one()
            db.add_all(
                [
                    UserAttribute(
                        user_id=user.id,
                        key="desired_job",
                        value={"label": desired_job},
                        value_norm=desired_job,
                        status="confirmed",
                        source_kind="profile_form",
                    ),
                    UserAttribute(
                        user_id=user.id,
                        key="desired_region",
                        value={"label": region_label, "code": region_code},
                        value_norm=region_code,
                        status="confirmed",
                        source_kind="profile_form",
                    ),
                ]
            )
            await db.commit()

    asyncio.run(_run())


def test_recommended_jobs_ranks_occupation_and_region_matches_first(feed_client):
    """희망직무=프로그래머, 희망지역=경기로 설정하면 그 둘과 무관한 공고보다
    관련 공고가 위로 와야 한다 — 2026-09-13 리포트(지역만 맞고 직무는 무관한
    공고가 나옴)의 회귀 검증."""
    token = _register_and_login(feed_client)
    _add_desired_job_and_region(feed_client)
    _seed(
        feed_client,
        [
            _item("경기 프로그래머 채용", category="public_recruitment"),
            _item("부산 조리사 채용", category="public_recruitment"),
        ],
        [_fresh_state()],
    )
    # 두 번째 항목엔 관련성 텍스트가 없으니 meta_lines/subtitle을 직접 채운다.
    asyncio.run(
        _set_job_text(
            feed_client,
            {"경기 프로그래머 채용": ["지역: 경기도 수원시"], "부산 조리사 채용": ["지역: 부산 해운대구"]},
        )
    )

    body = feed_client.get("/api/v1/feed/jobs/recommended", headers=_auth(token)).json()
    assert body["personalized"] is True
    assert body["fallback_reason"] is None
    assert body["items"][0]["title"] == "경기 프로그래머 채용"


async def _set_job_text(client, meta_lines_by_title: dict[str, list[str]]):
    async with client.session_local() as db:
        from sqlalchemy import select

        for title, meta_lines in meta_lines_by_title.items():
            item = (await db.execute(select(FeedItem).where(FeedItem.title == title))).scalar_one()
            item.meta_lines = meta_lines
        await db.commit()


def test_recommended_jobs_schedules_the_occupation_embedder(feed_client):
    """희망직무가 있으면 백그라운드로 직무 벡터 갱신을 예약해야 한다 — SQLite엔
    user_occupation_embeddings가 없어 occupation_needs_refresh가 항상 True를
    주지만(테이블 부재 폴백, occupation_adapter 문서화됨), 그래도 매번
    예약하는 게 안전한 동작이다."""
    token = _register_and_login(feed_client)
    _add_desired_job_and_region(feed_client)
    _seed(feed_client, [_item("공고 A", category="public_recruitment")], [_fresh_state()])

    feed_client.get("/api/v1/feed/jobs/recommended", headers=_auth(token))

    assert len(feed_client.fake_occupation_embedder.calls) == 1


def test_recommended_jobs_does_not_schedule_the_occupation_embedder_without_a_desired_job(feed_client):
    token = _register_and_login(feed_client)
    _seed(feed_client, [_item("공고 A", category="public_recruitment")], [_fresh_state()])

    feed_client.get("/api/v1/feed/jobs/recommended", headers=_auth(token))

    assert feed_client.fake_occupation_embedder.calls == []


def test_recommended_trainings_schedules_the_occupation_embedder(feed_client):
    token = _register_and_login(feed_client)
    _add_desired_job_and_region(feed_client)
    _seed(feed_client, [_item("과정 A", feed_kind="policy", category="training_course")], [_fresh_state("worknet:training_course")])

    feed_client.get("/api/v1/feed/trainings/recommended", headers=_auth(token))

    assert len(feed_client.fake_occupation_embedder.calls) == 1


def test_recommended_policies_schedules_the_occupation_embedder(feed_client):
    token = _register_and_login(feed_client)

    async def _run():
        async with feed_client.session_local() as db:
            from sqlalchemy import select

            user = (await db.execute(select(User).where(User.email == "feed@example.com"))).scalar_one()
            db.add_all(
                [
                    UserAttribute(
                        user_id=user.id, key="desired_job", value={"label": "프로그래머"},
                        value_norm="프로그래머", status="confirmed", source_kind="profile_form",
                    ),
                    # 정책 게이트(profile.is_empty)는 desired_region_codes를 안 보므로
                    # 나이처럼 실제 정책 자격조건 필드가 하나는 있어야 개인화 분기를 탄다.
                    UserAttribute(
                        user_id=user.id, key="birth_year", value={"label": "2000년생", "year": 2000},
                        value_norm="2000", status="confirmed", source_kind="profile_form",
                    ),
                ]
            )
            await db.commit()

    asyncio.run(_run())
    _seed(
        feed_client,
        [_item("정책 A", feed_kind="policy", category="youth_policy")],
        [_fresh_state("youthcenter:youth_policy")],
    )

    feed_client.get("/api/v1/feed/policies/recommended", headers=_auth(token))

    assert len(feed_client.fake_occupation_embedder.calls) == 1


def test_recommended_without_any_answers_reports_no_profile(feed_client):
    """신규 사용자에게 고장 안내를 띄우면 안 된다 — 정보가 없는 것과
    서버가 죽은 것은 다른 상태다."""
    token = _register_and_login(feed_client)
    _seed(feed_client, [_item("공고 A")], [_fresh_state()])

    body = feed_client.get("/api/v1/feed/jobs/recommended", headers=_auth(token)).json()
    assert body["personalized"] is False
    assert body["fallback_reason"] == "no_profile"
    # 화면은 비지 않는다 — 최신순으로 채운다.
    assert [i["title"] for i in body["items"]] == ["공고 A"]
    # 임베딩할 프로필이 없으므로 백그라운드 작업도 안 잡는다.
    assert feed_client.fake_embedder.calls == []


def test_recommended_with_answers_but_no_vector_reports_preparing(feed_client):
    """문답은 쌓였는데 아직 벡터가 없다 = 방금 계산을 예약한 상태.

    문답을 처음 남긴 사용자는 전부 이 경로를 한 번 지나가므로 고장 안내가
    아니라 '준비 중'이어야 한다 — 실제 라이브 확인에서 정상 사용자에게
    "AI 서버가 수리 중"이 뜨는 오경보로 잡혔다."""
    token = _register_and_login(feed_client)
    _seed(feed_client, [_item("공고 A")], [_fresh_state()])
    _add_answer(feed_client)

    body = feed_client.get("/api/v1/feed/jobs/recommended", headers=_auth(token)).json()
    assert body["personalized"] is False
    assert body["fallback_reason"] == "preparing"
    assert [i["title"] for i in body["items"]] == ["공고 A"]
    # 벡터가 없으니 백그라운드로 계산을 예약해 다음 방문엔 개인화되게 한다.
    assert len(feed_client.fake_embedder.calls) == 1


def test_recommended_does_not_403_a_guest(feed_client):
    """api/profile.py는 게스트에게 403을 주지만 여기선 안 준다 — 랭킹은
    신호가 조금이라도 있으면 이득이고, 돌려주는 건 공개 공고뿐이다."""
    token = feed_client.post("/api/v1/auth/guest").json()["access_token"]
    _seed(feed_client, [_item("공고 A")], [_fresh_state()])

    resp = feed_client.get("/api/v1/feed/jobs/recommended", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["fallback_reason"] == "no_profile"
