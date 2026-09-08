from __future__ import annotations

from app.main import app
from app.services.job_pipeline.job_info_client import JobInfoResult, WorknetApiError, get_job_info_client
from app.services.llm.base import JobInfoCategoryQuery
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
    # 더 이상 단계 전이가 없는 상시 대화형 세션이라 생성 즉시 활성 상태다.
    assert body["status"] == "JOB_SEARCHING"
    return body["id"]


class FakeJobInfoClient:
    def __init__(self, results_by_category: dict[str, list[JobInfoResult]] | None = None, failing_categories: set[str] | None = None):
        self._results_by_category = results_by_category or {}
        self._failing_categories = failing_categories or set()
        self.search_calls: list[tuple[str, list[str]]] = []

    async def search(self, category: str, keywords: list[str]) -> list[JobInfoResult]:
        self.search_calls.append((category, keywords))
        if category in self._failing_categories:
            raise WorknetApiError(category, "테스트용 오류")
        return self._results_by_category.get(category, [])


def _override_job_info_client(**kwargs):
    fake_client = FakeJobInfoClient(**kwargs)
    app.dependency_overrides[get_job_info_client] = lambda: fake_client
    return fake_client


def test_query_requires_job_search_kind(session_client):
    token = _register_and_login(session_client)
    resp = session_client.post("/api/v1/sessions", json={"kind": "gap_fill"}, headers=_auth(token))
    gap_session_id = resp.json()["id"]
    _override_job_info_client()
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider()

    resp = session_client.post(
        f"/api/v1/sessions/{gap_session_id}/job-search/query", json={"query": "채용행사 있어?"}, headers=_auth(token)
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "not_a_job_search_session"


def test_query_with_no_matching_category_returns_clarification(session_client):
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    _override_job_info_client()
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider(job_info_categories=[])

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "음..."}, headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["categories"] == []
    assert body["clarification_question"] is not None
    assert "채용행사" in body["clarification_question"]


def test_query_spanning_multiple_categories_returns_all_of_them(session_client):
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    fake_client = _override_job_info_client(
        results_by_category={
            "training_course": [JobInfoResult(title="백엔드 부트캠프", subtitle="국민내일배움카드", meta_lines=[])],
            "promising_sme": [JobInfoResult(title="주식회사 테스트", subtitle="제조업", meta_lines=["지역: 서울"])],
        }
    )
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider(
        job_info_categories=[
            JobInfoCategoryQuery(category="training_course", keywords=["백엔드"]),
            JobInfoCategoryQuery(category="promising_sme", keywords=[]),
        ]
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query",
        json={"query": "이직 준비하는데 도움될 거 있어?"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["clarification_question"] is None
    categories = {c["category"]: c for c in body["categories"]}
    assert set(categories) == {"training_course", "promising_sme"}
    assert categories["training_course"]["category_label"] == "직업훈련과정"
    assert categories["training_course"]["results"][0]["title"] == "백엔드 부트캠프"
    assert categories["promising_sme"]["results"][0]["meta_lines"] == ["지역: 서울"]
    assert fake_client.search_calls == [("training_course", ["백엔드"]), ("promising_sme", [])]


def test_query_drops_only_the_category_that_fails(session_client):
    # 워크넷 오류(예: 승인 대기 중인 카테고리)는 해당 카테고리만 결과에서
    # 빠지고 나머지는 그대로 보여야 한다 — 질문 전체가 실패로 보이면 안 된다.
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    _override_job_info_client(
        results_by_category={"job_fair": [JobInfoResult(title="취업박람회", subtitle="서울", meta_lines=[])]},
        failing_categories={"training_course"},
    )
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider(
        job_info_categories=[
            JobInfoCategoryQuery(category="job_fair", keywords=[]),
            JobInfoCategoryQuery(category="training_course", keywords=[]),
        ]
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "채용행사랑 훈련과정 알려줘"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert [c["category"] for c in body["categories"]] == ["job_fair"]


def test_query_empty_results_for_a_category_still_shown(session_client):
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    _override_job_info_client(results_by_category={})
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider(
        job_info_categories=[JobInfoCategoryQuery(category="job_fair", keywords=["부산"])]
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "부산 채용행사 있어?"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["categories"][0]["category"] == "job_fair"
    assert body["categories"][0]["results"] == []


def test_draft_query_requires_a_linked_session(session_client):
    token = _register_and_login(session_client)
    job_session_id = _create_job_search_session(session_client, token)

    resp = session_client.post(
        f"/api/v1/sessions/{job_session_id}/job-search/draft-query-from-gap", headers=_auth(token)
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_linked_gap_session"


def test_draft_query_rejects_a_linked_session_owned_by_another_user(session_client):
    token_a = _register_and_login(session_client, "alice@example.com", nickname="Alice")
    gap_session_a = session_client.post("/api/v1/sessions", headers=_auth(token_a)).json()

    token_b = _register_and_login(session_client, "bob@example.com", nickname="Bob")
    resp = session_client.post(
        "/api/v1/sessions",
        json={"kind": "job_search", "linked_gap_session_id": gap_session_a["id"]},
        headers=_auth(token_b),
    )

    # linked_gap_session_id 자체가 다른 사용자 소유라 세션 생성 시점에 이미
    # 거부된다(app/api/sessions.py) — draft-query까지 갈 필요도 없다.
    assert resp.status_code == 404


def test_draft_query_returns_llms_suggestion_without_persisting_anything(session_client):
    token = _register_and_login(session_client)
    gap_session = session_client.post("/api/v1/sessions", headers=_auth(token)).json()
    job_session = session_client.post(
        "/api/v1/sessions",
        json={"kind": "job_search", "linked_gap_session_id": gap_session["id"]},
        headers=_auth(token),
    ).json()

    fake_llm = FakeLLMProvider(draft_job_info_query="카페 아르바이트 경험이 있는데 관련 직업훈련과정 알려줘")
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm

    resp = session_client.post(
        f"/api/v1/sessions/{job_session['id']}/job-search/draft-query-from-gap", headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["draft_query"] == "카페 아르바이트 경험이 있는데 관련 직업훈련과정 알려줘"
    assert len(fake_llm.draft_job_info_query_calls) == 1
