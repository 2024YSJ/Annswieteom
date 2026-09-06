from __future__ import annotations

import uuid

from app.main import app
from app.services import interview_orchestrator as orchestrator
from app.services.interview_orchestrator import MAX_QUESTIONS_PER_CATEGORY
from app.services.interview_question_bank import BASE_QUESTIONS
from app.services.llm.base import BasedOn, DrilldownDecision, FactCandidate, RecordExcerpt, SufficiencyResult
from app.services.record_pipeline.search import RecordChunkExcerpt, get_chunk_search


def _register_and_login(client, email="alice@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "nickname": "Alice"},
    )
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_session(client, headers):
    resp = client.post("/api/v1/sessions", headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


def _advance_to_interviewing(client, headers, session_id, category_types=("part_time",)):
    """Period -> categories -> records/skip, landing at INTERVIEWING with the
    first category's "여러 활동 있나요?" check still unanswered — use this
    directly (instead of _advance_to_first_category) when a test needs to
    drive that check itself."""
    resp = client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CATEGORY_SELECT"

    resp = client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers,
        json={"categories": [{"category_type": t} for t in category_types]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "RECORD_UPLOAD"

    # One /records/skip call advances past a single category's record request;
    # with several categories it must be called once per category before the
    # session actually reaches INTERVIEWING.
    for _ in category_types:
        resp = client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers)
        assert resp.status_code == 200
    assert resp.json()["status"] == "INTERVIEWING"
    return resp.json()["current_category_id"]


def _advance_to_first_category(client, headers, session_id, category_types=("part_time",)):
    _advance_to_interviewing(client, headers, session_id, category_types=category_types)

    # Positions the session at the first category's first *real* question —
    # callers of this helper assert against BASE_QUESTIONS directly and
    # predate the "여러 활동 있나요?" check, so skip it here rather than in
    # every individual test.
    _skip_activity_breakdown(client, headers, session_id)
    ctx = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    return ctx["current_category"]["id"]


def _skip_activity_breakdown(client, headers, session_id):
    """Every fresh category's very first turn is the "여러 활동 있나요?" check
    added for sub-categorization (2026-09-06) — answer "no" so the real fixed
    questions start right after. FakeLLMProvider's extract_activity_items
    defaults to returning no items, so this never actually splits."""
    resp = client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["question_source"] == "split_check"

    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "하나뿐이에요"}
    )
    assert resp.status_code == 200
    candidates = resp.json()["candidates"]

    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [{"index": c["index"], "final_text": c["content"], "was_edited": False} for c in candidates]},
    )
    assert resp.status_code == 200
    assert resp.json()["category_done"] is False


def _do_turn(client, headers, session_id, answer_text="답변입니다", was_edited=False, include=True):
    """One full ask -> answer -> confirm round trip, confirming every extracted candidate."""
    resp = client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 200
    ask_body = resp.json()

    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": answer_text}
    )
    assert resp.status_code == 200
    candidates = resp.json()["candidates"]

    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={
            "confirmations": [
                {"index": c["index"], "final_text": c["content"], "was_edited": was_edited, "include": include}
                for c in candidates
            ]
        },
    )
    assert resp.status_code == 200
    return ask_body, candidates, resp.json()


