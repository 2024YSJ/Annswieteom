from __future__ import annotations


def _register(client, email="alice@example.com", password="password123", nickname="Alice"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "nickname": nickname},
    )


def _login(client, email="alice@example.com", password="password123"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_register_returns_user_id(client):
    resp = _register(client)

    assert resp.status_code == 201
    assert "user_id" in resp.json()


def test_register_duplicate_email_returns_409(client):
    _register(client)

    resp = _register(client)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "email_already_exists"


def test_register_rejects_short_password(client):
    resp = _register(client, password="short")

    assert resp.status_code == 422


def test_login_returns_access_token_and_sets_refresh_cookie(client):
    _register(client)

    resp = _login(client)

    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert len(resp.json()["access_token"]) > 0
    assert "refresh_token" in resp.cookies


def test_login_wrong_password_returns_401(client):
    _register(client)

    resp = _login(client, password="wrong-password")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_credentials"


def test_login_unknown_email_returns_401(client):
    resp = _login(client, email="nobody@example.com")

    assert resp.status_code == 401


def test_me_returns_current_user_with_valid_token(client):
    _register(client)
    access_token = _login(client).json()["access_token"]

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})

    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"
    assert resp.json()["nickname"] == "Alice"


def test_me_without_token_returns_401(client):
    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 401


def test_me_with_garbage_token_returns_401(client):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})

    assert resp.status_code == 401


def test_refresh_issues_new_access_token(client):
    _register(client)
    _login(client)  # cookie jar on the TestClient now holds refresh_token

    resp = client.post("/api/v1/auth/refresh")

    assert resp.status_code == 200
    assert len(resp.json()["access_token"]) > 0


def test_refresh_without_cookie_returns_401(client):
    resp = client.post("/api/v1/auth/refresh")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_refresh_token"


def test_logout_revokes_refresh_token(client):
    _register(client)
    access_token = _login(client).json()["access_token"]
    old_refresh_token = client.cookies.get("refresh_token")

    logout_resp = client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert logout_resp.status_code == 204
    # logout clears the cookie client-side, so a plain follow-up request
    # would just be "missing" - explicitly resend the old token value to
    # verify it's actually revoked server-side, not just forgotten locally.
    assert "refresh_token" not in client.cookies

    refresh_resp = client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": old_refresh_token}
    )
    assert refresh_resp.status_code == 401
    assert refresh_resp.json()["detail"] == "invalid_refresh_token"


def test_logout_requires_authentication(client):
    resp = client.post("/api/v1/auth/logout")

    assert resp.status_code == 401
