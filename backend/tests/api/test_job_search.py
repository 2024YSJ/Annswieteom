from __future__ import annotations

from app.main import app
from app.services.job_pipeline.worknet_client import get_job_search_client
from app.services.llm.base import JobFitResult, JobPosting, JobPreferences
from app.services.llm.fallback import get_llm_provider
from tests.api.conftest import FakeLLMProvider


def _register_and_login(client, email="alice@example.com", password="password123", nickname="Alice"):
    client.post("/api/v1/auth/register", json={"email": email, "password": password, "nickname": nickname})
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_job_search_session(client, token):
    resp = client.post("/api/v1/sessions", json={"kind": "job_search"}, headers=_auth(token))
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "job_search"
    assert body["status"] == "JOB_PREFERENCES_INPUT"
    return body["id"]


class FakeJobSearchClient:
    def __init__(self, postings: list[JobPosting] | None = None):
        self._postings = postings if postings is not None else [
            JobPosting(
                source="worknet", external_id="K1", title="백엔드 개발자", company="테스트회사",
                salary_text="연봉 3500", location="서울", education_requirement="학력무관",
                career_requirement="경력무관", work_type="정규직", url="https://work24.go.kr/1",
            ),
            JobPosting(
                source="worknet", external_id="K2", title="프론트엔드 개발자", company="다른회사",
                salary_text="연봉 5000", location="부산", education_requirement="대졸",
                career_requirement="3년 이상", work_type="정규직", url="https://work24.go.kr/2",
            ),
        ]
        self.search_calls: list[JobPreferences] = []

    async def search(self, preferences: JobPreferences, limit: int = 15) -> list[JobPosting]:
        self.search_calls.append(preferences)
        return self._postings[:limit]


def _override_job_client(postings=None):
    fake_client = FakeJobSearchClient(postings)
    app.dependency_overrides[get_job_search_client] = lambda: fake_client
    return fake_client


def test_job_search_session_starts_in_preferences_input(session_client):
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)

    resp = session_client.get(f"/api/v1/sessions/{session_id}/job-search", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "JOB_PREFERENCES_INPUT"
    assert body["preferences"] is None
    assert body["results"] == []


def test_extract_preferences_does_not_persist_anything(session_client):
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/preferences/extract",
        json={"text": "재택 가능한 곳이면 좋겠어요, 서울에서 일하고 싶어요"},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    state = session_client.get(f"/api/v1/sessions/{session_id}/job-search", headers=_auth(token)).json()
    assert state["status"] == "JOB_PREFERENCES_INPUT"
    assert state["preferences"] is None


def test_confirm_preferences_persists_and_advances_status(session_client):
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/preferences",
        json={
            "salary_min": 3000,
            "salary_max": 4000,
            "location": "서울",
            "education_level": "학력무관",
            "career_years": 1,
            "work_style_tags": ["재택 가능", "유연근무"],
        },
        headers=_auth(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "JOB_SEARCHING"
    assert body["preferences"]["work_style_tags"] == ["재택 가능", "유연근무"]
    assert body["preferences"]["salary_min"] == 3000


def test_confirm_preferences_add_edit_delete_tags_before_search(session_client):
    """확인 단계에서 태그를 자유롭게 추가/삭제/수정한 최종 값이 그대로
    저장되는지 — CategorySection의 로컬 편집 패턴과 동일한 자유도를 서버가
    막지 않는지 확인한다."""
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)

    session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/preferences",
        json={"work_style_tags": ["재택 가능"]},
        headers=_auth(token),
    )

    # 사용자가 태그 하나 삭제하고, 하나 수정하고, 새 태그를 추가한 뒤 다시 확정
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/preferences",
        json={"work_style_tags": ["재택 가능(주3일)", "빠른 성장"]},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert resp.json()["preferences"]["work_style_tags"] == ["재택 가능(주3일)", "빠른 성장"]


def test_search_requires_confirmed_preferences(session_client):
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    _override_job_client()

    resp = session_client.post(f"/api/v1/sessions/{session_id}/job-search/search", headers=_auth(token))

    assert resp.status_code == 409


def test_search_judges_fit_and_sorts_fit_first(session_client):
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/preferences",
        json={"location": "서울", "work_style_tags": []},
        headers=_auth(token),
    )
    fake_client = _override_job_client()

    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider(
        job_fit_results=[
            JobFitResult(fit=False, reason="근무지가 안 맞아요"),
            JobFitResult(fit=True, reason="조건에 맞습니다"),
        ]
    )

    resp = session_client.post(f"/api/v1/sessions/{session_id}/job-search/search", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "JOB_RESULTS_REVIEW"
    assert len(body["results"]) == 2
    assert body["results"][0]["fit"] is True
    assert body["results"][1]["fit"] is False
    assert fake_client.search_calls[0].location == "서울"


def test_get_state_after_search_returns_cached_results_without_calling_worknet_again(session_client):
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/preferences",
        json={"work_style_tags": []},
        headers=_auth(token),
    )
    fake_client = _override_job_client()
    session_client.post(f"/api/v1/sessions/{session_id}/job-search/search", headers=_auth(token))
    assert len(fake_client.search_calls) == 1

    resp = session_client.get(f"/api/v1/sessions/{session_id}/job-search", headers=_auth(token))

    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 2
    assert len(fake_client.search_calls) == 1  # unchanged — no re-fetch on GET


def test_extract_preferences_works_after_confirm_for_conversational_edits(session_client):
    """확정(JOB_SEARCHING) 이후에도 자유 텍스트로 조건을 다시 말하면 여전히
    해석해준다 — 더 이상 최초 1턴에서만 되는 게 아니다. 검색까지 마친
    JOB_RESULTS_REVIEW에서도 동일하게 허용돼야 한다."""
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/preferences",
        json={"location": "서울", "work_style_tags": []},
        headers=_auth(token),
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/preferences/extract",
        json={"text": "생각해보니 부산도 괜찮아요"},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    _override_job_client()
    session_client.post(f"/api/v1/sessions/{session_id}/job-search/search", headers=_auth(token))

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/preferences/extract",
        json={"text": "역시 재택도 필요해요"},
        headers=_auth(token),
    )
    assert resp.status_code == 200


def test_job_search_endpoints_reject_gap_fill_sessions(session_client):
    token = _register_and_login(session_client)
    gap_session = session_client.post("/api/v1/sessions", headers=_auth(token)).json()

    resp = session_client.get(f"/api/v1/sessions/{gap_session['id']}/job-search", headers=_auth(token))

    assert resp.status_code == 409
    assert resp.json()["detail"] == "not_a_job_search_session"
