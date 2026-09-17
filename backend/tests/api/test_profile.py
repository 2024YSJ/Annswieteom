from __future__ import annotations

import asyncio
import uuid

from app.models.user_attribute import UserAttribute


def _register_and_login(client, email="archive@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "nickname": "Archie"},
    )
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _session_at_interviewing(client, headers):
    session_id = client.post("/api/v1/sessions", headers=headers).json()["id"]
    client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers,
        json={"categories": [{"category_type": "part_time", "custom_label": "편의점 알바"}]},
    )
    client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers)

    # 카테고리 첫 턴은 "여러 활동 있나요?" 구조 질문이라 문답 기록 대상이 아니다.
    client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "하나뿐이에요"}
    )
    client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [
            {"index": c["index"], "final_text": c["content"], "was_edited": False}
            for c in resp.json()["candidates"]
        ]},
    )
    return session_id


def _answer_one_turn(client, headers, session_id, text, confirm=False):
    """ask -> answer 한 턴. 카테고리 단위 확인(2026-09-11) 이후 답변마다 확인하는
    단계는 없다 — 사실 확정까지 필요한 테스트는 confirm=True로 카테고리를 끝까지
    답하고 확인까지 제출한다(_finish_category)."""
    client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": text}
    )
    assert resp.status_code == 200
    if confirm:
        _finish_category(client, headers, session_id, answer_body=resp.json())


def _finish_category(client, headers, session_id, answer_body):
    """남은 질문에 채움 답을 하고 카테고리 끝 확인을 모두 맞다고 제출한다."""
    for _ in range(20):
        if answer_body["mode"] == "review":
            break
        client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
        answer_body = client.post(
            f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "채움 답변"}
        ).json()
    review = answer_body["review"]
    confirmations = [
        {"turn_id": g["turn_id"], "index": d["index"], "final_text": d["content"], "was_edited": False}
        for g in review["groups"]
        for d in g["drafts"]
    ]
    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/review", headers=headers, json={"confirmations": confirmations}
    )
    assert resp.status_code == 200


def test_answers_are_archived_with_the_users_own_wording(session_client):
    """추출된 사실 문장이 아니라 사용자가 실제로 타이핑한 원문이 남아야 한다 —
    2026-09-09 전까지 이 원문은 어디에도 저장되지 않고 사라졌다."""
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, session_id, "주 3회 저녁 6시부터 10시까지 일했어요", confirm=True)

    resp = session_client.get("/api/v1/me/answers", headers=headers)
    assert resp.status_code == 200
    answers = resp.json()
    # 카테고리를 끝까지 답했으므로 채움 답변들도 함께 쌓인다 — 원문으로 찾는다.
    answer = next(a for a in answers if a["answer_text"] == "주 3회 저녁 6시부터 10시까지 일했어요")
    assert answer["category_label"] == "편의점 알바"
    assert answer["category_type"] == "part_time"
    assert answer["question_source"] == "base"
    assert answer["session_id"] == session_id
    # 카테고리 끝 확인에서 확정된 사실이 그 답변 행에 스냅샷으로 남는다.
    assert [f["content"] for f in answer["confirmed_facts"]] == ["주 3회 저녁 6시부터 10시까지 일했어요"]


def test_answer_without_confirm_is_archived_with_no_facts(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, session_id, "답만 하고 확인은 안 눌렀어요", confirm=False)

    answers = session_client.get("/api/v1/me/answers", headers=headers).json()
    assert len(answers) == 1
    assert answers[0]["confirmed_facts"] == []

    confirmed_only = session_client.get("/api/v1/me/answers?confirmed_only=true", headers=headers).json()
    assert confirmed_only == []


def test_archive_survives_deleting_the_session(session_client):
    """계정에 쌓인다는 게 이 뜻이다 — confirmed_facts는 세션과 함께 CASCADE로
    사라지지만 문답 기록은 남는다(session_id만 NULL이 된다)."""
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, session_id, "세션이 지워져도 남을 답변")

    assert session_client.delete(f"/api/v1/sessions/{session_id}", headers=headers).status_code == 204

    answers = session_client.get("/api/v1/me/answers", headers=headers).json()
    assert len(answers) == 1
    assert answers[0]["session_id"] is None
    assert answers[0]["answer_text"] == "세션이 지워져도 남을 답변"


def test_exclude_session_id_keeps_orphaned_rows(session_client):
    """`!=`만 쓰면 session_id IS NULL인 행(원본 세션이 삭제된 기록)이 SQL의
    3값 논리 때문에 통째로 걸러진다."""
    headers = _register_and_login(session_client)
    old_session = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, old_session, "예전 세션 답변")
    session_client.delete(f"/api/v1/sessions/{old_session}", headers=headers)

    new_session = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, new_session, "지금 세션 답변")

    answers = session_client.get(
        f"/api/v1/me/answers?exclude_session_id={new_session}", headers=headers
    ).json()
    assert [a["answer_text"] for a in answers] == ["예전 세션 답변"]


def test_archive_is_scoped_to_the_account(session_client):
    alice_headers = _register_and_login(session_client, email="alice@example.com")
    alice_session = _session_at_interviewing(session_client, alice_headers)
    _answer_one_turn(session_client, alice_headers, alice_session, "앨리스의 답변")

    bob_headers = _register_and_login(session_client, email="bob@example.com")
    assert session_client.get("/api/v1/me/answers", headers=bob_headers).json() == []


