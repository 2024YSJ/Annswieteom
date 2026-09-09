from __future__ import annotations

from app.main import app
from app.services.job_pipeline.job_info_client import JobInfoResult, WorknetApiError, get_job_info_client
from app.services.llm.base import JobInfoCategoryQuery
from app.services.llm import get_llm_provider
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
        self.search_calls: list[str] = []
        self.search_params: list = []

    async def search(self, category: str, params=None) -> list[JobInfoResult]:
        self.search_calls.append(category)
        self.search_params.append(params)
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
            JobInfoCategoryQuery(category="training_course"),
            JobInfoCategoryQuery(category="promising_sme"),
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
    assert set(fake_client.search_calls) == {"training_course", "promising_sme"}


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
            JobInfoCategoryQuery(category="job_fair"),
            JobInfoCategoryQuery(category="training_course"),
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
        job_info_categories=[JobInfoCategoryQuery(category="job_fair")]
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "부산 채용행사 있어?"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["categories"][0]["category"] == "job_fair"
    assert body["categories"][0]["results"] == []


def test_query_only_shows_results_the_llm_judged_relevant(session_client):
    # 문자열 부분일치 대신 LLM이 실제로 관련 있는 항목만 고른다 — 워크넷이
    # 3건을 돌려줘도 LLM이 1건만 관련 있다고 판단하면 그 1건만 보여야 한다.
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    _override_job_info_client(
        results_by_category={
            "training_course": [
                JobInfoResult(title="백엔드 개발 부트캠프", subtitle="의정부", meta_lines=[]),
                JobInfoResult(title="조리사 자격증반", subtitle="의정부", meta_lines=[]),
                JobInfoResult(title="웹 개발 국비지원", subtitle="파주", meta_lines=[]),
            ]
        }
    )
    fake_llm = FakeLLMProvider(
        job_info_categories=[JobInfoCategoryQuery(category="training_course")],
        job_info_relevant_indices=[0, 2],  # 조리사 자격증반(1번)만 제외
    )
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query",
        json={"query": "나는 백엔드 개발자야. 경기 북부에서 일자리를 구하고 싶어."},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    titles = [r["title"] for r in body["categories"][0]["results"]]
    assert titles == ["백엔드 개발 부트캠프", "웹 개발 국비지원"]
    assert len(fake_llm.select_relevant_calls) == 1
    query, category_label, candidates = fake_llm.select_relevant_calls[0]
    assert query == "나는 백엔드 개발자야. 경기 북부에서 일자리를 구하고 싶어."
    assert category_label == "직업훈련과정"
    assert len(candidates) == 3


def test_query_drops_category_when_relevance_judgment_is_unavailable(session_client):
    from app.services.llm.base import LLMUnavailableError

    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    _override_job_info_client(
        results_by_category={"job_fair": [JobInfoResult(title="취업박람회", subtitle="서울", meta_lines=[])]}
    )

    class BrokenRelevanceLLM(FakeLLMProvider):
        async def select_relevant_job_info_results(self, query, category_label, candidates):
            raise LLMUnavailableError()

    app.dependency_overrides[get_llm_provider] = lambda: BrokenRelevanceLLM(
        job_info_categories=[JobInfoCategoryQuery(category="job_fair")]
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "채용행사 알려줘"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    # 원본 목록을 걸러지지 않은 채로 보여주느니, 그 카테고리를 빼는 쪽을 택한다.
    # 다만 조용히 버리지 않고 무엇이 빠졌는지는 알려준다.
    assert resp.json()["categories"] == []
    assert resp.json()["skipped_category_labels"] == ["채용행사"]


def test_query_caps_the_number_of_categories(session_client):
    # 분류가 6개를 다 고르는 일이 실제로 흔한데(측정: "백엔드 개발자, 경기
    # 북부"가 6/6), 카테고리마다 관련성 판단 LLM 호출이 하나씩 붙으므로
    # 상한이 없으면 질문 한 번이 LLM 호출 7회가 된다.
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    one_result = [JobInfoResult(title="아무거나", subtitle="서울", meta_lines=[])]
    all_six = ["job_fair", "public_recruitment", "public_recruitment_company", "training_course", "job_seeker_program", "promising_sme"]
    fake_client = _override_job_info_client(results_by_category={c: one_result for c in all_six})
    fake_llm = FakeLLMProvider(
        job_info_categories=[JobInfoCategoryQuery(category=c) for c in all_six],
        job_info_relevant_indices=[0],
    )
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "일자리 찾아줘"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert fake_client.search_calls == all_six[:3]
    assert len(fake_llm.select_relevant_calls) == 3
    assert [c["category"] for c in resp.json()["categories"]] == all_six[:3]


def test_query_reports_a_worknet_failure_as_skipped(session_client):
    # 예전에는 실패한 카테고리를 그냥 버려서, 전부 실패하면 사용자에게는
    # "AI가 아무 말도 안 하는" 빈 응답으로 보였다.
    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    _override_job_info_client(
        results_by_category={"job_fair": [JobInfoResult(title="취업박람회", subtitle="서울", meta_lines=[])]},
        failing_categories={"training_course"},
    )
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider(
        job_info_categories=[JobInfoCategoryQuery(category="job_fair"), JobInfoCategoryQuery(category="training_course")],
        job_info_relevant_indices=[0],
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "채용행사랑 훈련과정"}, headers=_auth(token)
    )

    body = resp.json()
    assert [c["category"] for c in body["categories"]] == ["job_fair"]
    assert body["skipped_category_labels"] == ["직업훈련과정"]


