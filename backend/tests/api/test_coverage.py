from __future__ import annotations

from app.services.interview_question_bank import BASE_QUESTIONS


def _register_and_login(client, email="cov@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "nickname": "Cov"},
    )
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _session_at_interviewing(client, headers, category_types=("part_time",)):
    session_id = client.post("/api/v1/sessions", headers=headers).json()["id"]
    client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-12-31"},
    )
    client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers,
        json={"categories": [{"category_type": t} for t in category_types]},
    )
    for _ in category_types:
        client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers)
    return session_id


def _categories(client, headers, session_id):
    return client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["categories"]


def test_coverage_is_empty_before_any_period_is_known(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)

    resp = session_client.get(f"/api/v1/sessions/{session_id}/coverage", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_days"] == 365
    assert body["covered_days"] == 0
    assert body["coverage_ratio"] == 0.0
    assert len(body["categories_without_period"]) == 1
    # 아무것도 설명되지 않았으므로 공백기 전체가 하나의 빈 구간이다.
    assert len(body["uncovered_ranges"]) == 1
    assert body["suggested_probe_question"] is not None


def test_setting_a_category_period_moves_coverage(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    category_id = _categories(session_client, headers, session_id)[0]["id"]

    resp = session_client.patch(
        f"/api/v1/sessions/{session_id}/categories/{category_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    assert resp.status_code == 204

    body = session_client.get(f"/api/v1/sessions/{session_id}/coverage", headers=headers).json()
    assert body["covered_days"] == 181
    assert body["categories_without_period"] == []
    assert [(r["start"], r["end"]) for r in body["uncovered_ranges"]] == [("2025-07-01", "2025-12-31")]
    assert "2025년 7월~12월" in body["suggested_probe_question"]


def test_set_category_period_rejects_reversed_dates(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    category_id = _categories(session_client, headers, session_id)[0]["id"]

    resp = session_client.patch(
        f"/api/v1/sessions/{session_id}/categories/{category_id}/period",
        headers=headers,
        json={"start_date": "2025-06-30", "end_date": "2025-01-01"},
    )
    assert resp.status_code == 422


def test_set_category_period_rejects_another_users_category(session_client):
    owner_headers = _register_and_login(session_client, email="owner@example.com")
    session_id = _session_at_interviewing(session_client, owner_headers)
    category_id = _categories(session_client, owner_headers, session_id)[0]["id"]

    other_headers = _register_and_login(session_client, email="other@example.com")
    resp = session_client.patch(
        f"/api/v1/sessions/{session_id}/categories/{category_id}/period",
        headers=other_headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    assert resp.status_code == 403


def test_fill_creates_a_category_for_the_uncovered_range_and_points_the_interview_at_it(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    category_id = _categories(session_client, headers, session_id)[0]["id"]
    session_client.patch(
        f"/api/v1/sessions/{session_id}/categories/{category_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/coverage/fill",
        headers=headers,
        json={"start_date": "2025-07-01", "end_date": "2025-12-31"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "INTERVIEWING"
    assert body["category_label"] == "2025년 7월~12월"

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["current_category"]["id"] == body["category_id"]

    # 새 카테고리는 시간 구간 하나를 가리키므로 소분류 질문을 건너뛰고 곧바로
    # other 유형의 고정 질문으로 들어간다.
    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["question_source"] == "base"
    assert resp.json()["question_text"] == BASE_QUESTIONS["other"][0].text

    # 빈 구간이 카테고리로 잡히면서 커버리지가 100%가 된다.
    coverage = session_client.get(f"/api/v1/sessions/{session_id}/coverage", headers=headers).json()
    assert coverage["coverage_ratio"] == 1.0
    assert coverage["uncovered_ranges"] == []
    assert coverage["suggested_probe_question"] is None


def test_fill_rejects_an_already_covered_range(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)
    category_id = _categories(session_client, headers, session_id)[0]["id"]
    session_client.patch(
        f"/api/v1/sessions/{session_id}/categories/{category_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-12-31"},
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/coverage/fill",
        headers=headers,
        json={"start_date": "2025-03-01", "end_date": "2025-04-30"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "range_already_covered"


def test_fill_rejects_a_range_outside_the_gap_period(session_client):
    headers = _register_and_login(session_client)
    session_id = _session_at_interviewing(session_client, headers)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/coverage/fill",
        headers=headers,
        json={"start_date": "2024-01-01", "end_date": "2024-06-30"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "range_outside_gap_period"


def test_fill_is_rejected_before_the_interview_starts(session_client):
    headers = _register_and_login(session_client)
    session_id = session_client.post("/api/v1/sessions", headers=headers).json()["id"]
    session_client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-12-31"},
    )

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/coverage/fill",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    assert resp.status_code == 409


def test_coverage_requires_a_gap_period(session_client):
    headers = _register_and_login(session_client)
    session_id = session_client.post("/api/v1/sessions", headers=headers).json()["id"]

    resp = session_client.get(f"/api/v1/sessions/{session_id}/coverage", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "gap_period_not_set"
