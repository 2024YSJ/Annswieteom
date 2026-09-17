from __future__ import annotations

from app.core.config import settings
from tests.api.test_document import _advance_to_result_generate, _register_and_login


def test_demo_document_404_when_not_configured(document_client, monkeypatch):
    monkeypatch.setattr(settings, "demo_session_id", "")
    resp = document_client.get("/api/v1/demo/document")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "demo_not_configured"


def test_demo_document_404_when_configured_session_has_no_final_document(document_client, monkeypatch):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    # DRAFT, not FINAL — the demo route should not surface an unfinalized document.
    monkeypatch.setattr(settings, "demo_session_id", session_id)

    resp = document_client.get("/api/v1/demo/document")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "demo_document_not_found"


def test_demo_document_is_reachable_without_auth(document_client, monkeypatch):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    document_client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)
    monkeypatch.setattr(settings, "demo_session_id", session_id)

    # No Authorization header at all.
    resp = document_client.get("/api/v1/demo/document")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "FINAL"
    sentences = [s for p in body["paragraphs"] for s in p["sentences"]]
    assert len(sentences) > 0
    assert all("evidence_grade" in s for s in sentences)


def test_demo_document_ignores_a_malformed_session_id(document_client, monkeypatch):
    monkeypatch.setattr(settings, "demo_session_id", "not-a-uuid")
    resp = document_client.get("/api/v1/demo/document")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "demo_not_configured"