def test_base_questions_asked_in_order_for_part_time(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time",))

    # MAX_QUESTIONS_PER_CATEGORY (3) is smaller than part_time's fixed set
    # (4) — only the first 3 fixed questions are ever reached, in order; the
    # category finishes there instead of exhausting all 4 (2026-09-05: "카테
    # 고리당 질문 횟수를 늘리자. 3회까지").
    expected_questions = BASE_QUESTIONS["part_time"][:MAX_QUESTIONS_PER_CATEGORY]
    confirm_body = None
    for i, expected in enumerate(expected_questions):
        ask_body, _, confirm_body = _do_turn(session_client, headers, session_id)
        assert ask_body["question_text"] == expected.text
        assert ask_body["question_source"] == "base"
        is_last = i == len(expected_questions) - 1
        assert confirm_body["category_done"] is is_last

    assert confirm_body["status"] == "RESULT_GENERATE"
    assert confirm_body["current_category_id"] is None

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = {f["fact_type"] for f in ctx["confirmed_facts"]}
    assert fact_types == {q.fact_type for q in expected_questions}
    assert len(ctx["confirmed_facts"]) == len(expected_questions)


def test_ai_can_interleave_a_drilldown_question_between_fixed_base_questions(session_client):
    """Requirement (2026-09-05): "답변마다 AI가 바로 파고들지 판단" — a vague or
    bundled answer to a fixed question (e.g. "기획과 개발을 담당했어요") should get
    an immediate, narrower follow-up before the interview moves on to a
    totally unrelated fixed question, not just after the whole fixed set is
    exhausted."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("project",))

    drilldown_question = "기획 쪽에서는 구체적으로 어떤 아이디어를 내셨나요?"
    session_client.fake_llm._drilldown_queue = [
        DrilldownDecision(should_ask=True, question_text=drilldown_question)
    ]

    # Turn 1: answer the first fixed question ("project_what"). The drilldown
    # decision above fires during this confirm call.
    first_base_question = BASE_QUESTIONS["project"][0]
    ask_body, _, confirm_body = _do_turn(session_client, headers, session_id, answer_text="기획과 개발을 담당했어요")
    assert ask_body["question_text"] == first_base_question.text
    assert confirm_body["category_done"] is False

    # The next question must be the interleaved drill-down, not the second
    # fixed question — and it must be idempotent (cached), not a fresh LLM
    # call each time /ask is polled.
    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.json()["question_text"] == drilldown_question
    assert resp.json()["question_source"] == "followup"

    # Answering it resumes the fixed sequence at the second question — the
    # drilldown queue is now empty (defaults to should_ask=False), so no
    # further interleaving happens.
    _, _, confirm_body = _do_turn(session_client, headers, session_id, answer_text="새로운 캠퍼스 배달 서비스 아이디어를 냈어요")
    assert confirm_body["category_done"] is False  # the drilldown fact didn't satisfy a base fact_type
    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.json()["question_text"] == BASE_QUESTIONS["project"][1].text
    assert resp.json()["question_source"] == "base"

    # The remaining fixed questions (frequency was only peeked via /ask above,
    # not yet answered; then hardship, outcome) still fit comfortably under
    # MAX_QUESTIONS_PER_CATEGORY (well above 4 + 1 drilldown), so the
    # interview keeps going through the rest of the fixed set as normal.
    for _ in BASE_QUESTIONS["project"][1:]:
        _, _, confirm_body = _do_turn(session_client, headers, session_id)

    assert confirm_body["category_done"] is True
    assert confirm_body["status"] == "RESULT_GENERATE"

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = [f["fact_type"] for f in ctx["confirmed_facts"]]
    assert fact_types.count("followup") == 1
    assert set(fact_types) == {q.fact_type for q in BASE_QUESTIONS["project"]} | {"followup"}
    assert len(fact_types) == len(BASE_QUESTIONS["project"]) + 1


def test_candidate_fact_type_is_forced_to_the_question_hint_not_the_llm_choice(session_client, monkeypatch):
    """A weaker LLM can echo back the wrong fact_type for a base question
    (observed live with the local dev model: a hardship_and_coping answer kept
    getting relabeled study_goal/study_method). Since next_base_question()
    decides a category is done purely by which fact_types have a confirmed
    row, a mislabeled fact makes that base question look permanently
    unanswered and it repeats forever — the "질문에 답해도 다음 단계로 안 넘어감"
    bug (2026-09-05). The server must ignore the LLM's own fact_type and
    always use the hint the question was actually asked under.

    This test is about fact_type forcing specifically, not the total
    per-category question cap, so the cap is raised here to let all 4 fixed
    questions play out and isolate the two concerns.
    """
    monkeypatch.setattr(orchestrator, "MAX_QUESTIONS_PER_CATEGORY", 8)
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time",))

    # First base question's hint is "frequency" — have the fake LLM misreport
    # a completely different fact_type, as the weak local model did.
    session_client.fake_llm._facts_queue = [
        [FactCandidate(content="주 3회 근무했습니다", fact_type="task", based_on=BasedOn(type="generic_pattern"))],
    ]

    for _ in BASE_QUESTIONS["part_time"]:
        _do_turn(session_client, headers, session_id)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = {f["fact_type"] for f in ctx["confirmed_facts"]}
    # Every base question's fact_type is present exactly once — none stuck repeating.
    assert fact_types == {q.fact_type for q in BASE_QUESTIONS["part_time"]}
    assert len(ctx["confirmed_facts"]) == len(BASE_QUESTIONS["part_time"])


def test_followup_question_asked_when_sufficiency_says_not_enough_yet(session_client, monkeypatch):
    """Tests the post-base judge_sufficiency loop specifically, so the total
    per-category question cap is raised here — under the real default (3),
    a category with a 4-question fixed set never reaches the post-base phase
    at all, which is a different behavior covered by its own cap tests."""
    monkeypatch.setattr(orchestrator, "MAX_QUESTIONS_PER_CATEGORY", 8)
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time",))

    session_client.fake_llm._sufficiency_queue = [SufficiencyResult(sufficient=False, reason="아직 부족함")]

    for _ in BASE_QUESTIONS["part_time"]:
        _do_turn(session_client, headers, session_id)

    ask_body, _, confirm_body = _do_turn(session_client, headers, session_id)
    assert ask_body["question_source"] == "followup"
    assert confirm_body["category_done"] is True  # second judge_sufficiency call defaults to True

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = [f["fact_type"] for f in ctx["confirmed_facts"]]
    assert fact_types.count("followup") == 1
    assert len(ctx["confirmed_facts"]) == len(BASE_QUESTIONS["part_time"]) + 1


def test_deeper_category_specific_questions_for_study_and_part_time_differ(session_client):
    """Requirement: different categories get different, domain-tailored questions —
    not the same generic frequency/task/achievement triad for everything."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time", "study"))

    part_time_first_question = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/ask", headers=headers
    ).json()["question_text"]

    assert part_time_first_question == BASE_QUESTIONS["part_time"][0].text
    assert part_time_first_question != BASE_QUESTIONS["study"][0].text


