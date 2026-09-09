from __future__ import annotations

from app.services.llm import get_llm_provider
from app.main import app
from app.services.llm.base import LLMUnavailableError, CategorySuggestion
from tests.api.conftest import FakeLLMProvider


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
            raise LLMUnavailableError()

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


def _override_llm(**kwargs):
    fake = FakeLLMProvider(**kwargs)
    app.dependency_overrides[get_llm_provider] = lambda: fake
    return fake


def test_empty_extraction_asks_a_followup_question(session_client):
    """"잘 모르겠어" 같은 답에 같은 질문을 되풀이하면 사용자는 똑같이 막힌다 —
    활동을 하나도 못 찾았을 때는 AI가 구체적인 갈래를 짚어 되묻는다."""
    headers = _register_and_login(session_client)
    session_id = _create_session_at_category_select(session_client, headers)

    fake = _override_llm(
        category_suggestions=[],
        probe_question="혹시 그동안 아르바이트나 단기 일은 하셨을까요?",
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/categories/extract",
        headers=headers,
        json={"text": "잘 모르겠어"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["suggestions"] == []
    assert body["followup_question"] == "혹시 그동안 아르바이트나 단기 일은 하셨을까요?"
    assert fake.probe_question_calls == ["잘 모르겠어"]


def test_followup_is_not_generated_when_activities_were_found(session_client):
    """정상 경로에는 LLM 호출이 늘지 않는다 — 되묻기는 빈 결과 전용이다."""
    headers = _register_and_login(session_client)
    session_id = _create_session_at_category_select(session_client, headers)

    fake = _override_llm(
        category_suggestions=[CategorySuggestion(category_type="part_time", custom_label="편의점 알바")],
        probe_question="이건 불려선 안 된다",
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/categories/extract",
        headers=headers,
        json={"text": "편의점에서 알바했어요"},
    )

    assert resp.status_code == 200
    assert resp.json()["followup_question"] is None
    assert fake.probe_question_calls == []


def test_followup_failure_degrades_instead_of_failing_the_request(session_client):
    """되묻기 생성이 실패해도 요청 전체를 실패시키지 않는다.

    Gemini 폴백을 제거한 뒤 로컬 Ollama가 유일한 경로라 터널이 끊기면 여기도
    같이 죽는데, 그때는 followup_question=null로 두고 프론트가 정적 예시
    안내로 돌아간다 — 사용자가 막다른 길에 갇히면 안 된다.
    """
    headers = _register_and_login(session_client)
    session_id = _create_session_at_category_select(session_client, headers)

    # probe_question을 안 주면 FakeLLMProvider가 LLMUnavailableError를 던진다.
    _override_llm(category_suggestions=[])

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/categories/extract",
        headers=headers,
        json={"text": "잘 모르겠어"},
    )

    assert resp.status_code == 200
    assert resp.json()["suggestions"] == []
    assert resp.json()["followup_question"] is None
