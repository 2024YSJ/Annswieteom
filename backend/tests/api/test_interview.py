from __future__ import annotations

import uuid

from app.main import app
from app.services import interview_orchestrator as orchestrator
from app.services.interview_orchestrator import MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY
from app.services.interview_question_bank import BASE_QUESTIONS
from app.services.llm.base import LLMUnavailableError, BasedOn, DrilldownDecision, FactCandidate, RecordExcerpt, SufficiencyResult
from app.services.llm import get_llm_provider
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

    # Fixed questions are never truncated by the followup budget (2026-09-06)
    # — all of part_time's questions are reached, in order.
    expected_questions = BASE_QUESTIONS["part_time"]
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
    # not yet answered; then hardship, outcome) are never budget-capped, so
    # the interview keeps going through the rest of the fixed set as normal
    # regardless of how much of the (separate) followup budget the one
    # drill-down above used.
    for _ in BASE_QUESTIONS["project"][1:]:
        _, _, confirm_body = _do_turn(session_client, headers, session_id)

    assert confirm_body["category_done"] is True
    assert confirm_body["status"] == "RESULT_GENERATE"

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = [f["fact_type"] for f in ctx["confirmed_facts"]]
    assert fact_types.count("followup") == 1
    assert set(fact_types) == {q.fact_type for q in BASE_QUESTIONS["project"]} | {"followup"}
    assert len(fact_types) == len(BASE_QUESTIONS["project"]) + 1


def test_candidate_fact_type_is_forced_to_the_question_hint_not_the_llm_choice(session_client):
    """A weaker LLM can echo back the wrong fact_type for a base question
    (observed live with the local dev model: a hardship_and_coping answer kept
    getting relabeled study_goal/study_method). Since next_base_question()
    decides a category is done purely by which fact_types have a confirmed
    row, a mislabeled fact makes that base question look permanently
    unanswered and it repeats forever — the "질문에 답해도 다음 단계로 안 넘어감"
    bug (2026-09-05). The server must ignore the LLM's own fact_type and
    always use the hint the question was actually asked under.
    """
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


def test_followup_question_asked_when_sufficiency_says_not_enough_yet(session_client):
    """Tests the post-base judge_sufficiency loop specifically — fixed
    questions are never budget-capped (2026-09-06), so a 4-question fixed
    set always reaches this post-base phase regardless of the (separate,
    still-untouched) followup budget."""
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

    async def fake_chunk_search(session_id_arg, category_id, query_text=None):
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

    async def fake_chunk_search(session_id_arg, category_id, query_text=None):
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


