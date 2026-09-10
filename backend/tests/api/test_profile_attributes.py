from __future__ import annotations

import asyncio

from app.models.feed_item import FeedItem
from tests.api.test_profile import _answer_one_turn, _register_and_login, _session_at_interviewing


def _guest_headers(client):
    guest = client.post("/api/v1/auth/guest").json()
    return {"Authorization": f"Bearer {guest['access_token']}"}


# ── 추출 훅 ────────────────────────────────────────────────────────────────


def test_each_interview_answer_schedules_attribute_extraction(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, session_id, "수원에 살고 26살이에요. 주 3회 편의점에서 일했어요")

    calls = session_client.fake_extractor.calls
    # 구조 질문("하나뿐이에요")은 서사가 아니라 라우팅 정보라 추출 대상이 아니다.
    assert [(kind, text) for _, kind, text, _ in calls] == [
        ("interview_answer", "수원에 살고 26살이에요. 주 3회 편의점에서 일했어요")
    ]
    assert calls[0][3] is not None  # 원 답변 id — 답변을 지우면 추정 속성도 지우는 연결 고리


def test_saving_the_wish_text_schedules_extraction(session_client):
    headers = _register_and_login(session_client)
    session_client.put("/api/v1/me/preferences", headers=headers, json={"wish_text": "경기 남부에서 사무직"})
    assert [kind for _, kind, _, _ in session_client.fake_extractor.calls] == ["wish_text"]


# ── 프로필 편집 ────────────────────────────────────────────────────────────


def test_user_can_add_edit_confirm_and_delete_attributes(session_client):
    headers = _register_and_login(session_client)

    resp = session_client.post("/api/v1/me/attributes", headers=headers, json={"key": "residence_region", "value": "수원"})
    assert resp.status_code == 201
    attr = resp.json()
    assert attr["label"] == "수원" and attr["status"] == "user_edited" and attr["key_label"] == "거주지"

    resp = session_client.patch(f"/api/v1/me/attributes/{attr['id']}", headers=headers, json={"value": "성남"})
    assert resp.json()["label"] == "성남"

    listing = session_client.get("/api/v1/me/attributes", headers=headers).json()
    assert [a["label"] for a in listing["attributes"]] == ["성남"]
    region_key = next(k for k in listing["keys"] if k["key"] == "residence_region")
    assert "수원" in region_key["choices"]

    assert session_client.delete(f"/api/v1/me/attributes/{attr['id']}", headers=headers).status_code == 204
    assert session_client.get("/api/v1/me/attributes", headers=headers).json()["attributes"] == []


def test_values_outside_the_vocabulary_are_rejected(session_client):
    headers = _register_and_login(session_client)
    resp = session_client.post(
        "/api/v1/me/attributes", headers=headers, json={"key": "education_level", "value": "대졸"}
    )
    assert resp.status_code == 422
    resp = session_client.post("/api/v1/me/attributes", headers=headers, json={"key": "blood_type", "value": "A"})
    assert resp.status_code == 422


def test_sensitive_attributes_require_consent_and_are_erased_on_revoke(session_client):
    headers = _register_and_login(session_client)
    body = {"key": "special_groups", "value": "한부모가정"}

    assert session_client.post("/api/v1/me/attributes", headers=headers, json=body).status_code == 403

    consent = session_client.put("/api/v1/me/consents/sensitive-profiling", headers=headers, json={"granted": True})
    assert consent.json()["granted"] is True
    assert session_client.post("/api/v1/me/attributes", headers=headers, json=body).status_code == 201

    session_client.put("/api/v1/me/consents/sensitive-profiling", headers=headers, json={"granted": False})
    assert session_client.get("/api/v1/me/attributes", headers=headers).json()["attributes"] == []


def test_guests_can_manage_attributes_but_cannot_consent_to_sensitive_ones(session_client):
    headers = _guest_headers(session_client)
    resp = session_client.post("/api/v1/me/attributes", headers=headers, json={"key": "residence_region", "value": "수원"})
    assert resp.status_code == 201

    resp = session_client.put("/api/v1/me/consents/sensitive-profiling", headers=headers, json={"granted": True})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "registered_account_required"


