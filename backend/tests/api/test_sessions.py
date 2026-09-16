from __future__ import annotations

import time


def _register_and_login(client, email="alice@example.com", password="password123", nickname="Alice"):
    client.post("/api/v1/auth/register", json={"email": email, "password": password, "nickname": nickname})
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()["access_token"]


def _guest_login(client):
    return client.post("/api/v1/auth/guest").json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_guest_can_create_one_session(session_client):
    token = _guest_login(session_client)

    resp = session_client.post("/api/v1/sessions", headers=_auth(token))

    assert resp.status_code == 201
    assert resp.json()["status"]


def test_guest_can_create_multiple_sessions(session_client):
    token = _guest_login(session_client)
    first = session_client.post("/api/v1/sessions", headers=_auth(token))

    second = session_client.post("/api/v1/sessions", headers=_auth(token))

    assert first.status_code == 201
    assert second.status_code == 201


def test_registered_user_can_create_multiple_sessions(session_client):
    token = _register_and_login(session_client)

    first = session_client.post("/api/v1/sessions", headers=_auth(token))
    second = session_client.post("/api/v1/sessions", headers=_auth(token))

    assert first.status_code == 201
    assert second.status_code == 201


def test_list_sessions_returns_own_sessions_newest_first(session_client):
    token = _register_and_login(session_client)
    first = session_client.post("/api/v1/sessions", headers=_auth(token)).json()
    # created_at uses func.now(), which SQLite (unlike Postgres) only resolves
    # to whole seconds — without this the two rows can tie and sort arbitrarily.
    time.sleep(1.1)
    second = session_client.post("/api/v1/sessions", headers=_auth(token)).json()

    resp = session_client.get("/api/v1/sessions", headers=_auth(token))

    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert ids == [second["id"], first["id"]]


def test_list_sessions_excludes_other_users_sessions(session_client):
    token_a = _register_and_login(session_client, email="alice@example.com", nickname="Alice")
    token_b = _register_and_login(session_client, email="bob@example.com", nickname="Bob")
    session_client.post("/api/v1/sessions", headers=_auth(token_a))

    resp = session_client.get("/api/v1/sessions", headers=_auth(token_b))

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_sessions_requires_authentication(session_client):
    resp = session_client.get("/api/v1/sessions")

    assert resp.status_code == 401


def test_rename_session_sets_title(session_client):
    token = _register_and_login(session_client)
    session_id = session_client.post("/api/v1/sessions", headers=_auth(token)).json()["id"]

    resp = session_client.patch(f"/api/v1/sessions/{session_id}", headers=_auth(token), json={"title": "이직 준비 공백기"})

    assert resp.status_code == 200
    assert resp.json()["title"] == "이직 준비 공백기"


def test_rename_session_blank_title_clears_it(session_client):
    token = _register_and_login(session_client)
    session_id = session_client.post("/api/v1/sessions", headers=_auth(token)).json()["id"]
    session_client.patch(f"/api/v1/sessions/{session_id}", headers=_auth(token), json={"title": "임시 이름"})

    resp = session_client.patch(f"/api/v1/sessions/{session_id}", headers=_auth(token), json={"title": "   "})

    assert resp.status_code == 200
    assert resp.json()["title"] is None


def test_rename_other_users_session_returns_403(session_client):
    token_a = _register_and_login(session_client, email="alice@example.com", nickname="Alice")
    token_b = _register_and_login(session_client, email="bob@example.com", nickname="Bob")
    session_id = session_client.post("/api/v1/sessions", headers=_auth(token_a)).json()["id"]

    resp = session_client.patch(f"/api/v1/sessions/{session_id}", headers=_auth(token_b), json={"title": "가로채기"})

    assert resp.status_code == 403


def test_delete_session_removes_it_from_list(session_client):
    token = _register_and_login(session_client)
    session_id = session_client.post("/api/v1/sessions", headers=_auth(token)).json()["id"]

    resp = session_client.delete(f"/api/v1/sessions/{session_id}", headers=_auth(token))

    assert resp.status_code == 204
    listed = session_client.get("/api/v1/sessions", headers=_auth(token)).json()
    assert listed == []


def test_delete_other_users_session_returns_403(session_client):
    token_a = _register_and_login(session_client, email="alice@example.com", nickname="Alice")
    token_b = _register_and_login(session_client, email="bob@example.com", nickname="Bob")
    session_id = session_client.post("/api/v1/sessions", headers=_auth(token_a)).json()["id"]

    resp = session_client.delete(f"/api/v1/sessions/{session_id}", headers=_auth(token_b))

    assert resp.status_code == 403
    still_listed = session_client.get("/api/v1/sessions", headers=_auth(token_a)).json()
    assert len(still_listed) == 1


def test_bulk_delete_removes_all_specified_sessions(session_client):
    token = _register_and_login(session_client)
    first_id = session_client.post("/api/v1/sessions", headers=_auth(token)).json()["id"]
    second_id = session_client.post("/api/v1/sessions", headers=_auth(token)).json()["id"]

    resp = session_client.post(
        "/api/v1/sessions/bulk-delete", headers=_auth(token), json={"session_ids": [first_id, second_id]}
    )

    assert resp.status_code == 200
    assert set(resp.json()["deleted_ids"]) == {first_id, second_id}
    listed = session_client.get("/api/v1/sessions", headers=_auth(token)).json()
    assert listed == []


def test_bulk_delete_ignores_other_users_sessions(session_client):
    token_a = _register_and_login(session_client, email="alice@example.com", nickname="Alice")
    token_b = _register_and_login(session_client, email="bob@example.com", nickname="Bob")
    alice_session_id = session_client.post("/api/v1/sessions", headers=_auth(token_a)).json()["id"]
    bob_session_id = session_client.post("/api/v1/sessions", headers=_auth(token_b)).json()["id"]

    resp = session_client.post(
        "/api/v1/sessions/bulk-delete",
        headers=_auth(token_b),
        json={"session_ids": [alice_session_id, bob_session_id]},
    )

    assert resp.status_code == 200
    assert resp.json()["deleted_ids"] == [bob_session_id]
    still_listed = session_client.get("/api/v1/sessions", headers=_auth(token_a)).json()
    assert len(still_listed) == 1


def test_bulk_delete_ignores_nonexistent_ids(session_client):
    token = _register_and_login(session_client)

    resp = session_client.post(
        "/api/v1/sessions/bulk-delete",
        headers=_auth(token),
        json={"session_ids": ["00000000-0000-0000-0000-000000000000"]},
    )

    assert resp.status_code == 200
    assert resp.json()["deleted_ids"] == []


def test_bulk_delete_empty_list_returns_empty(session_client):
    token = _register_and_login(session_client)

    resp = session_client.post("/api/v1/sessions/bulk-delete", headers=_auth(token), json={"session_ids": []})

    assert resp.status_code == 200
    assert resp.json()["deleted_ids"] == []


def test_bulk_delete_requires_authentication(session_client):
    resp = session_client.post("/api/v1/sessions/bulk-delete", json={"session_ids": []})

    assert resp.status_code == 401
