from __future__ import annotations

from app.main import app
from app.services.llm.base import JobPreferenceInferenceResult
from app.services.llm.fallback import get_llm_provider
from tests.api.conftest import FakeLLMProvider


def _register_and_login(client, email="alice@example.com", password="password123", nickname="Alice"):
    client.post("/api/v1/auth/register", json={"email": email, "password": password, "nickname": nickname})
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_seed_requires_a_linked_session(session_client):
    token = _register_and_login(session_client)
    job_session = session_client.post(
        "/api/v1/sessions", json={"kind": "job_search"}, headers=_auth(token)
    ).json()

    resp = session_client.post(
        f"/api/v1/sessions/{job_session['id']}/job-search/seed-from-gap", headers=_auth(token)
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_linked_gap_session"


def test_create_rejects_linking_another_users_session(session_client):
    token_a = _register_and_login(session_client, "alice@example.com", nickname="Alice")
    gap_session_a = session_client.post("/api/v1/sessions", headers=_auth(token_a)).json()

    token_b = _register_and_login(session_client, "bob@example.com", nickname="Bob")
    resp = session_client.post(
        "/api/v1/sessions",
        json={"kind": "job_search", "linked_gap_session_id": gap_session_a["id"]},
        headers=_auth(token_b),
    )

    assert resp.status_code == 404


def test_seed_infers_preferences_from_linked_sessions_confirmed_facts(session_client):
    token = _register_and_login(session_client)
    gap_session = session_client.post("/api/v1/sessions", headers=_auth(token)).json()

    job_session = session_client.post(
        "/api/v1/sessions",
        json={"kind": "job_search", "linked_gap_session_id": gap_session["id"]},
        headers=_auth(token),
    ).json()
    assert job_session["linked_gap_session_id"] == gap_session["id"]

    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider(
        job_preference_inference=JobPreferenceInferenceResult(
            work_style_tags=["협업 중시"], keyword_hints=["마케팅"], notes="팀 프로젝트 경험이 많아요"
        )
    )

    resp = session_client.post(
        f"/api/v1/sessions/{job_session['id']}/job-search/seed-from-gap", headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["work_style_tags"] == ["협업 중시"]
    assert body["keyword_hints"] == ["마케팅"]
    assert "salary_min" not in body
    assert "location" not in body


def test_seed_does_not_persist_anything(session_client):
    """seed는 제안만 반환한다 — 확정하려면 사용자가 여전히
    POST /job-search/preferences를 직접 호출해야 한다(정직성 가드레일과
    동일한 원칙, 카테고리/기간 extract와 동일 패턴)."""
    token = _register_and_login(session_client)
    gap_session = session_client.post("/api/v1/sessions", headers=_auth(token)).json()
    job_session = session_client.post(
        "/api/v1/sessions",
        json={"kind": "job_search", "linked_gap_session_id": gap_session["id"]},
        headers=_auth(token),
    ).json()

    session_client.post(f"/api/v1/sessions/{job_session['id']}/job-search/seed-from-gap", headers=_auth(token))

    state = session_client.get(f"/api/v1/sessions/{job_session['id']}/job-search", headers=_auth(token)).json()
    assert state["status"] == "JOB_PREFERENCES_INPUT"
    assert state["preferences"] is None