def test_other_users_attributes_are_not_reachable(session_client):
    alice = _register_and_login(session_client, email="alice@example.com")
    bob = _register_and_login(session_client, email="bob@example.com")
    attr = session_client.post("/api/v1/me/attributes", headers=alice, json={"key": "skills", "value": "엑셀"}).json()

    assert session_client.delete(f"/api/v1/me/attributes/{attr['id']}", headers=bob).status_code == 404
    assert session_client.patch(f"/api/v1/me/attributes/{attr['id']}", headers=bob, json={"value": "워드"}).status_code == 404


# ── 맞춤 정책(티어 매칭) ─────────────────────────────────────────────────


def _add_policy(client, title: str, eligibility: dict | None) -> None:
    async def _insert():
        async with client.session_local() as db:
            db.add(
                FeedItem(
                    source="youthcenter",
                    category="youth_policy",
                    feed_kind="policy",
                    dedup_key=f"k:{title}",
                    title=title,
                    eligibility=eligibility,
                )
            )
            await db.commit()

    asyncio.run(_insert())


_OPEN = {
    "age": None, "zip_codes": [], "nationwide": True, "school": ["0049010"], "major": ["0011009"],
    "job_status": ["0013010"], "special": ["0014010"], "marital": "0055003", "income": None,
}


def test_recommended_policies_put_the_intersection_first_and_label_it(feed_client):
    headers = _register_and_login(feed_client)
    feed_client.post("/api/v1/me/attributes", headers=headers, json={"key": "residence_region", "value": "수원"})
    feed_client.post("/api/v1/me/attributes", headers=headers, json={"key": "employment_status", "value": "미취업자"})

    _add_policy(feed_client, "전국 누구나", _OPEN)
    _add_policy(feed_client, "수원 미취업 청년", {**_OPEN, "nationwide": False, "zip_codes": ["41111"], "job_status": ["0013003"]})
    _add_policy(feed_client, "고양시 전용", {**_OPEN, "nationwide": False, "zip_codes": ["41281"]})
    _add_policy(feed_client, "재직자 전용", {**_OPEN, "job_status": ["0013001"], "school": ["0049007"]})

    resp = feed_client.get("/api/v1/feed/policies/recommended", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["personalized"] is True
    titles = [i["title"] for i in body["items"]]
    assert titles[0] == "수원 미취업 청년"
    assert "고양시 전용" not in titles  # 거주지가 맞지 않으면 신청 자격이 없다
    first = body["items"][0]
    assert first["match_tier"] == "all"
    assert first["matched_labels"] == ["수원 거주", "미취업자"]


def test_recommended_policies_only_include_youth_policies(feed_client):
    """고용24 훈련·프로그램은 자격조건이 없어 매칭이 안 된다 — 맞춤 정책에서 뺀다."""
    headers = _register_and_login(feed_client)
    feed_client.post("/api/v1/me/attributes", headers=headers, json={"key": "residence_region", "value": "수원"})
    _add_policy(feed_client, "전국 누구나", _OPEN)

    async def _insert_training():
        async with feed_client.session_local() as db:
            db.add(FeedItem(source="worknet", category="training_course", feed_kind="policy", dedup_key="k:t", title="훈련과정"))
            await db.commit()

    asyncio.run(_insert_training())

    for path in ("/api/v1/feed/policies/recommended", "/api/v1/feed/policies"):
        titles = [i["title"] for i in feed_client.get(path, headers=headers).json()["items"]]
        assert "훈련과정" not in titles, path
        assert "전국 누구나" in titles, path


def test_recommended_policies_without_any_attribute_fall_back_to_recency(feed_client):
    headers = _register_and_login(feed_client)
    _add_policy(feed_client, "아무 정책", _OPEN)

    body = feed_client.get("/api/v1/feed/policies/recommended", headers=headers).json()
    assert body["personalized"] is False
    assert body["fallback_reason"] == "no_attributes"
    assert [i["title"] for i in body["items"]] == ["아무 정책"]
