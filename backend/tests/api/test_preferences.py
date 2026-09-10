from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from app.models.user import User
from app.models.user_preference import WISH_TEXT_MAX_CHARS
from app.services.feed.profile_adapter import has_profile_input, profile_needs_refresh, read_profile_signal


def _register_and_login(client, email="wish@example.com"):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123", "nickname": "Wish"})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _user_id(client, email="wish@example.com") -> uuid.UUID:
    async def _run():
        async with client.session_local() as db:
            return (await db.execute(select(User).where(User.email == email))).scalar_one().id

    return asyncio.run(_run())


def _adapter(client, fn, *args):
    async def _run():
        async with client.session_local() as db:
            return await fn(db, *args)

    return asyncio.run(_run())


# ── API ────────────────────────────────────────────────────────────────────


def test_requires_authentication(feed_client):
    assert feed_client.get("/api/v1/me/preferences").status_code == 401


def test_guest_cannot_use_it(feed_client):
    """맞춤 정보는 이메일 계정에 쌓인다 — 게스트는 회원가입 안내를 받는다."""
    token = feed_client.post("/api/v1/auth/guest").json()["access_token"]
    resp = feed_client.get("/api/v1/me/preferences", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "registered_account_required"


def test_unset_preference_is_empty_not_404(feed_client):
    """아직 안 쓴 상태는 정상이다 — 404를 주면 화면이 "불러오기 실패"와 구분을 못 한다."""
    headers = _register_and_login(feed_client)

    body = feed_client.get("/api/v1/me/preferences", headers=headers).json()

    assert body["wish_text"] == ""
    assert body["updated_at"] is None


def test_save_and_read_back(feed_client):
    headers = _register_and_login(feed_client)

    saved = feed_client.put(
        "/api/v1/me/preferences", headers=headers, json={"wish_text": "  반도체 장비 쪽 일을 찾고 있어요  "}
    ).json()

    # 앞뒤 공백은 저장 전에 다듬는다.
    assert saved["wish_text"] == "반도체 장비 쪽 일을 찾고 있어요"
    assert feed_client.get("/api/v1/me/preferences", headers=headers).json()["wish_text"] == saved["wish_text"]


def test_save_twice_updates_in_place(feed_client):
    headers = _register_and_login(feed_client)

    feed_client.put("/api/v1/me/preferences", headers=headers, json={"wish_text": "첫 번째"})
    feed_client.put("/api/v1/me/preferences", headers=headers, json={"wish_text": "두 번째"})

    assert feed_client.get("/api/v1/me/preferences", headers=headers).json()["wish_text"] == "두 번째"


def test_empty_string_clears_it(feed_client):
    """별도 삭제 API를 두지 않는다 — "지우기"가 곧 "빈 값으로 저장"이다."""
    headers = _register_and_login(feed_client)
    feed_client.put("/api/v1/me/preferences", headers=headers, json={"wish_text": "지울 내용"})

    feed_client.put("/api/v1/me/preferences", headers=headers, json={"wish_text": ""})

    assert feed_client.get("/api/v1/me/preferences", headers=headers).json()["wish_text"] == ""


def test_too_long_is_rejected(feed_client):
    """임베딩 입력의 일부라 무한정 길면 문답 쪽 신호를 덮어버린다."""
    headers = _register_and_login(feed_client)

    resp = feed_client.put(
        "/api/v1/me/preferences", headers=headers, json={"wish_text": "가" * (WISH_TEXT_MAX_CHARS + 1)}
    )

    assert resp.status_code == 422


def test_another_users_preference_is_not_visible(feed_client):
    mine = _register_and_login(feed_client, "mine@example.com")
    feed_client.put("/api/v1/me/preferences", headers=mine, json={"wish_text": "내 희망"})
    theirs = _register_and_login(feed_client, "theirs@example.com")

    assert feed_client.get("/api/v1/me/preferences", headers=theirs).json()["wish_text"] == ""


# ── 개인화 연동 ────────────────────────────────────────────────────────────


def test_wish_alone_turns_personalization_on(feed_client):
    """이 기능의 존재 이유다.

    예전에는 라우터가 문답 개수만 셌기 때문에, 공백기 정리를 안 한 사용자가
    맞춤 정보를 아무리 적어도 영영 개인화되지 않았다 — 그런데 그게 바로 이
    기능이 필요한 사람이다.
    """
    headers = _register_and_login(feed_client)
    user_id = _user_id(feed_client)

    assert _adapter(feed_client, has_profile_input, user_id) is False

    feed_client.put("/api/v1/me/preferences", headers=headers, json={"wish_text": "물류 창고 일을 찾아요"})

    assert _adapter(feed_client, has_profile_input, user_id) is True
    signal = _adapter(feed_client, read_profile_signal, user_id)
    assert signal.has_wish is True
    assert "물류 창고 일을 찾아요" in signal.text
    # 문답이 0건이어도 벡터를 만들 재료가 생겼으므로 갱신이 필요하다.
    assert _adapter(feed_client, profile_needs_refresh, user_id) is True


def test_recommended_feed_stops_saying_no_profile(feed_client):
    headers = _register_and_login(feed_client)

    before = feed_client.get("/api/v1/feed/jobs/recommended", headers=headers).json()
    assert before["fallback_reason"] == "no_profile"

    feed_client.put("/api/v1/me/preferences", headers=headers, json={"wish_text": "사무 보조 일이면 좋겠어요"})

    after = feed_client.get("/api/v1/feed/jobs/recommended", headers=headers).json()
    # 벡터는 아직 없으니 개인화 자체는 안 되지만, "정보가 없다"가 아니라
    # "준비 중"으로 바뀌어야 한다 — 사용자가 방금 정보를 준 게 반영돼야 한다.
    assert after["fallback_reason"] == "preparing"


def test_wish_is_placed_before_the_answers(feed_client):
    """희망사항이 4000자 상한에 걸려 잘려 나가면 안 된다 — 사용자가 방금 직접
    쓴 말이라 과거 문답보다 현재 의도를 잘 나타낸다."""
    import uuid as _uuid

    from app.models.interview_answer import InterviewAnswer

    headers = _register_and_login(feed_client)
    user_id = _user_id(feed_client)
    feed_client.put("/api/v1/me/preferences", headers=headers, json={"wish_text": "지금 원하는 일"})

    async def _add():
        async with feed_client.session_local() as db:
            db.add(
                InterviewAnswer(
                    id=_uuid.uuid4(), user_id=user_id, session_id=None,
                    category_label="교육", category_type="education",
                    question_text="q", question_source="fixed",
                    answer_text="옛날에 한 일", confirmed_facts=[],
                )
            )
            await db.commit()

    asyncio.run(_add())

    text = _adapter(feed_client, read_profile_signal, user_id).text
    assert text.index("지금 원하는 일") < text.index("옛날에 한 일")