def test_activity_breakdown_splits_category_into_children_and_walks_into_them(session_client):
    """A broad category (e.g. "공모전") containing several distinct activities
    (e.g. two different contests) must be split into separate sub-categories
    so each gets its own fixed-question cycle instead of sharing one
    answered-fact-type tracker (2026-09-06)."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    session_client.fake_llm._activity_items_queue = [["CS336 강의 학습", "Claude Code 가이드 학습"]]
    _advance_to_interviewing(session_client, headers, session_id, category_types=("study",))

    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["question_source"] == "split_check"

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer",
        headers=headers,
        json={"text": "CS336 강의랑 Claude Code 가이드요"},
    )
    candidates = resp.json()["candidates"]
    assert [c["content"] for c in candidates] == ["CS336 강의 학습", "Claude Code 가이드 학습"]

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [{"index": c["index"], "final_text": c["content"], "was_edited": False} for c in candidates]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "INTERVIEWING"
    assert body["category_done"] is False
    assert body["confirmed_facts"] == []  # routing info, not a citable fact

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    study = next(c for c in ctx["categories"] if c["category_type"] == "study" and c["parent_category_id"] is None)
    assert study["status"] == "DONE"  # container — never interviewed directly
    children = [c for c in ctx["categories"] if c["parent_category_id"] == study["id"]]
    assert [c["custom_label"] for c in children] == ["CS336 강의 학습", "Claude Code 가이드 학습"]
    assert ctx["current_category"]["id"] == children[0]["id"]

    # The child gets its own fixed-question cycle, including the new
    # "내용/활용" question added for `study` — not a continuation of the parent's.
    first_question = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert first_question["question_source"] == "base"
    assert first_question["question_text"] == BASE_QUESTIONS["study"][0].text


def test_activity_breakdown_with_a_single_item_does_not_split(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("study",))

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert len(ctx["categories"]) == 1  # _advance_to_first_category's own "하나뿐이에요" didn't split
    assert ctx["categories"][0]["status"] != "DONE"

    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert ask["question_source"] == "base"
    assert ask["question_text"] == BASE_QUESTIONS["study"][0].text


def test_activity_breakdown_review_can_edit_and_add_items_beyond_the_ai_list(session_client):
    """The candidate review screen for this question is the same shared UI as
    normal fact review — editing an item's text ("고쳐 쓰기") or adding a new
    one beyond what the AI proposed must both actually take effect, not just
    silently fall back to the AI's original suggestion (2026-09-06 bug: the
    confirm handler read candidate_facts[index]["content"] — the AI's
    original text — instead of the user's final_text)."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    session_client.fake_llm._activity_items_queue = [["공모전 A"]]
    _advance_to_interviewing(session_client, headers, session_id, category_types=("project",))

    session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "공모전 A요"}
    )
    candidates = resp.json()["candidates"]
    assert len(candidates) == 1

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={
            "confirmations": [
                # Edited to a different name than the AI proposed.
                {"index": 0, "final_text": "공모전 A (수정됨)", "was_edited": True, "include": True},
                # A second item the AI never suggested, added by hand.
                {"index": 1, "final_text": "공모전 B (직접 추가)", "was_edited": True, "include": True},
            ]
        },
    )
    assert resp.status_code == 200

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    parent = next(c for c in ctx["categories"] if c["category_type"] == "project" and c["parent_category_id"] is None)
    children = sorted(
        (c for c in ctx["categories"] if c["parent_category_id"] == parent["id"]),
        key=lambda c: c["order_index"],
    )
    assert [c["custom_label"] for c in children] == ["공모전 A (수정됨)", "공모전 B (직접 추가)"]