def test_followup_budget_caps_ai_questions_but_never_skips_a_fixed_one(session_client):
    """Regression guard for the 2026-09-06 redesign: the old single shared
    cap (MAX_QUESTIONS_PER_CATEGORY) could force a category to advance
    before its fixed "achievement" question (STAR's Result) was ever asked,
    if AI-added drill-downs had already eaten the whole budget. Now the
    followup/drill-down budget (MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY) is
    tracked separately and only caps AI-added questions — even an LLM that
    wants to drill down after every single answer can't stop all of
    part_time's 4 fixed questions from eventually being asked."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.fake_llm._sufficiency_queue = [SufficiencyResult(sufficient=False, reason="never enough")] * 10
    session_client.fake_llm._drilldown_queue = [DrilldownDecision(should_ask=True, question_text="더 자세히 말해주세요")] * 10

    asked_base_questions: list[str] = []
    followup_count = 0
    confirm_body = {"category_done": False}
    for _ in range(20):  # generous safety cap against an infinite loop bug
        if confirm_body["category_done"]:
            break
        ask_body, _, confirm_body = _do_turn(session_client, headers, session_id)
        if ask_body["question_source"] == "base":
            asked_base_questions.append(ask_body["question_text"])
        else:
            followup_count += 1

    assert confirm_body["category_done"] is True
    assert confirm_body["status"] == "RESULT_GENERATE"
    # All 4 fixed questions landed, in order, despite the LLM wanting to
    # drill down after every one of them.
    assert asked_base_questions == [q.text for q in BASE_QUESTIONS["part_time"]]
    # The AI-added budget was fully used but not exceeded.
    assert followup_count == MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = [f["fact_type"] for f in ctx["confirmed_facts"]]
    assert fact_types.count("followup") == MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY
    assert len(fact_types) == len(BASE_QUESTIONS["part_time"]) + MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY


def test_drilldown_heuristic_backup_probes_a_vague_answer_when_all_llm_providers_fail(session_client):
    """When judge_drilldown itself can't be called because every LLM
    provider is down (the known local-dev limitation: a placeholder
    GEMINI_API_KEY means the fallback provider can't rescue a local model's
    malformed JSON), a rule-based backup still guarantees at least a minimal
    probe for an answer too short to be useful — instead of silently moving
    straight to the next fixed question (2026-09-06)."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("project",))

    class DrilldownFailingProvider:
        def __getattr__(self, name):
            return getattr(session_client.fake_llm, name)

        async def judge_drilldown(self, context):
            raise LLMUnavailableError()

    app.dependency_overrides[get_llm_provider] = lambda: DrilldownFailingProvider()
    try:
        session_client.fake_llm._facts_queue = [
            [FactCandidate(content="개발함", fact_type="task", based_on=BasedOn(type="generic_pattern"))],
        ]
        _, _, confirm_body = _do_turn(session_client, headers, session_id, answer_text="개발함")
        assert confirm_body["category_done"] is False

        resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
        assert resp.json()["question_source"] == "followup"
        assert "구체적으로" in resp.json()["question_text"]
    finally:
        app.dependency_overrides[get_llm_provider] = lambda: session_client.fake_llm


def test_drilldown_heuristic_backup_does_not_probe_a_detailed_answer(session_client):
    """The rule-based backup (see test above) must not over-trigger — a
    reasonably detailed answer shouldn't get an extra probe question just
    because the LLM providers happened to be unavailable that turn."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("project",))

    class DrilldownFailingProvider:
        def __getattr__(self, name):
            return getattr(session_client.fake_llm, name)

        async def judge_drilldown(self, context):
            raise LLMUnavailableError()

    app.dependency_overrides[get_llm_provider] = lambda: DrilldownFailingProvider()
    try:
        detailed_answer = "학교 축제 웹사이트 예약 시스템을 기획하고 백엔드 API를 FastAPI로 직접 개발했습니다"
        session_client.fake_llm._facts_queue = [
            [FactCandidate(content=detailed_answer, fact_type="task", based_on=BasedOn(type="generic_pattern"))],
        ]
        _, _, confirm_body = _do_turn(session_client, headers, session_id, answer_text=detailed_answer)
        assert confirm_body["category_done"] is False

        resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
        # No drill-down interjected — straight to the second fixed question.
        assert resp.json()["question_source"] == "base"
        assert resp.json()["question_text"] == BASE_QUESTIONS["project"][1].text
    finally:
        app.dependency_overrides[get_llm_provider] = lambda: session_client.fake_llm


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


# ---------------------------------------------------------------------------
# 질문 문구 기반 기록물 검색 + 활동 기간 유추 (2026-09-09)
# ---------------------------------------------------------------------------


def test_record_search_is_keyed_on_the_question_being_asked(session_client):
    """검색어 없이 카테고리 청크를 작성순으로 자르던 예전 동작에서는
    record_chunks.embedding이 한 번도 조회되지 않았다 — 질문 문구가 실제로
    검색어로 내려가야 벡터 검색이 의미를 갖는다."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    category_id = _advance_to_first_category(session_client, headers, session_id)

    queries = []

    async def recording_chunk_search(session_id_arg, category_id_arg, query_text=None):
        queries.append(query_text)
        return []

    app.dependency_overrides[get_chunk_search] = lambda: recording_chunk_search

    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 200
    question_text = resp.json()["question_text"]
    assert question_text == BASE_QUESTIONS["part_time"][0].text

    assert queries, "chunk_search was never called"
    assert queries[-1] == question_text