def test_query_runs_relevance_judgments_one_at_a_time(session_client):
    # 로컬 Ollama는 요청을 직렬 처리하므로, 카테고리별 판단을 동시에 던지면
    # 뒤쪽 호출이 큐에서 기다리는 동안 자기 타임아웃을 다 써버린다 — 6개를
    # asyncio.gather로 던졌을 때 1개만 성공하고 5개가 죽는 걸 실측했다(devlog 20).
    import asyncio

    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    one_result = [JobInfoResult(title="아무거나", subtitle="서울", meta_lines=[])]
    categories = ["job_fair", "training_course", "promising_sme"]
    _override_job_info_client(results_by_category={c: one_result for c in categories})

    class ConcurrencyTrackingLLM(FakeLLMProvider):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.in_flight = 0
            self.max_in_flight = 0

        async def select_relevant_job_info_results(self, query, category_label, candidates):
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                await asyncio.sleep(0)  # 동시에 돌고 있다면 여기서 서로 끼어든다
                return await super().select_relevant_job_info_results(query, category_label, candidates)
            finally:
                self.in_flight -= 1

    fake_llm = ConcurrencyTrackingLLM(
        job_info_categories=[JobInfoCategoryQuery(category=c) for c in categories],
        job_info_relevant_indices=[0],
    )
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "일자리 찾아줘"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert len(fake_llm.select_relevant_calls) == 3
    assert fake_llm.max_in_flight == 1


def test_query_skips_remaining_categories_when_the_budget_runs_out(session_client, monkeypatch):
    # 예산을 넘기면 남은 카테고리는 skipped로 넘기고 그때까지 모인 결과만
    # 돌려준다 — 무한정 기다리다 화면이 멈추는 것보다 부분 결과가 낫다.
    import asyncio

    from app.api import job_search as job_search_module

    monkeypatch.setattr(job_search_module, "_QUERY_BUDGET_SECONDS", 0.05)

    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    one_result = [JobInfoResult(title="아무거나", subtitle="서울", meta_lines=[])]
    _override_job_info_client(results_by_category={"job_fair": one_result, "training_course": one_result})

    class SlowRelevanceLLM(FakeLLMProvider):
        async def select_relevant_job_info_results(self, query, category_label, candidates):
            await asyncio.sleep(0.5)
            return [0]

    app.dependency_overrides[get_llm_provider] = lambda: SlowRelevanceLLM(
        job_info_categories=[JobInfoCategoryQuery(category="job_fair"), JobInfoCategoryQuery(category="training_course")]
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "일자리 찾아줘"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["categories"] == []
    assert body["skipped_category_labels"] == ["채용행사", "직업훈련과정"]


def test_query_passes_extracted_search_params_to_the_client(session_client):
    # 이 경로가 없던 동안에는 카테고리(=엔드포인트)만 맞게 고르고 조회는 전국
    # 첫 20건을 무조건 받아왔다 — 질문한 지역/직무가 후보에 아예 없으니
    # 관련성 판단이 정확해도 건질 게 없었다(devlog 20).
    from app.services.llm.base import JobInfoQueryParams

    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    fake_client = _override_job_info_client(
        results_by_category={"training_course": [JobInfoResult(title="자바 과정", subtitle="고양", meta_lines=[])]}
    )
    extracted = JobInfoQueryParams(regions=["경기 북부"], keywords=["자바"])
    fake_llm = FakeLLMProvider(
        job_info_categories=[JobInfoCategoryQuery(category="training_course")],
        job_info_query_params=extracted,
        job_info_relevant_indices=[0],
    )
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query",
        json={"query": "나는 백엔드 개발자야. 경기 북부에서 일자리를 구하고 싶어."},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert fake_client.search_params == [extracted]
    # 추출 프롬프트에는 인식 가능한 지역 어휘가 함께 넘어가야 한다.
    assert len(fake_llm.extract_query_params_calls) == 1
    _, known_regions = fake_llm.extract_query_params_calls[0]
    assert "경기 북부" in known_regions


def test_query_still_searches_when_param_extraction_fails(session_client):
    # 조건 추출이 실패하면 조건 없이라도 조회한다 — 예전 동작으로 퇴화할
    # 뿐이고, 질문 전체를 실패시키는 것보다 낫다.
    from app.services.llm.base import LLMUnavailableError

    token = _register_and_login(session_client)
    session_id = _create_job_search_session(session_client, token)
    fake_client = _override_job_info_client(
        results_by_category={"job_fair": [JobInfoResult(title="취업박람회", subtitle="서울", meta_lines=[])]}
    )

    class BrokenParamsLLM(FakeLLMProvider):
        async def extract_job_info_query_params(self, query, known_regions):
            raise LLMUnavailableError()

    app.dependency_overrides[get_llm_provider] = lambda: BrokenParamsLLM(
        job_info_categories=[JobInfoCategoryQuery(category="job_fair")],
        job_info_relevant_indices=[0],
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/job-search/query", json={"query": "채용행사 알려줘"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert [c["category"] for c in resp.json()["categories"]] == ["job_fair"]
    assert fake_client.search_params == [None]


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