def test_child_category_falls_back_to_parents_records_when_it_has_none(session_client):
    """Sub-categories don't get their own record-request step (records are
    only attachable during RECORD_UPLOAD, which is long over by the time a
    split happens mid-interview) — they share the parent's uploaded records
    instead (2026-09-06 decision)."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    session_client.fake_llm._activity_items_queue = [["CS336 강의 학습", "Claude Code 가이드 학습"]]
    _advance_to_interviewing(session_client, headers, session_id, category_types=("study",))

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    parent_id = ctx["categories"][0]["id"]

    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "둘 다요"}
    )
    candidates = resp.json()["candidates"]
    session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [{"index": c["index"], "final_text": c["content"], "was_edited": False} for c in candidates]},
    )

    seen_category_ids = []

    async def fake_chunk_search(session_id_arg, category_id):
        seen_category_ids.append(str(category_id))
        if str(category_id) == parent_id:
            return [RecordChunkExcerpt(chunk_id=uuid.uuid4(), text="부모 카테고리에 올린 자료", published_at=None)]
        return []

    app.dependency_overrides[get_chunk_search] = lambda: fake_chunk_search
    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert len(ctx["available_record_chunks"]) == 1
    assert ctx["available_record_chunks"][0]["text"] == "부모 카테고리에 올린 자료"
    # Child's own id was tried first (and came back empty) before falling back to the parent's.
    assert ctx["current_category"]["id"] in seen_category_ids
    assert parent_id in seen_category_ids


def test_two_categories_second_starts_fresh_after_first_done(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time", "study"))

    confirm_body = None
    for _ in BASE_QUESTIONS["part_time"]:
        # The last of these turns exhausts part_time's fixed set, triggers
        # sufficiency (fake defaults to True), and advances to the next category.
        _, _, confirm_body = _do_turn(session_client, headers, session_id)

    assert confirm_body["status"] == "INTERVIEWING"
    assert confirm_body["current_category_id"] is not None

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["current_category"]["category_type"] == "study"
    part_time = next(c for c in ctx["categories"] if c["category_type"] == "part_time")
    assert part_time["status"] == "DONE"

    # The new category asks its own first base question, not a continuation of
    # part_time's — but first it gets its own "여러 활동 있나요?" check, same as
    # every other freshly-entered category.
    _skip_activity_breakdown(session_client, headers, session_id)
    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert ask["question_text"] == BASE_QUESTIONS["study"][0].text


def test_ask_is_idempotent_without_calling_llm_twice(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    first = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    second = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert first == second


def test_ask_returns_a_draft_answer_to_prefill_the_composer(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.fake_llm._draft_answer_queue = ["주로 저녁 시간대에 근무했어요"]

    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert ask["draft_answer"] == "주로 저녁 시간대에 근무했어요"
    assert session_client.fake_llm.draft_answer_calls == [ask["question_text"]]

    # Idempotent replay (no answer/confirm yet) returns the same cached draft
    # without calling the LLM again.
    again = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert again["draft_answer"] == "주로 저녁 시간대에 근무했어요"
    assert len(session_client.fake_llm.draft_answer_calls) == 1


def test_draft_answer_prefill_does_not_bypass_candidate_confirmation(session_client):
    """Sending the AI's draft answer unedited still goes through the normal
    extract -> review -> confirm steps — prefilling the composer only changes
    what's in the box before the user sends, not the honesty guardrail after."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.fake_llm._draft_answer_queue = ["주 3회 정도 일했어요"]
    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()

    # User sends the draft answer completely as-is.
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer",
        headers=headers,
        json={"text": ask["draft_answer"]},
    )
    candidates = resp.json()["candidates"]
    assert len(candidates) == 1  # extract_facts still ran on the submitted text

    # Nothing is in confirmed_facts until confirm is called explicitly.
    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"] == []


