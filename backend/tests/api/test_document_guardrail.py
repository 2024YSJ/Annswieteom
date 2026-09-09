"""정직성 가드레일 집행 + 근거 등급 + 내보내기/버전 (2026-09-09).

`test_document.py`는 문서 생성·편집 자체를 다루고, 이 파일은 "생성된 문서가
근거와 맞는지"를 서비스가 실제로 **집행**하는지를 다룬다 — 예전에는 정합성 검사
결과가 화면에 노란 배지로 표시만 되고 확정도 내보내기도 그대로 통과했다.
"""
from __future__ import annotations

from app.services.llm.base import DraftDocument, ParagraphDraft, SentenceWithEvidence

from tests.api.test_document import (
    _advance_to_result_generate,
    _all_sentences,
    _register_and_login,
)


def _generate_with_one_unverified_sentence(client, headers):
    session_id = _advance_to_result_generate(client, headers)
    # 기본 벡터와 직교하는 벡터를 등록해 코사인 유사도를 0으로 만든다.
    client.fake_embedding._vectors["근거와 무관한 문장"] = [0.0, 1.0]
    client.fake_llm._document_queue = [
        DraftDocument(paragraphs=[
            ParagraphDraft(topic="주제", sentences=[
                SentenceWithEvidence(text="근거와 무관한 문장", fact_indices=[0]),
                SentenceWithEvidence(text="근거에 맞는 문장", fact_indices=[1]),
            ])
        ])
    ]
    client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    return session_id


def test_generate_records_the_consistency_score_not_just_the_verdict(document_client):
    """점수를 버리면 임계값(settings.consistency_threshold)을 실제 샘플에 맞춰
    조정할 근거 데이터가 없다 — 0.54였는지 0.11이었는지 구분이 안 됐다."""
    headers = _register_and_login(document_client)
    session_id = _generate_with_one_unverified_sentence(document_client, headers)

    doc = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers).json()
    by_text = {s["text"]: s for s in _all_sentences(doc)}
    assert by_text["근거와 무관한 문장"]["consistency_score"] == 0.0
    assert by_text["근거에 맞는 문장"]["consistency_score"] == 1.0


def test_finalize_is_blocked_while_an_unverified_sentence_remains(document_client):
    headers = _register_and_login(document_client)
    session_id = _generate_with_one_unverified_sentence(document_client, headers)

    resp = document_client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "unverified_sentences"
    assert [s["text"] for s in detail["sentences"]] == ["근거와 무관한 문장"]
    assert detail["sentences"][0]["consistency_score"] == 0.0

    # 확정되지 않았으므로 내보내기도 여전히 막혀 있다.
    resp = document_client.get(f"/api/v1/sessions/{session_id}/export?format=txt", headers=headers)
    assert resp.status_code == 409


def test_finalize_proceeds_when_the_user_acknowledges(document_client):
    """판단 자체는 사용자 몫이지만, 모르고 지나칠 수는 없어야 한다."""
    headers = _register_and_login(document_client)
    session_id = _generate_with_one_unverified_sentence(document_client, headers)

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/document/finalize",
        headers=headers,
        json={"acknowledge_unverified": True},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "FINAL"


def test_finalize_proceeds_after_the_offending_sentence_is_fixed(document_client):
    headers = _register_and_login(document_client)
    session_id = _generate_with_one_unverified_sentence(document_client, headers)

    doc = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers).json()
    bad = next(s for s in _all_sentences(doc) if s["text"] == "근거와 무관한 문장")
    sentence_id = bad["id"]
    document_client.patch(
        f"/api/v1/sessions/{session_id}/document/sentences/{sentence_id}",
        headers=headers,
        json={"text": "직접 고쳐 쓴 문장"},
    )

    resp = document_client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)
    assert resp.status_code == 200


def test_user_edited_sentence_is_distinguishable_from_a_verified_one(document_client):
    """둘 다 consistency_check_passed=True지만 근거가 다르다 — 예전에는 같은
    값으로 뭉개져서 사용자가 고쳐 쓴 문장에도 '검증 통과' 배지가 그대로 붙었다."""
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    sentence = _all_sentences(doc)[0]
    assert sentence["edited_by_user"] is False
    sentence_id = sentence["id"]

    resp = document_client.patch(
        f"/api/v1/sessions/{session_id}/document/sentences/{sentence_id}",
        headers=headers,
        json={"text": "제가 직접 고친 문장"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["consistency_check_passed"] is True
    assert body["edited_by_user"] is True
    # 이 문장에 대해 계산된 적 없는 점수를 남겨두면 오해를 부른다.
    assert body["consistency_score"] is None


def test_regenerating_a_sentence_clears_the_user_edited_flag(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    sentence_id = _all_sentences(doc)[0]["id"]
    document_client.patch(
        f"/api/v1/sessions/{session_id}/document/sentences/{sentence_id}",
        headers=headers,
        json={"text": "직접 고친 문장"},
    )

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/document/sentences/{sentence_id}/regenerate", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["edited_by_user"] is False


def test_sentences_carry_an_evidence_grade(document_client):
    """본인 진술만 있는 문장과 실제 기록물이 뒷받침하는 문장은 채용담당자
    입장에서 값이 다르다 — API가 그 차이를 내려줘야 프론트가 구분해 보여준다."""
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()

    for sentence in _all_sentences(doc):
        # FakeLLMProvider가 만드는 사실은 전부 user_confirmed(기록물 근거 없음)다.
        assert sentence["evidence_grade"] == "self_reported"


def test_sentence_with_no_cited_fact_is_graded_unsupported(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.fake_llm._document_queue = [
        DraftDocument(paragraphs=[
            ParagraphDraft(topic="주제", sentences=[SentenceWithEvidence(text="근거 없는 문장", fact_indices=[])])
        ])
    ]

    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    sentence = _all_sentences(doc)[0]
    assert sentence["evidence_grade"] == "unsupported"
    assert sentence["consistency_check_passed"] is False
    assert sentence["consistency_score"] is None  # 검사를 수행조차 못 했다


def test_export_supports_markdown(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    document_client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)

    resp = document_client.get(f"/api/v1/sessions/{session_id}/export?format=md", headers=headers)
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    for sentence in _all_sentences(doc):
        assert sentence["text"] in resp.text


def test_citations_appendix_is_omitted_when_nothing_is_record_backed(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    document_client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)

    resp = document_client.get(
        f"/api/v1/sessions/{session_id}/export?format=txt&citations=true", headers=headers
    )
    assert resp.status_code == 200
    # 이 세션의 사실은 전부 user_confirmed라 인용할 출처가 없다 — 빈 부록 제목만
    # 덩그러니 남기지는 않는다.
    assert "[근거 자료]" not in resp.text


def test_list_document_versions_returns_newest_first(document_client):
    """regenerate는 예전 버전을 지우지 않고 쌓아왔는데, 정작 최신 1건 말고는
    꺼내볼 방법이 없었다."""
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    document_client.post(
        f"/api/v1/sessions/{session_id}/document/regenerate", headers=headers, json={"tone": "assertive"}
    )

    resp = document_client.get(f"/api/v1/sessions/{session_id}/documents", headers=headers)
    assert resp.status_code == 200
    versions = resp.json()
    assert [v["version"] for v in versions] == [2, 1]
    assert [v["tone"] for v in versions] == ["assertive", "neutral"]
