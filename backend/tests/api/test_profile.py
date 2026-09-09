from __future__ import annotations


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


def _answer_one_turn(client, headers, session_id, text, confirm=True):
    client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": text}
    )
    assert resp.status_code == 200
    if not confirm:
        return
    client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [
            {"index": c["index"], "final_text": c["content"], "was_edited": False}
            for c in resp.json()["candidates"]
        ]},
    )


def test_answers_are_archived_with_the_users_own_wording(session_client):
    """추출된 사실 문장이 아니라 사용자가 실제로 타이핑한 원문이 남아야 한다 —
    2026-09-09 전까지 이 원문은 어디에도 저장되지 않고 사라졌다."""
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    _answer_one_turn(session_client, headers, session_id, "주 3회 저녁 6시부터 10시까지 일했어요")

    resp = session_client.get("/api/v1/me/answers", headers=headers)
    assert resp.status_code == 200
    answers = resp.json()
    assert len(answers) == 1
    assert answers[0]["answer_text"] == "주 3회 저녁 6시부터 10시까지 일했어요"
    assert answers[0]["category_label"] == "편의점 알바"
    assert answers[0]["category_type"] == "part_time"
    assert answers[0]["question_source"] == "base"
    assert answers[0]["session_id"] == session_id
    assert [f["content"] for f in answers[0]["confirmed_facts"]] == ["주 3회 저녁 6시부터 10시까지 일했어요"]


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

    body = session_client.get("/api/v1/me/answers/summary", headers=headers).json()
    assert body["total_answers"] == 2
    assert body["total_confirmed_facts"] == 2
    assert body["category_types"] == ["part_time"]


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