def test_answer_before_ask_returns_409(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "x"}
    )
    assert resp.status_code == 409


def test_confirm_before_answer_returns_409(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm", headers=headers, json={"confirmations": []}
    )
    assert resp.status_code == 409


def test_ask_before_period_returns_409(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)

    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 409


def test_confirm_with_negative_index_returns_409(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    session_client.post(f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "답변"})
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [{"index": -1, "final_text": "x", "was_edited": False}]},
    )
    assert resp.status_code == 409


def test_confirm_with_index_past_the_candidate_list_adds_a_manual_fact(session_client):
    """An index beyond the AI-extracted candidate list is a manually-added
    row (2026-09-06: the candidate review screen — reused for both normal
    fact review and the "여러 활동 있나요?" split-check — needs a way to add
    more entries than the AI proposed, not just edit/exclude existing ones).
    It has no AI draft to compare against, so it's always user_edited."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "답변"})
    candidates = resp.json()["candidates"]
    assert len(candidates) == 1  # the fake LLM's default: one candidate per non-empty answer

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={
            "confirmations": [
                {"index": 0, "final_text": candidates[0]["content"], "was_edited": False, "include": True},
                {"index": 1, "final_text": "AI가 안 뽑아낸, 직접 추가한 사실", "was_edited": True, "include": True},
            ]
        },
    )
    assert resp.status_code == 200
    facts = resp.json()["confirmed_facts"]
    assert len(facts) == 2
    manual_fact = next(f for f in facts if f["content"] == "AI가 안 뽑아낸, 직접 추가한 사실")
    assert manual_fact["source_type"] == "user_edited"


def test_empty_answer_yields_no_candidates_and_does_not_get_stuck(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "   "}
    )
    assert resp.status_code == 200
    assert resp.json()["candidates"] == []

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm", headers=headers, json={"confirmations": []}
    )
    assert resp.status_code == 200
    assert resp.json()["category_done"] is False

    # Loop isn't stuck: the same (still-unanswered) base question comes back.
    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert ask["question_text"] == BASE_QUESTIONS["part_time"][0].text


def test_other_users_session_returns_403_on_every_endpoint(session_client):
    headers_a = _register_and_login(session_client, email="a@example.com")
    session_id = _create_session(session_client, headers_a)
    _advance_to_first_category(session_client, headers_a, session_id)

    headers_b = _register_and_login(session_client, email="b@example.com")

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers_b,
        json={"start_date": "2025-01-01", "end_date": "2025-02-01"},
    )
    assert resp.status_code == 403

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers_b,
        json={"categories": [{"category_type": "study"}]},
    )
    assert resp.status_code == 403

    resp = session_client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers_b)
    assert resp.status_code == 403

    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers_b)
    assert resp.status_code == 403

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm", headers=headers_b, json={"confirmations": []}
    )
    assert resp.status_code == 403

    resp = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers_b)
    assert resp.status_code == 403

    resp = session_client.delete(f"/api/v1/sessions/{session_id}", headers=headers_b)
    assert resp.status_code == 403


def test_was_edited_true_sets_source_type_user_edited(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    _do_turn(session_client, headers, session_id, was_edited=True)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"][0]["source_type"] == "user_edited"


def test_record_based_candidate_confirmed_unedited_is_record_cited(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    # Must contain a non-digit hex character - an all-digit UUID string gets
    # silently mangled by SQLite's NUMERIC column-affinity conversion.
    chunk_id = str(uuid.uuid4())

    async def fake_chunk_search(session_id_arg, label):
        return [RecordChunkExcerpt(chunk_id=uuid.UUID(chunk_id), text="근무 기록", published_at=None)]

    app.dependency_overrides[get_chunk_search] = lambda: fake_chunk_search
    session_client.fake_llm._facts_queue = [
        [
            FactCandidate(
                content="주 3회 카페 아르바이트를 했다",
                fact_type="frequency",
                based_on=BasedOn(type="record", excerpts=[RecordExcerpt(chunk_id=chunk_id, text="근무 기록", published_at=None)]),
            )
        ]
    ]
    _do_turn(session_client, headers, session_id, was_edited=False)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"][0]["source_type"] == "record_cited"


def test_record_cited_claim_for_unshown_chunk_id_is_downgraded_to_generic_pattern(session_client):
    """Honesty guardrail: the LLM cannot claim record_cited for a chunk_id that
    wasn't actually part of this turn's context (chunk_search stubbed to []
    by session_client, so any chunk_id the fake claims is unverifiable)."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    fabricated_chunk_id = str(uuid.uuid4())
    session_client.fake_llm._facts_queue = [
        [
            FactCandidate(
                content="주 3회 카페 아르바이트를 했다",
                fact_type="frequency",
                based_on=BasedOn(
                    type="record",
                    excerpts=[RecordExcerpt(chunk_id=fabricated_chunk_id, text="근무 기록", published_at=None)],
                ),
            )
        ]
    ]
    _do_turn(session_client, headers, session_id, was_edited=False)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"][0]["source_type"] == "user_confirmed"


