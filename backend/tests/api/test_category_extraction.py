from __future__ import annotations

from app.api.interview import get_llm_provider
from app.main import app
from app.services.llm.base import AllProvidersFailedError, CategorySuggestion


def _register_and_login(client, email="alice@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "nickname": "Alice"},
    )
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_session_at_category_select(client, headers):
    resp = client.post("/api/v1/sessions", headers=headers)
    session_id = resp.json()["id"]
    resp = client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    assert resp.json()["status"] == "CATEGORY_SELECT"
    return session_id


def test_extract_categories_returns_suggestions_without_persisting(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session_at_category_select(session_client, headers)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/categories/extract",
        headers=headers,
        json={"text": "편의점에서 6개월 정도 알바했어요"},
    )

    assert resp.status_code == 200
    suggestions = resp.json()["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["category_type"] == "part_time"
    assert suggestions[0]["custom_label"]
    assert session_client.fake_llm.extract_calls == ["편의점에서 6개월 정도 알바했어요"]

    # Nothing was persisted — GET /sessions/{id} shows no categories yet.
    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["categories"] == []
    assert ctx["status"] == "CATEGORY_SELECT"


def test_extract_categories_requires_category_select_status(session_client):
    headers = _register_and_login(session_client)
    resp = session_client.post("/api/v1/sessions", headers=headers)
    session_id = resp.json()["id"]  # still PERIOD_INPUT

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/categories/extract",
        headers=headers,
        json={"text": "아무 내용"},
    )

    assert resp.status_code == 409


def test_extract_categories_returns_503_when_all_providers_fail(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session_at_category_select(session_client, headers)

    class FailingLLMProvider:
        async def extract_categories(self, free_text, gap_start, gap_end):
            raise AllProvidersFailedError()

    app.dependency_overrides[get_llm_provider] = lambda: FailingLLMProvider()
    try:
        resp = session_client.post(
            f"/api/v1/sessions/{session_id}/categories/extract",
            headers=headers,
            json={"text": "아무 내용"},
        )
    finally:
        app.dependency_overrides[get_llm_provider] = lambda: session_client.fake_llm

    assert resp.status_code == 503
    assert resp.json()["detail"] == "llm_unavailable"


def test_select_categories_persists_custom_label(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session_at_category_select(session_client, headers)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers,
        json={"categories": [{"category_type": "part_time", "custom_label": "편의점 아르바이트"}]},
    )
    assert resp.status_code == 200

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["categories"][0]["custom_label"] == "편의점 아르바이트"