def test_summary_counts_answers_and_facts(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, session_id, "첫 번째 답변")
    _answer_one_turn(session_client, headers, session_id, "두 번째 답변")

    # 확인 전: 답은 쌓였지만 확정된 사실은 없다.
    body = session_client.get("/api/v1/me/answers/summary", headers=headers).json()
    assert body["total_answers"] == 2
    assert body["total_confirmed_facts"] == 0
    assert body["category_types"] == ["part_time"]

    # 카테고리 끝 확인 뒤: 모든 답의 사실이 스냅샷으로 들어온다.
    _answer_one_turn(session_client, headers, session_id, "세 번째 답변", confirm=True)
    body = session_client.get("/api/v1/me/answers/summary", headers=headers).json()
    assert body["total_confirmed_facts"] == body["total_answers"]


def test_archived_answer_can_be_deleted(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, session_id, "지워질 답변")

    answer_id = session_client.get("/api/v1/me/answers", headers=headers).json()[0]["id"]
    assert session_client.delete(f"/api/v1/me/answers/{answer_id}", headers=headers).status_code == 204
    assert session_client.get("/api/v1/me/answers", headers=headers).json() == []


def test_another_user_cannot_delete_an_archived_answer(session_client):
    alice_headers = _register_and_login(session_client, email="alice@example.com")
    alice_session = _session_at_interviewing(session_client, alice_headers)
    _answer_one_turn(session_client, alice_headers, alice_session, "앨리스의 답변")
    answer_id = session_client.get("/api/v1/me/answers", headers=alice_headers).json()[0]["id"]

    bob_headers = _register_and_login(session_client, email="bob@example.com")
    resp = session_client.delete(f"/api/v1/me/answers/{answer_id}", headers=bob_headers)
    assert resp.status_code == 404


def test_reset_answers_clears_the_whole_archive_and_returns_the_count(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, session_id, "첫 번째 답변")
    _answer_one_turn(session_client, headers, session_id, "두 번째 답변")

    resp = session_client.post("/api/v1/me/answers/reset", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["reset_count"] == 2

    assert session_client.get("/api/v1/me/answers", headers=headers).json() == []


def test_reset_answers_also_clears_attributes_inferred_from_those_answers(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, session_id, "수원에 살고 26살이에요")

    # fake_extractor는 백그라운드 태스크로 등록만 되고 즉시 실행되진 않으므로,
    # 실제 추정 속성 하나를 직접 만들어 답변에 연결한다(forget_answer가 지우는 대상).
    answer_id = session_client.get("/api/v1/me/answers", headers=headers).json()[0]["id"]
    user_id = session_client.get("/api/v1/auth/me", headers=headers).json()["id"]

    async def _add_inferred():
        async with session_client.session_local() as db:
            db.add(
                UserAttribute(
                    user_id=uuid.UUID(user_id),
                    key="residence_region",
                    value={"label": "수원"},
                    value_norm="수원",
                    status="inferred",
                    sensitive=False,
                    source_kind="interview_answer",
                    source_answer_id=uuid.UUID(answer_id),
                    evidence_text="수원에 살고 26살이에요",
                )
            )
            await db.commit()

    asyncio.run(_add_inferred())
    assert len(session_client.get("/api/v1/me/attributes", headers=headers).json()["attributes"]) == 1

    session_client.post("/api/v1/me/answers/reset", headers=headers)
    assert session_client.get("/api/v1/me/attributes", headers=headers).json()["attributes"] == []


def test_another_user_cannot_be_affected_by_reset_answers(session_client):
    alice_headers = _register_and_login(session_client, email="alice-reset2@example.com")
    bob_headers = _register_and_login(session_client, email="bob-reset2@example.com")
    alice_session = _session_at_interviewing(session_client, alice_headers)
    bob_session = _session_at_interviewing(session_client, bob_headers)
    _answer_one_turn(session_client, alice_headers, alice_session, "앨리스의 답변")
    _answer_one_turn(session_client, bob_headers, bob_session, "밥의 답변")

    resp = session_client.post("/api/v1/me/answers/reset", headers=alice_headers)
    assert resp.json()["reset_count"] == 1

    assert session_client.get("/api/v1/me/answers", headers=alice_headers).json() == []
    assert len(session_client.get("/api/v1/me/answers", headers=bob_headers).json()) == 1


def test_guest_cannot_read_the_archive_but_keeps_it_on_upgrade(session_client):
    """게스트 세션에서 남긴 문답도 같은 user 행에 저장되므로, 이메일로
    회원가입해 승격되는 순간 그대로 보인다."""
    guest = session_client.post("/api/v1/auth/guest").json()
    guest_headers = {"Authorization": f"Bearer {guest['access_token']}"}

    session_id = _session_at_interviewing(session_client, guest_headers)
    _answer_one_turn(session_client, guest_headers, session_id, "게스트로 남긴 답변")

    resp = session_client.get("/api/v1/me/answers", headers=guest_headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "registered_account_required"

    session_client.post(
        "/api/v1/auth/register",
        headers=guest_headers,
        json={"email": "upgraded@example.com", "password": "password123", "nickname": "Up"},
    )
    resp = session_client.post(
        "/api/v1/auth/login", json={"email": "upgraded@example.com", "password": "password123"}
    )
    upgraded_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    answers = session_client.get("/api/v1/me/answers", headers=upgraded_headers).json()
    assert [a["answer_text"] for a in answers] == ["게스트로 남긴 답변"]


def test_archive_requires_authentication(session_client):
    assert session_client.get("/api/v1/me/answers").status_code == 401