def test_generic_pattern_candidate_confirmed_unedited_is_user_confirmed(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    _do_turn(session_client, headers, session_id, was_edited=False)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"][0]["source_type"] == "user_confirmed"


def test_excluded_candidate_is_not_persisted(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "답변"}
    )
    candidates = resp.json()["candidates"]
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [{"index": c["index"], "final_text": c["content"], "was_edited": False, "include": False} for c in candidates]},
    )
    assert resp.status_code == 200
    assert resp.json()["confirmed_facts"] == []

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"] == []


def test_max_questions_per_category_forces_advance_even_with_llm_never_satisfied(session_client):
    """MAX_QUESTIONS_PER_CATEGORY (2026-09-05: lowered to 3 on request —
    "카테고리당 질문 횟수를 늘리자. 3회까지") is a hard ceiling on the TOTAL number
    of questions (fixed + AI-added combined), not just AI follow-ups on top of
    an already-exhausted fixed set — so it must force an advance even while
    judge_drilldown/judge_sufficiency would keep wanting more, and even while
    part_time's fixed set (4 questions) still has one left unasked."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.fake_llm._sufficiency_queue = [SufficiencyResult(sufficient=False, reason="never enough")] * 10
    session_client.fake_llm._drilldown_queue = [DrilldownDecision(should_ask=True, question_text="더 자세히 말해주세요")] * 10

    confirm_body = None
    for _ in range(MAX_QUESTIONS_PER_CATEGORY):
        _, _, confirm_body = _do_turn(session_client, headers, session_id)

    assert confirm_body["category_done"] is True
    assert confirm_body["status"] == "RESULT_GENERATE"


def test_session_create_and_delete(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)

    resp = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "PERIOD_INPUT"

    resp = session_client.delete(f"/api/v1/sessions/{session_id}", headers=headers)
    assert resp.status_code == 204

    resp = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers)
    assert resp.status_code == 404
