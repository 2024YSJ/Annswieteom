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


def test_guest_second_session_returns_409(session_client):
    token = _guest_login(session_client)
    session_client.post("/api/v1/sessions", headers=_auth(token))

    resp = session_client.post("/api/v1/sessions", headers=_auth(token))

    assert resp.status_code == 409
    assert resp.json()["detail"] == "guest_session_limit_reached"


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
