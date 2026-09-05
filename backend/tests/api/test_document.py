from __future__ import annotations

from app.services.interview_question_bank import BASE_QUESTIONS
from app.services.llm.base import DraftDocument, SentenceWithEvidence

# part_time과 study 둘 다 고정 질문을 4개씩 정의해둔다(interview_question_bank.py).
# MAX_QUESTIONS_PER_CATEGORY는 이보다 넉넉하므로(드릴다운 여지를 남기기 위해), 이
# 헬퍼는 드릴다운 없이(FakeLLMProvider 기본값) 고정 질문만 다 채워 카테고리를
# 끝내는 것을 기준으로 한다 — 정확히 고정 질문 개수만큼만 돈다.
FACTS_PER_CATEGORY = len(BASE_QUESTIONS["part_time"])


def _register_and_login(client, email="alice@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "nickname": "Alice"},
    )
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _do_one_turn(client, headers, session_id):
    resp = client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "답변입니다"})
    assert resp.status_code == 200
    candidates = resp.json()["candidates"]
    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [{"index": c["index"], "final_text": c["content"], "was_edited": False} for c in candidates]},
    )
    assert resp.status_code == 200
    return resp.json()


def _advance_to_result_generate(client, headers, category_types=("part_time",)):
    resp = client.post("/api/v1/sessions", headers=headers)
    session_id = resp.json()["id"]

    client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers,
        json={"categories": [{"category_type": t} for t in category_types]},
    )
    client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers)

    for _ in category_types:
        for _ in range(FACTS_PER_CATEGORY):
            _do_one_turn(client, headers, session_id)

    ctx = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["status"] == "RESULT_GENERATE"
    return session_id


def test_generate_creates_sentences_with_evidence_and_advances_status(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["version"] == 1
    assert body["status"] == "DRAFT"
    assert len(body["sentences"]) == FACTS_PER_CATEGORY  # one fact per confirm round -> one sentence per fact (fake LLM)

    for sentence in body["sentences"]:
        assert sentence["consistency_check_passed"] is True
        assert len(sentence["evidence"]) == 1
        assert sentence["evidence"][0]["citation"] is None  # user_confirmed facts have no record origin

    ctx = document_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["status"] == "RESULT_REVIEW"


def test_generate_only_passes_this_category_facts_to_llm(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers, category_types=("part_time", "study"))

    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})

    # generate_document is called once per category, each with just that category's facts.
    assert len(document_client.fake_llm.document_calls) == 2
    for fact_ids, tone in document_client.fake_llm.document_calls:
        assert len(fact_ids) == FACTS_PER_CATEGORY
        assert tone == "neutral"


def test_generate_requires_result_generate_status(document_client):
    headers = _register_and_login(document_client)
    resp = document_client.post("/api/v1/sessions", headers=headers)
    session_id = resp.json()["id"]  # still PERIOD_INPUT

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    )
    assert resp.status_code == 409


def test_get_document_returns_latest_version(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "plain"})

    resp = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["tone"] == "plain"


def test_get_document_before_generate_returns_404(document_client):
    headers = _register_and_login(document_client)
    resp = document_client.post("/api/v1/sessions", headers=headers)
    session_id = resp.json()["id"]

    resp = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers)
    assert resp.status_code == 404


def test_regenerate_creates_new_version_with_different_tone(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/document/regenerate", headers=headers, json={"tone": "assertive"}
    )
    assert resp.status_code == 201
    assert resp.json()["version"] == 2
    assert resp.json()["tone"] == "assertive"

    latest = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers).json()
    assert latest["version"] == 2
    assert latest["tone"] == "assertive"


def test_patch_sentence_updates_text_and_forces_consistent(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    sentence_id = doc["sentences"][0]["id"]
    original_evidence = doc["sentences"][0]["evidence"]

    resp = document_client.patch(
        f"/api/v1/sessions/{session_id}/document/sentences/{sentence_id}",
        headers=headers,
        json={"text": "사용자가 직접 고쳐 쓴 문장"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "사용자가 직접 고쳐 쓴 문장"
    assert body["consistency_check_passed"] is True
    assert [e["fact_id"] for e in body["evidence"]] == [e["fact_id"] for e in original_evidence]


def test_regenerate_single_sentence_only_uses_its_own_evidence(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    sentence_id = doc["sentences"][0]["id"]
    calls_before = len(document_client.fake_llm.document_calls)

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/document/sentences/{sentence_id}/regenerate", headers=headers
    )
    assert resp.status_code == 200
    assert len(document_client.fake_llm.document_calls) == calls_before + 1
    fact_ids, tone = document_client.fake_llm.document_calls[-1]
    assert len(fact_ids) == 1  # only this sentence's own cited fact, not the whole category
    assert tone == "neutral"  # inherited from the document, no tone in the request body


def test_finalize_then_export_returns_full_text(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()

    resp = document_client.get(f"/api/v1/sessions/{session_id}/export?format=txt", headers=headers)
    assert resp.status_code == 409  # not finalized yet

    resp = document_client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "FINAL"

    resp = document_client.get(f"/api/v1/sessions/{session_id}/export?format=txt", headers=headers)
    assert resp.status_code == 200
    for sentence in doc["sentences"]:
        assert sentence["text"] in resp.text


def test_export_unsupported_format_returns_400(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    document_client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)

    resp = document_client.get(f"/api/v1/sessions/{session_id}/export?format=pdf", headers=headers)
    assert resp.status_code == 400


def test_unrelated_generated_sentence_is_marked_inconsistent_not_dropped(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)

    # Make the LLM return one sentence citing a fact, but embed that sentence
    # text to a vector orthogonal to the default so cosine similarity is 0.
    document_client.fake_embedding._vectors["완전히 무관한 문장"] = [0.0, 1.0]
    document_client.fake_llm._document_queue = [
        DraftDocument(sentences=[SentenceWithEvidence(text="완전히 무관한 문장", fact_indices=[0])])
    ]

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    )
    body = resp.json()
    assert len(body["sentences"]) == 1
    assert body["sentences"][0]["consistency_check_passed"] is False
    assert body["sentences"][0]["text"] == "완전히 무관한 문장"  # not deleted, just flagged


def test_other_users_session_403_and_cross_session_sentence_404(document_client):
    headers_a = _register_and_login(document_client, email="a@example.com")
    session_id = _advance_to_result_generate(document_client, headers_a)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers_a, json={"tone": "neutral"}
    ).json()
    sentence_id = doc["sentences"][0]["id"]

    headers_b = _register_and_login(document_client, email="b@example.com")

    resp = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers_b)
    assert resp.status_code == 403

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers_b, json={"tone": "neutral"}
    )
    assert resp.status_code == 403

    # b's own session, but referencing a's sentence id -> 404, not leaking a's document
    resp = document_client.post("/api/v1/sessions", headers=headers_b)
    session_b_id = resp.json()["id"]
    resp = document_client.patch(
        f"/api/v1/sessions/{session_b_id}/document/sentences/{sentence_id}",
        headers=headers_b,
        json={"text": "훔쳐쓰기"},
    )
    assert resp.status_code == 404
