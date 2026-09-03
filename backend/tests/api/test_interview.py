from __future__ import annotations

import uuid

from app.services.llm.base import BasedOn, RecordExcerpt, Suggestion


def _register_and_login(client, email="alice@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "nickname": "Alice"},
    )
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_session(client, headers):
    resp = client.post("/api/v1/sessions", headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


def _advance_to_first_category(client, headers, session_id, category_types=("part_time",)):
    resp = client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CATEGORY_SELECT"

    resp = client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers,
        json={"categories": [{"category_type": t} for t in category_types]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "RECORD_UPLOAD"

    resp = client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "FREQ_DRAFT"
    return resp.json()["current_category_id"]


def _do_confirm_round(client, headers, session_id, draft_step, confirm_step, final_text="답변입니다", was_edited=False):
    resp = client.get(f"/api/v1/sessions/{session_id}/interview/next", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["step"] == draft_step

    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"step": confirm_step, "final_text": final_text, "was_edited": was_edited},
    )
    assert resp.status_code == 200
    return resp.json()


def test_full_category_round_creates_three_confirmed_facts(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    _do_confirm_round(session_client, headers, session_id, "FREQ_DRAFT", "FREQ_CONFIRM")
    _do_confirm_round(session_client, headers, session_id, "TASK_DRAFT", "TASK_CONFIRM")
    result = _do_confirm_round(session_client, headers, session_id, "ACHIEVEMENT_DRAFT", "ACHIEVEMENT_CONFIRM")

    assert result["status"] == "RESULT_GENERATE"
    assert result["current_category_id"] is None

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert len(ctx["confirmed_facts"]) == 3
    assert {f["fact_type"] for f in ctx["confirmed_facts"]} == {"frequency", "task", "achievement"}


def test_two_categories_second_starts_at_freq_draft(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time", "study"))

    _do_confirm_round(session_client, headers, session_id, "FREQ_DRAFT", "FREQ_CONFIRM")
    _do_confirm_round(session_client, headers, session_id, "TASK_DRAFT", "TASK_CONFIRM")
    result = _do_confirm_round(session_client, headers, session_id, "ACHIEVEMENT_DRAFT", "ACHIEVEMENT_CONFIRM")

    assert result["status"] == "FREQ_DRAFT"
    assert result["current_category_id"] is not None

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["current_category"]["category_type"] == "study"
    part_time = next(c for c in ctx["categories"] if c["category_type"] == "part_time")
    assert part_time["status"] == "DONE"


def test_confirm_before_any_draft_returns_409(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"step": "FREQ_CONFIRM", "final_text": "x", "was_edited": False},
    )
    assert resp.status_code == 409


def test_interview_next_before_period_returns_409(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)

    resp = session_client.get(f"/api/v1/sessions/{session_id}/interview/next", headers=headers)
    assert resp.status_code == 409


def test_confirm_step_mismatch_returns_409(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    session_client.get(f"/api/v1/sessions/{session_id}/interview/next", headers=headers)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"step": "TASK_CONFIRM", "final_text": "x", "was_edited": False},
    )
    assert resp.status_code == 409


def test_other_users_session_returns_403_on_every_endpoint(session_client):
    headers_a = _register_and_login(session_client, email="a@example.com")
    session_id = _create_session(session_client, headers_a)
    _advance_to_first_category(session_client, headers_a, session_id)

    headers_b = _register_and_login(session_client, email="b@example.com")

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers_b,
        json={"start_date": "2025-01-01", "end_date": "2025-02-01"},
    )
    assert resp.status_code == 403

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers_b,
        json={"categories": [{"category_type": "study"}]},
    )
    assert resp.status_code == 403

    resp = session_client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers_b)
    assert resp.status_code == 403

    resp = session_client.get(f"/api/v1/sessions/{session_id}/interview/next", headers=headers_b)
    assert resp.status_code == 403

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers_b,
        json={"step": "FREQ_CONFIRM", "final_text": "x", "was_edited": False},
    )
    assert resp.status_code == 403

    resp = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers_b)
    assert resp.status_code == 403

    resp = session_client.delete(f"/api/v1/sessions/{session_id}", headers=headers_b)
    assert resp.status_code == 403


def test_was_edited_true_sets_source_type_user_edited(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    _do_confirm_round(session_client, headers, session_id, "FREQ_DRAFT", "FREQ_CONFIRM", was_edited=True)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"][0]["source_type"] == "user_edited"


def test_record_based_draft_confirmed_unedited_is_record_cited(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    # Must contain a non-digit hex character - an all-digit UUID string gets
    # silently mangled by SQLite's NUMERIC column-affinity conversion (the
    # postgresql.UUID DDL type name doesn't match any of SQLite's affinity
    # keywords, so it falls back to NUMERIC). Real Postgres has no such issue.
    chunk_id = str(uuid.uuid4())
    session_client.fake_llm._queue = [
        Suggestion(
            draft_text="주 3회 카페 아르바이트를 했다",
            based_on=BasedOn(type="record", excerpts=[RecordExcerpt(chunk_id=chunk_id, text="근무 기록", published_at=None)]),
        )
    ]

    _do_confirm_round(session_client, headers, session_id, "FREQ_DRAFT", "FREQ_CONFIRM", was_edited=False)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"][0]["source_type"] == "record_cited"


def test_generic_pattern_draft_confirmed_unedited_is_user_confirmed(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    _do_confirm_round(session_client, headers, session_id, "FREQ_DRAFT", "FREQ_CONFIRM", was_edited=False)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"][0]["source_type"] == "user_confirmed"


def test_session_create_and_delete(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)

    resp = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "PERIOD_INPUT"

    resp = session_client.delete(f"/api/v1/sessions/{session_id}", headers=headers)
    assert resp.status_code == 204

    resp = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers)
    assert resp.status_code == 404
