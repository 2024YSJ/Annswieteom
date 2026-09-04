from __future__ import annotations

from app.services.llm.fallback import get_llm_provider
from app.main import app
from app.services.llm.base import AllProvidersFailedError


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
    return resp.json()["id"]  # PERIOD_INPUT


def test_extract_period_returns_dates_without_persisting(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/period/extract",
        headers=headers,
        json={"text": "작년 1월부터 6월까지요"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["start_date"] == "2025-01-01"
    assert body["end_date"] == "2025-06-30"
    assert session_client.fake_llm.period_calls == ["작년 1월부터 6월까지요"]

    # Nothing was persisted — GET /sessions/{id} shows no gap_period yet.
    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["gap_period"] is None
    assert ctx["status"] == "PERIOD_INPUT"


def test_extract_period_requires_period_input_status(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    session_client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )  # now CATEGORY_SELECT

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/period/extract",
        headers=headers,
        json={"text": "아무 내용"},
    )

    assert resp.status_code == 409


def test_extract_period_returns_503_when_all_providers_fail(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)

    class FailingLLMProvider:
        async def extract_period(self, free_text, today):
            raise AllProvidersFailedError()

    app.dependency_overrides[get_llm_provider] = lambda: FailingLLMProvider()
    try:
        resp = session_client.post(
            f"/api/v1/sessions/{session_id}/period/extract",
            headers=headers,
            json={"text": "아무 내용"},
        )
    finally:
        app.dependency_overrides[get_llm_provider] = lambda: session_client.fake_llm

    assert resp.status_code == 503
    assert resp.json()["detail"] == "llm_unavailable"


def test_extract_period_returns_null_dates_when_unparseable(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)

    class UncertainLLMProvider:
        async def extract_period(self, free_text, today):
            return None

    app.dependency_overrides[get_llm_provider] = lambda: UncertainLLMProvider()
    try:
        resp = session_client.post(
            f"/api/v1/sessions/{session_id}/period/extract",
            headers=headers,
            json={"text": "그냥 쉬었어요"},
        )
    finally:
        app.dependency_overrides[get_llm_provider] = lambda: session_client.fake_llm

    assert resp.status_code == 200
    body = resp.json()
    assert body["start_date"] is None
    assert body["end_date"] is None
