from __future__ import annotations

from tests.api.test_document import _advance_to_result_generate, _register_and_login


def test_trust_score_404_before_document_generated(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)

    resp = document_client.get(f"/api/v1/sessions/{session_id}/trust-score", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "document_not_found"


def test_trust_score_reflects_a_fully_accepted_document(document_client):
    """FakeLLMProvider's default generate_document cites every fact, and
    _submit_review confirms every AI draft unedited (was_edited=False) — so a
    freshly generated document should read as "everything accepted"."""
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})

    resp = document_client.get(f"/api/v1/sessions/{session_id}/trust-score", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sentences"] > 0
    assert body["evidence_coverage_ratio"] == 1.0
    assert body["consistency_pass_rate"] == 1.0
    assert body["ai_acceptance_rate"] == 1.0
    assert body["interview_ai_acceptance_rate"] == 1.0
    assert body["user_edited_sentences"] == 0


def test_trust_score_drops_after_a_direct_edit(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()

    sentence_id = doc["paragraphs"][0]["sentences"][0]["id"]
    document_client.patch(
        f"/api/v1/sessions/{session_id}/document/sentences/{sentence_id}",
        headers=headers,
        json={"text": "직접 고쳐 쓴 문장입니다"},
    )

    resp = document_client.get(f"/api/v1/sessions/{session_id}/trust-score", headers=headers)
    body = resp.json()
    assert body["user_edited_sentences"] == 1
    assert body["ai_acceptance_rate"] < 1.0


def test_global_trust_score_is_unauthenticated_and_counts_only_final_documents(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})

    # Not finalized yet — global stats (FINAL-only) should still report zero sentences.
    resp = document_client.get("/api/v1/trust-score/global")
    assert resp.status_code == 200
    assert resp.json()["total_sentences"] == 0

    document_client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)

    resp = document_client.get("/api/v1/trust-score/global")
    assert resp.status_code == 200
    assert resp.json()["total_sentences"] > 0
