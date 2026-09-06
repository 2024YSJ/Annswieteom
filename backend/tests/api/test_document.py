from __future__ import annotations

from app.services.interview_question_bank import BASE_QUESTIONS
from app.services.llm.base import DraftDocument, ParagraphDraft, SentenceWithEvidence


def _all_sentences(doc: dict) -> list[dict]:
    """Flattens a DocumentRead's paragraphs into one sentence list, in order —
    most assertions here don't care about paragraph grouping itself."""
    return [s for p in doc["paragraphs"] for s in p["sentences"]]

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
    # One /records/skip call advances past a single category's record request;
    # with several categories it must be called once per category to actually
    # reach INTERVIEWING.
    for _ in category_types:
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
    sentences = _all_sentences(body)
    assert len(sentences) == FACTS_PER_CATEGORY  # one fact per confirm round -> one sentence per fact (fake LLM)

    for sentence in sentences:
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
    sentence_id = _all_sentences(doc)[0]["id"]
    original_evidence = _all_sentences(doc)[0]["evidence"]

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
    sentence_id = _all_sentences(doc)[0]["id"]
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
    for sentence in _all_sentences(doc):
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
        DraftDocument(paragraphs=[
            ParagraphDraft(topic="무관한 주제", sentences=[SentenceWithEvidence(text="완전히 무관한 문장", fact_indices=[0])])
        ])
    ]

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    )
    body = resp.json()
    sentences = _all_sentences(body)
    assert len(sentences) == 1
    assert sentences[0]["consistency_check_passed"] is False
    assert sentences[0]["text"] == "완전히 무관한 문장"  # not deleted, just flagged


def test_generate_groups_sentences_into_paragraphs(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)

    document_client.fake_llm._document_queue = [
        DraftDocument(paragraphs=[
            ParagraphDraft(topic="첫 번째 주제", sentences=[SentenceWithEvidence(text="문장 A", fact_indices=[0])]),
            ParagraphDraft(topic="두 번째 주제", sentences=[
                SentenceWithEvidence(text="문장 B", fact_indices=[1]),
                SentenceWithEvidence(text="문장 C", fact_indices=[2]),
            ]),
        ])
    ]

    resp = document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    body = resp.json()
    assert len(body["paragraphs"]) == 2
    assert body["paragraphs"][0]["topic"] == "첫 번째 주제"
    assert [s["text"] for s in body["paragraphs"][0]["sentences"]] == ["문장 A"]
    assert body["paragraphs"][0]["user_confirmed"] is False
    assert [s["text"] for s in body["paragraphs"][1]["sentences"]] == ["문장 B", "문장 C"]


def test_update_paragraph_renames_topic_and_confirms(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    paragraph_id = doc["paragraphs"][0]["id"]

    resp = document_client.patch(
        f"/api/v1/sessions/{session_id}/document/paragraphs/{paragraph_id}",
        headers=headers,
        json={"topic": "새 주제", "user_confirmed": True},
    )
    assert resp.status_code == 200
    assert resp.json()["topic"] == "새 주제"
    assert resp.json()["user_confirmed"] is True


def test_merge_paragraph_with_next_combines_sentences_and_removes_next(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.fake_llm._document_queue = [
        DraftDocument(paragraphs=[
            ParagraphDraft(topic="A", sentences=[SentenceWithEvidence(text="문장 A", fact_indices=[0])]),
            ParagraphDraft(topic="B", sentences=[SentenceWithEvidence(text="문장 B", fact_indices=[1])]),
        ])
    ]
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    first_id = doc["paragraphs"][0]["id"]
    second_id = doc["paragraphs"][1]["id"]

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/document/paragraphs/{first_id}/merge-next", headers=headers
    )
    assert resp.status_code == 200
    merged = resp.json()
    assert [s["text"] for s in merged["sentences"]] == ["문장 A", "문장 B"]

    full_doc = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers).json()
    assert len(full_doc["paragraphs"]) == 1
    assert not any(p["id"] == second_id for p in full_doc["paragraphs"])


def test_merge_last_paragraph_with_next_returns_409(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    last_paragraph_id = doc["paragraphs"][-1]["id"]

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/document/paragraphs/{last_paragraph_id}/merge-next", headers=headers
    )
    assert resp.status_code == 409


def test_move_sentence_to_next_and_prev_paragraph(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.fake_llm._document_queue = [
        DraftDocument(paragraphs=[
            ParagraphDraft(topic="A", sentences=[SentenceWithEvidence(text="문장 A", fact_indices=[0])]),
            ParagraphDraft(topic="B", sentences=[SentenceWithEvidence(text="문장 B", fact_indices=[1])]),
        ])
    ]
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    first_paragraph_id = doc["paragraphs"][0]["id"]
    second_paragraph_id = doc["paragraphs"][1]["id"]
    sentence_a_id = doc["paragraphs"][0]["sentences"][0]["id"]

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/document/sentences/{sentence_a_id}/move",
        headers=headers,
        json={"direction": "next"},
    )
    assert resp.status_code == 200

    full_doc = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers).json()
    by_id = {p["id"]: p for p in full_doc["paragraphs"]}
    assert [s["id"] for s in by_id[first_paragraph_id]["sentences"]] == []
    assert {s["id"] for s in by_id[second_paragraph_id]["sentences"]} == {sentence_a_id, doc["paragraphs"][1]["sentences"][0]["id"]}

    # Move it back with "prev".
    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/document/sentences/{sentence_a_id}/move",
        headers=headers,
        json={"direction": "prev"},
    )
    assert resp.status_code == 200
    full_doc = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers).json()
    by_id = {p["id"]: p for p in full_doc["paragraphs"]}
    assert [s["id"] for s in by_id[first_paragraph_id]["sentences"]] == [sentence_a_id]


def test_move_sentence_past_the_edge_returns_409(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
    ).json()
    first_sentence_id = doc["paragraphs"][0]["sentences"][0]["id"]

    resp = document_client.post(
        f"/api/v1/sessions/{session_id}/document/sentences/{first_sentence_id}/move",
        headers=headers,
        json={"direction": "prev"},
    )
    assert resp.status_code == 409


def test_export_separates_paragraphs_with_blank_line_and_omits_topic(document_client):
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)
    document_client.fake_llm._document_queue = [
        DraftDocument(paragraphs=[
            ParagraphDraft(topic="주제는 내보내기에 없어야 함", sentences=[SentenceWithEvidence(text="문장 A", fact_indices=[0])]),
            ParagraphDraft(topic="다른 주제", sentences=[SentenceWithEvidence(text="문장 B", fact_indices=[1])]),
        ])
    ]
    document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    document_client.post(f"/api/v1/sessions/{session_id}/document/finalize", headers=headers)

    resp = document_client.get(f"/api/v1/sessions/{session_id}/export?format=txt", headers=headers)
    assert resp.status_code == 200
    assert resp.text == "문장 A\n\n문장 B"
    assert "주제는 내보내기에 없어야 함" not in resp.text


def test_other_users_session_403_and_cross_session_sentence_404(document_client):
    headers_a = _register_and_login(document_client, email="a@example.com")
    session_id = _advance_to_result_generate(document_client, headers_a)
    doc = document_client.post(
        f"/api/v1/sessions/{session_id}/generate", headers=headers_a, json={"tone": "neutral"}
    ).json()
    sentence_id = _all_sentences(doc)[0]["id"]

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
