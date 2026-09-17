from __future__ import annotations

from tests.api.test_document import _advance_to_result_generate, _register_and_login


def _generate_and_finalize(client, headers, **kwargs):
    session_id = _advance_to_result_generate(client, headers, **kwargs)
    client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)
    return session_id


def test_share_link_requires_a_finalized_document(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})

    resp = document_client.post(f"/api/v1/sessions/{session_id}/document/share", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "document_not_finalized"


def test_share_link_is_created_and_reused(document_client):
    headers = _register_and_login(document_client)
    session_id = _generate_and_finalize(document_client, headers)

    first = document_client.post(f"/api/v1/sessions/{session_id}/document/share", headers=headers)
    assert first.status_code == 200
    slug = first.json()["share_slug"]
    assert slug

    second = document_client.post(f"/api/v1/sessions/{session_id}/document/share", headers=headers)
    assert second.json()["share_slug"] == slug


def test_public_share_preview_is_reachable_without_auth_and_leaks_nothing(document_client):
    headers = _register_and_login(document_client)
    session_id = _generate_and_finalize(document_client, headers)
    slug = document_client.post(f"/api/v1/sessions/{session_id}/document/share", headers=headers).json()["share_slug"]

    resp = document_client.get(f"/api/v1/share/{slug}")
    assert resp.status_code == 200
    body = resp.json()

    # 정직성 스코어보드/근거 등급을 보여주되, 개인정보(세션/유저 id, 근거 원문,
    # 기록물 URL)는 스키마 자체에 존재할 수 없어야 한다 — 회귀 방지 테스트.
    assert set(body.keys()) == {"tone", "representative_sentences", "evidence_grade_summary"}
    assert body["tone"] == "neutral"
    assert len(body["representative_sentences"]) > 0
    assert sum(body["evidence_grade_summary"].values()) > 0


def test_share_preview_404_for_unknown_slug(document_client):
    resp = document_client.get("/api/v1/share/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "share_not_found"


def test_revoking_a_share_link_makes_the_public_preview_404(document_client):
    headers = _register_and_login(document_client)
    session_id = _generate_and_finalize(document_client, headers)
    slug = document_client.post(f"/api/v1/sessions/{session_id}/document/share", headers=headers).json()["share_slug"]

    revoke = document_client.delete(f"/api/v1/sessions/{session_id}/document/share", headers=headers)
    assert revoke.status_code == 204

    resp = document_client.get(f"/api/v1/share/{slug}")
    assert resp.status_code == 404