def test_structural_split_check_searches_without_a_query(session_client):
    """"여러 활동 있나요?"는 라우팅 질문이라 근거로 삼을 기록물이 없다 —
    임베딩 호출을 낭비하지 않는다."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_interviewing(session_client, headers, session_id)

    queries = []

    async def recording_chunk_search(session_id_arg, category_id_arg, query_text=None):
        queries.append(query_text)
        return []

    app.dependency_overrides[get_chunk_search] = lambda: recording_chunk_search

    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.json()["question_source"] == "split_check"
    assert queries == [None]


def test_activity_period_is_inferred_once_a_frequency_fact_is_confirmed(session_client):
    """기간을 카테고리가 끝날 때까지 기다리지 않고 여기서 잡아야, 후속 질문
    예산과 커버리지가 인터뷰 도중에도 의미를 갖는다."""
    from datetime import date

    from app.services.llm.base import PeriodSuggestion

    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.fake_llm._activity_period = PeriodSuggestion(
        start_date=date(2025, 1, 1), end_date=date(2025, 3, 31)
    )
    # part_time의 첫 고정 질문이 frequency다. 답변에 기간 단서("3개월")가 있어야
    # LLM에 물어보기라도 한다 — 단서가 없으면 has_period_clue 게이트가 먼저 막는다.
    _do_turn(session_client, headers, session_id, answer_text="3개월 동안 주 3회 일했어요")

    assert session_client.fake_llm.activity_period_calls
    coverage = session_client.get(f"/api/v1/sessions/{session_id}/coverage", headers=headers).json()
    assert coverage["covered_days"] == 90
    assert coverage["categories_without_period"] == []


def test_user_set_period_is_not_overwritten_by_inference(session_client):
    from datetime import date

    from app.services.llm.base import PeriodSuggestion

    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    category_id = _advance_to_first_category(session_client, headers, session_id)

    session_client.patch(
        f"/api/v1/sessions/{session_id}/categories/{category_id}/period",
        headers=headers,
        json={"start_date": "2025-02-01", "end_date": "2025-02-28"},
    )
    session_client.fake_llm._activity_period = PeriodSuggestion(
        start_date=date(2025, 1, 1), end_date=date(2025, 6, 30)
    )
    _do_turn(session_client, headers, session_id, answer_text="3개월 동안 주 3회 일했어요")

    assert session_client.fake_llm.activity_period_calls == []
    coverage = session_client.get(f"/api/v1/sessions/{session_id}/coverage", headers=headers).json()
    assert coverage["covered_days"] == 28


def test_inference_failure_leaves_the_category_without_a_period(session_client):
    """기간은 커버리지용 메타데이터일 뿐이라, 못 구했다고 인터뷰 턴이
    실패하면 안 된다."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    async def exploding_period(*args, **kwargs):
        raise LLMUnavailableError()

    session_client.fake_llm.extract_activity_period = exploding_period

    _ask, _candidates, confirm_body = _do_turn(session_client, headers, session_id)
    assert confirm_body["status"] == "INTERVIEWING"

    coverage = session_client.get(f"/api/v1/sessions/{session_id}/coverage", headers=headers).json()
    assert len(coverage["categories_without_period"]) == 1


def test_long_activities_get_a_bigger_followup_budget(session_client):
    """6개월을 통째로 쓴 활동과 2주짜리 활동을 똑같이 3턴으로 끊으면,
    공백기를 실제로 메우고 있는 쪽에 시간을 덜 주는 셈이다."""
    from datetime import date

    class ShortCategory:
        period_start = date(2025, 1, 1)
        period_end = date(2025, 1, 14)

    class LongCategory:
        period_start = date(2025, 1, 1)
        period_end = date(2025, 6, 30)

    class UnknownCategory:
        period_start = None
        period_end = None

    assert orchestrator.followup_budget(ShortCategory()) == MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY
    assert orchestrator.followup_budget(UnknownCategory()) == MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY
    assert orchestrator.followup_budget(LongCategory()) > MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY
