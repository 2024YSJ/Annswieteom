from __future__ import annotations

import asyncio
import uuid

from app.main import app
from app.models.session import Session as SessionModel
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
    defaults to returning no items, so this never actually splits. This check
    is still confirmed immediately (it's routing, not a fact)."""
    resp = client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["question_source"] == "split_check"

    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "하나뿐이에요"}
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "candidates"
    candidates = resp.json()["candidates"]

    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [{"index": c["index"], "final_text": c["content"], "was_edited": False} for c in candidates]},
    )
    assert resp.status_code == 200
    assert resp.json()["category_done"] is False


def _answer(client, headers, session_id, answer_text="답변입니다"):
    """ask (idempotent — returns the pending question) -> answer. Since the
    category-level review (2026-09-11) the answer is stored as a draft and the
    response carries the next question (mode="question") or the category's
    review (mode="review")."""
    resp = client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 200
    ask_body = resp.json()
    assert ask_body["mode"] == "question", ask_body

    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": answer_text}
    )
    assert resp.status_code == 200, resp.text
    return ask_body, resp.json()


def _answer_until_review(client, headers, session_id, answer_text="답변입니다", max_turns=20):
    """Answers until the category asks for review. Returns (asked, review)."""
    asked = []
    for _ in range(max_turns):  # generous safety cap against an infinite loop bug
        ask_body, answer_body = _answer(client, headers, session_id, answer_text)
        asked.append(ask_body)
        if answer_body["mode"] == "review":
            return asked, answer_body["review"]
    raise AssertionError("the category never reached its review")


def _all_confirmations(review, was_edited=False, include=True):
    return [
        {"turn_id": g["turn_id"], "index": d["index"], "final_text": d["content"], "was_edited": was_edited, "include": include}
        for g in review["groups"]
        for d in g["drafts"]
    ]


def _submit_review(client, headers, session_id, confirmations=None, was_edited=False, include=True):
    resp = client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    body = resp.json()
    assert body["mode"] == "review", body
    if confirmations is None:
        confirmations = _all_confirmations(body["review"], was_edited=was_edited, include=include)
    resp = client.post(
        f"/api/v1/sessions/{session_id}/interview/review", headers=headers, json={"confirmations": confirmations}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _finish_category(client, headers, session_id, answer_text="답변입니다", was_edited=False, include=True):
    asked, _ = _answer_until_review(client, headers, session_id, answer_text)
    return asked, _submit_review(client, headers, session_id, was_edited=was_edited, include=include)


def _update_session(client, session_id, **fields):
    async def _run():
        async with client.session_local() as db:
            row = await db.get(SessionModel, uuid.UUID(session_id))
            for key, value in fields.items():
                setattr(row, key, value)
            await db.commit()

    asyncio.run(_run())


def test_base_questions_asked_in_order_for_part_time(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time",))

    # Fixed questions are never truncated by the followup budget (2026-09-06)
    # — all of part_time's questions are reached, in order, without any
    # per-answer confirmation in between.
    expected_questions = BASE_QUESTIONS["part_time"]
    for i, expected in enumerate(expected_questions):
        ask_body, answer_body = _answer(session_client, headers, session_id)
        assert ask_body["question_text"] == expected.text
        assert ask_body["question_source"] == "base"
        is_last = i == len(expected_questions) - 1
        assert answer_body["mode"] == ("review" if is_last else "question")

    review_body = _submit_review(session_client, headers, session_id)
    assert review_body["category_done"] is True
    assert review_body["status"] == "RESULT_GENERATE"
    assert review_body["current_category_id"] is None

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

    # Turn 1: answer the first fixed question. The drilldown decision above
    # fires during this answer call and comes back as the next question.
    first_base_question = BASE_QUESTIONS["project"][0]
    ask_body, answer_body = _answer(session_client, headers, session_id, answer_text="기획과 개발을 담당했어요")
    assert ask_body["question_text"] == first_base_question.text
    assert answer_body["mode"] == "question"
    assert answer_body["question"]["question_text"] == drilldown_question
    assert answer_body["question"]["question_source"] == "followup"

    # /ask returns the same pending drill-down (idempotent, cached).
    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.json()["question_text"] == drilldown_question
    assert resp.json()["question_source"] == "followup"

    # Answering it resumes the fixed sequence at the second question — the
    # drilldown queue is now empty (defaults to should_ask=False).
    _, answer_body = _answer(session_client, headers, session_id, answer_text="새로운 캠퍼스 배달 서비스 아이디어를 냈어요")
    assert answer_body["mode"] == "question"
    assert answer_body["question"]["question_text"] == BASE_QUESTIONS["project"][1].text
    assert answer_body["question"]["question_source"] == "base"

    for _ in BASE_QUESTIONS["project"][1:]:
        _, answer_body = _answer(session_client, headers, session_id)
    assert answer_body["mode"] == "review"

    review_body = _submit_review(session_client, headers, session_id)
    assert review_body["status"] == "RESULT_GENERATE"

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = [f["fact_type"] for f in ctx["confirmed_facts"]]
    assert fact_types.count("followup") == 1
    assert set(fact_types) == {q.fact_type for q in BASE_QUESTIONS["project"]} | {"followup"}
    assert len(fact_types) == len(BASE_QUESTIONS["project"]) + 1


def test_candidate_fact_type_is_forced_to_the_question_hint_not_the_llm_choice(session_client):
    """A weaker LLM can echo back the wrong fact_type for a base question
    (observed live with the local dev model). Progress is decided by which
    fact_types were answered, so a mislabeled fact would make that base
    question look permanently unanswered and it would repeat forever — the
    "질문에 답해도 다음 단계로 안 넘어감" bug (2026-09-05). The server must use
    the hint the question was actually asked under."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time",))

    session_client.fake_llm._facts_queue = [
        [FactCandidate(content="주 3회 근무했습니다", fact_type="task", based_on=BasedOn(type="generic_pattern"))],
    ]

    asked, _ = _finish_category(session_client, headers, session_id)
    assert len(asked) == len(BASE_QUESTIONS["part_time"])

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = {f["fact_type"] for f in ctx["confirmed_facts"]}
    assert fact_types == {q.fact_type for q in BASE_QUESTIONS["part_time"]}
    assert len(ctx["confirmed_facts"]) == len(BASE_QUESTIONS["part_time"])


def test_followup_question_asked_when_sufficiency_says_not_enough_yet(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time",))

    session_client.fake_llm._sufficiency_queue = [SufficiencyResult(sufficient=False, reason="아직 부족함")]

    asked, review_body = _finish_category(session_client, headers, session_id)
    assert [a["question_source"] for a in asked].count("followup") == 1
    assert asked[-1]["question_source"] == "followup"
    assert review_body["category_done"] is True

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = [f["fact_type"] for f in ctx["confirmed_facts"]]
    assert fact_types.count("followup") == 1
    assert len(ctx["confirmed_facts"]) == len(BASE_QUESTIONS["part_time"]) + 1


def test_deeper_category_specific_questions_for_study_and_part_time_differ(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time", "study"))

    part_time_first_question = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/ask", headers=headers
    ).json()["question_text"]

    assert part_time_first_question == BASE_QUESTIONS["part_time"][0].text
    assert part_time_first_question != BASE_QUESTIONS["study"][0].text


def test_activity_breakdown_splits_category_into_children_and_walks_into_them(session_client):
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

    first_question = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert first_question["question_source"] == "base"
    assert first_question["question_text"] == BASE_QUESTIONS["study"][0].text


def test_ask_restores_pending_candidates_instead_of_regenerating_split_check(session_client):
    """Regression test for the 2026-09-12 bug: calling /interview/ask again (e.g. a
    page refresh) while a split-check answer's candidates are extracted but not yet
    confirmed must not discard them and re-ask the same split-check question."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    session_client.fake_llm._activity_items_queue = [["CS336 강의 학습", "Claude Code 가이드 학습"]]
    _advance_to_interviewing(session_client, headers, session_id, category_types=("study",))

    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    split_check_question_text = resp.json()["question_text"]
    assert resp.json()["question_source"] == "split_check"

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer",
        headers=headers,
        json={"text": "CS336 강의랑 Claude Code 가이드요"},
    )
    assert resp.json()["mode"] == "candidates"
    candidates = resp.json()["candidates"]
    assert [c["content"] for c in candidates] == ["CS336 강의 학습", "Claude Code 가이드 학습"]

    # Simulate a page refresh / duplicate /ask call before confirming.
    resp = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "candidates"
    assert [c["content"] for c in body["candidates"]] == ["CS336 강의 학습", "Claude Code 가이드 학습"]
    # question_text/source must come back too — the frontend's candidate-card
    # render is gated on a truthy question_text (InterviewChatThread.tsx), so
    # omitting these leaves the whole panel blank after a refresh even though
    # the candidates themselves are correctly restored (caught live 2026-09-13).
    assert body["question_text"] == split_check_question_text
    assert body["question_source"] == "split_check"

    # Confirming still works normally afterward — nothing was lost.
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm",
        headers=headers,
        json={"confirmations": [{"index": c["index"], "final_text": c["content"], "was_edited": False} for c in candidates]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "INTERVIEWING"


def test_activity_breakdown_with_a_single_item_does_not_split(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("study",))

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert len(ctx["categories"]) == 1
    assert ctx["categories"][0]["status"] != "DONE"

    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert ask["question_source"] == "base"
    assert ask["question_text"] == BASE_QUESTIONS["study"][0].text


def test_activity_breakdown_review_can_edit_and_add_items_beyond_the_ai_list(session_client):
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
                {"index": 0, "final_text": "공모전 A (수정됨)", "was_edited": True, "include": True},
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
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    session_client.fake_llm._activity_items_queue = [["CS336 강의 학습", "Claude Code 가이드 학습"]]
    _advance_to_interviewing(session_client, headers, session_id, category_types=("study",))

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    parent_id = ctx["categories"][0]["id"]

    session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
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
    assert ctx["current_category"]["id"] in seen_category_ids
    assert parent_id in seen_category_ids


def test_two_categories_second_starts_fresh_after_first_done(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time", "study"))

    _, review_body = _finish_category(session_client, headers, session_id)
    assert review_body["status"] == "INTERVIEWING"
    assert review_body["current_category_id"] is not None

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["current_category"]["category_type"] == "study"
    part_time = next(c for c in ctx["categories"] if c["category_type"] == "part_time")
    assert part_time["status"] == "DONE"
    assert part_time["draft_turns"] == []  # moved into confirmed_facts by the review

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


def test_ask_never_prefills_the_composer(session_client):
    """입력창 자동 채우기(draft_answer)는 2026-09-12 사용자 요청으로 제거했다.
    응답에 그 필드가 없어야 하고, 프로바이더에 초안 생성 메서드 자체가 없어야 한다 —
    되살아나면 질문마다 LLM 호출이 하나 다시 붙는다."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert ask["question_text"] == BASE_QUESTIONS["part_time"][0].text
    assert "draft_answer" not in ask
    assert not hasattr(get_llm_provider(), "draft_answer")


def test_the_next_question_comes_with_the_answer_and_needs_no_prefill(session_client):
    """/answer가 이미 다음 질문을 싣고 온다 — 프론트가 초안을 받으러 /ask를 한 번 더
    부르던 왕복이 사라졌으므로, 그 응답의 질문에도 초안 필드가 없어야 한다."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    _, answer_body = _answer(session_client, headers, session_id)
    assert answer_body["question"]["question_text"] == BASE_QUESTIONS["part_time"][1].text
    assert "draft_answer" not in answer_body["question"]

    # 확인 절차는 그대로 — 답변에서 뽑은 사실은 아직 초안일 뿐이다.
    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"] == []


# ---------------------------------------------------------------------------
# 카테고리 단위 확인 (2026-09-11)
# ---------------------------------------------------------------------------


def test_no_confirmed_facts_exist_until_the_category_review(session_client):
    """정직성 가드레일: 답변에서 뽑은 사실은 확인 전까지 초안일 뿐 confirmed_facts에 없다."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    _answer(session_client, headers, session_id, "주 3회 일했어요")
    _answer(session_client, headers, session_id, "재고 정리를 맡았어요")

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"] == []
    turns = ctx["current_category"]["draft_turns"]
    assert [t["answer_text"] for t in turns] == ["주 3회 일했어요", "재고 정리를 맡았어요"]
    assert [t["question_text"] for t in turns] == [q.text for q in BASE_QUESTIONS["part_time"][:2]]


def test_last_answer_returns_the_review_grouped_by_question(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    answers = [f"{i}번째 답변" for i in range(len(BASE_QUESTIONS["part_time"]))]
    for text in answers:
        _, answer_body = _answer(session_client, headers, session_id, text)

    assert answer_body["mode"] == "review"
    groups = answer_body["review"]["groups"]
    assert [g["question_text"] for g in groups] == [q.text for q in BASE_QUESTIONS["part_time"]]
    assert [g["answer_text"] for g in groups] == answers
    assert [[d["content"] for d in g["drafts"]] for g in groups] == [[a] for a in answers]
    assert [g["fact_type"] for g in groups] == [q.fact_type for q in BASE_QUESTIONS["part_time"]]


def test_ask_during_review_returns_the_review_without_calling_the_llm(session_client):
    """새로고침 복원 경로 — 확인 대기 중인 /ask는 LLM을 부르지 않는다."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    _answer_until_review(session_client, headers, session_id)

    fake = session_client.fake_llm
    before = (
        len(fake.extract_facts_calls), len(fake.drilldown_calls),
        len(fake.sufficiency_calls), len(fake.followup_calls),
    )
    for _ in range(2):
        body = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
        assert body["mode"] == "review"
        assert len(body["review"]["groups"]) == len(BASE_QUESTIONS["part_time"])
    after = (
        len(fake.extract_facts_calls), len(fake.drilldown_calls),
        len(fake.sufficiency_calls), len(fake.followup_calls),
    )
    assert after == before


def test_answering_while_a_review_is_pending_returns_409(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    _answer_until_review(session_client, headers, session_id)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "더 할 말"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "category_review_pending"


def test_review_cannot_be_submitted_twice(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id, category_types=("part_time", "study"))
    _, review = _answer_until_review(session_client, headers, session_id)
    confirmations = _all_confirmations(review)

    first = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/review", headers=headers, json={"confirmations": confirmations}
    )
    assert first.status_code == 200
    second = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/review", headers=headers, json={"confirmations": confirmations}
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "no_pending_review"

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert len(ctx["confirmed_facts"]) == len(BASE_QUESTIONS["part_time"])  # not doubled


def test_review_with_an_unknown_turn_or_negative_index_returns_409(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    _, review = _answer_until_review(session_client, headers, session_id)
    turn_id = review["groups"][0]["turn_id"]

    for bad in (
        {"turn_id": "not-a-turn", "index": 0, "final_text": "x", "was_edited": False},
        {"turn_id": turn_id, "index": -1, "final_text": "x", "was_edited": False},
    ):
        resp = session_client.post(
            f"/api/v1/sessions/{session_id}/interview/review", headers=headers, json={"confirmations": [bad]}
        )
        assert resp.status_code == 409


def test_review_can_add_a_fact_beyond_the_ai_drafts(session_client):
    """An index past a turn's drafts is a row the user added — it has no AI
    draft to compare against, so it's always user_edited."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    _, review = _answer_until_review(session_client, headers, session_id)

    first = review["groups"][0]
    confirmations = _all_confirmations(review) + [
        {"turn_id": first["turn_id"], "index": len(first["drafts"]), "final_text": "AI가 안 뽑아낸, 직접 추가한 사실", "was_edited": True}
    ]
    body = _submit_review(session_client, headers, session_id, confirmations=confirmations)

    manual = next(f for f in body["confirmed_facts"] if f["content"] == "AI가 안 뽑아낸, 직접 추가한 사실")
    assert manual["source_type"] == "user_edited"
    assert manual["fact_type"] == first["fact_type"]
    assert manual["source_question_text"] == first["question_text"]


def test_client_cannot_claim_a_source_type(session_client):
    """source_type/fact_type are derived only from the stored draft turn —
    an extra field in the request is ignored."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    _, review = _answer_until_review(session_client, headers, session_id)

    confirmations = [
        {**c, "source_type": "record_cited", "fact_type": "achievement"} for c in _all_confirmations(review)
    ]
    body = _submit_review(session_client, headers, session_id, confirmations=confirmations)
    assert {f["source_type"] for f in body["confirmed_facts"]} == {"user_confirmed"}
    assert [f["fact_type"] for f in body["confirmed_facts"]] == [q.fact_type for q in BASE_QUESTIONS["part_time"]]


def test_review_snapshots_confirmed_facts_into_each_archived_answer(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    _, review = _answer_until_review(session_client, headers, session_id)

    # The first answer's fact is excluded, the rest confirmed as-is.
    confirmations = _all_confirmations(review)
    confirmations[0]["include"] = False
    _submit_review(session_client, headers, session_id, confirmations=confirmations)

    answers = session_client.get("/api/v1/me/answers", headers=headers).json()
    by_question = {a["question_text"]: a for a in answers}
    first_question = BASE_QUESTIONS["part_time"][0].text
    assert by_question[first_question]["confirmed_facts"] == []
    assert all(
        len(a["confirmed_facts"]) == 1 for q, a in by_question.items() if q != first_question
    )


def test_legacy_pending_candidates_are_absorbed_as_drafts(session_client):
    """A session caught mid-turn by the deploy (old per-answer candidates in
    pending_turn) continues: those candidates become a draft turn."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    category_id = _advance_to_first_category(session_client, headers, session_id)

    first = BASE_QUESTIONS["part_time"][0]
    _update_session(
        session_client,
        session_id,
        pending_turn={
            "category_id": category_id,
            "question_text": first.text,
            "question_source": "base",
            "fact_type_hint": first.fact_type,
            "candidate_facts": [
                {"content": "옛 방식에서 뽑힌 사실", "fact_type": first.fact_type, "based_on": {"type": "generic_pattern", "excerpts": []}}
            ],
        },
    )

    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert ask["question_text"] == BASE_QUESTIONS["part_time"][1].text

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert [t["question_text"] for t in ctx["current_category"]["draft_turns"]] == [first.text]


def test_drafts_survive_the_pending_turn_being_cleared(session_client):
    """Drafts live on the category, not in sessions.pending_turn — paths that
    reset pending_turn (a failed next-question LLM call, coverage, …) must not
    lose answered turns or re-ask them."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    _answer(session_client, headers, session_id)

    _update_session(session_client, session_id, pending_turn=None)

    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert ask["question_text"] == BASE_QUESTIONS["part_time"][1].text


def test_coverage_fill_is_blocked_while_drafts_are_pending(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    _answer(session_client, headers, session_id)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/coverage/fill",
        headers=headers,
        json={"start_date": "2025-03-01", "end_date": "2025-04-30"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "category_review_pending"


def test_confirm_is_only_for_the_split_check(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)
    _answer(session_client, headers, session_id)

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/confirm", headers=headers, json={"confirmations": []}
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------


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


def test_blank_answer_is_rejected_and_the_question_stays(session_client):
    """A blank answer would count as "answered" (progress counts turns), so it's
    rejected before any LLM call instead of silently skipping the question."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers)
    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/answer", headers=headers, json={"text": "   "}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "empty_answer"
    assert session_client.fake_llm.extract_facts_calls == []

    ask = session_client.post(f"/api/v1/sessions/{session_id}/interview/ask", headers=headers).json()
    assert ask["question_text"] == BASE_QUESTIONS["part_time"][0].text


def test_an_answer_with_nothing_extracted_still_moves_on_and_appears_in_the_review(session_client):
    """"잘 모르겠어요" yields no facts but still answers the question — it must
    not repeat forever, and the review lets the user add a fact for it."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.fake_llm._facts_queue = [[]]
    _, answer_body = _answer(session_client, headers, session_id, "잘 모르겠어요")
    assert answer_body["question"]["question_text"] == BASE_QUESTIONS["part_time"][1].text

    _, review = _answer_until_review(session_client, headers, session_id)
    assert review["groups"][0]["drafts"] == []
    assert review["groups"][0]["answer_text"] == "잘 모르겠어요"


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

    resp = session_client.post(
        f"/api/v1/sessions/{session_id}/interview/review", headers=headers_b, json={"confirmations": []}
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

    _finish_category(session_client, headers, session_id, was_edited=True)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert {f["source_type"] for f in ctx["confirmed_facts"]} == {"user_edited"}


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
    _finish_category(session_client, headers, session_id)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact = next(f for f in ctx["confirmed_facts"] if f["content"] == "주 3회 카페 아르바이트를 했다")
    assert fact["source_type"] == "record_cited"


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
    _finish_category(session_client, headers, session_id)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact = next(f for f in ctx["confirmed_facts"] if f["content"] == "주 3회 카페 아르바이트를 했다")
    assert fact["source_type"] == "user_confirmed"


def test_generic_pattern_candidate_confirmed_unedited_is_user_confirmed(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    _finish_category(session_client, headers, session_id)

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert {f["source_type"] for f in ctx["confirmed_facts"]} == {"user_confirmed"}


def test_excluded_drafts_are_not_persisted(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    _, review_body = _finish_category(session_client, headers, session_id, include=False)
    assert review_body["confirmed_facts"] == []

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert ctx["confirmed_facts"] == []


def test_followup_budget_caps_ai_questions_but_never_skips_a_fixed_one(session_client):
    """Regression guard for the 2026-09-06 redesign: the followup/drill-down
    budget only caps AI-added questions — even an LLM that wants to drill down
    after every single answer can't stop all fixed questions from being asked."""
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.fake_llm._sufficiency_queue = [SufficiencyResult(sufficient=False, reason="never enough")] * 10
    session_client.fake_llm._drilldown_queue = [DrilldownDecision(should_ask=True, question_text="더 자세히 말해주세요")] * 10

    asked, review_body = _finish_category(session_client, headers, session_id)
    asked_base_questions = [a["question_text"] for a in asked if a["question_source"] == "base"]
    followup_count = sum(1 for a in asked if a["question_source"] == "followup")

    assert review_body["status"] == "RESULT_GENERATE"
    assert asked_base_questions == [q.text for q in BASE_QUESTIONS["part_time"]]
    assert followup_count == MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY

    ctx = session_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    fact_types = [f["fact_type"] for f in ctx["confirmed_facts"]]
    assert fact_types.count("followup") == MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY
    assert len(fact_types) == len(BASE_QUESTIONS["part_time"]) + MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY


def test_drilldown_heuristic_backup_probes_a_vague_answer_when_all_llm_providers_fail(session_client):
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
        _, answer_body = _answer(session_client, headers, session_id, answer_text="개발함")
        assert answer_body["mode"] == "question"
        assert answer_body["question"]["question_source"] == "followup"
        assert "구체적으로" in answer_body["question"]["question_text"]
    finally:
        app.dependency_overrides[get_llm_provider] = lambda: session_client.fake_llm


def test_drilldown_heuristic_backup_does_not_probe_a_detailed_answer(session_client):
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
        _, answer_body = _answer(session_client, headers, session_id, answer_text=detailed_answer)
        assert answer_body["question"]["question_source"] == "base"
        assert answer_body["question"]["question_text"] == BASE_QUESTIONS["project"][1].text
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
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

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


def test_activity_period_is_inferred_once_a_frequency_answer_is_drafted(session_client):
    """기간을 카테고리가 끝날 때까지 기다리지 않고 답이 초안으로 쌓이는 시점에 잡아야,
    후속 질문 예산이 인터뷰 도중에도 의미를 갖는다(기간은 인용되지 않는 메타데이터)."""
    from datetime import date

    from app.services.llm.base import PeriodSuggestion

    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    session_client.fake_llm._activity_period = PeriodSuggestion(
        start_date=date(2025, 1, 1), end_date=date(2025, 3, 31)
    )
    _answer(session_client, headers, session_id, answer_text="3개월 동안 주 3회 일했어요")

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
    _answer(session_client, headers, session_id, answer_text="3개월 동안 주 3회 일했어요")

    assert session_client.fake_llm.activity_period_calls == []
    coverage = session_client.get(f"/api/v1/sessions/{session_id}/coverage", headers=headers).json()
    assert coverage["covered_days"] == 28


def test_inference_failure_leaves_the_category_without_a_period(session_client):
    headers = _register_and_login(session_client)
    session_id = _create_session(session_client, headers)
    _advance_to_first_category(session_client, headers, session_id)

    async def exploding_period(*args, **kwargs):
        raise LLMUnavailableError()

    session_client.fake_llm.extract_activity_period = exploding_period

    _, answer_body = _answer(session_client, headers, session_id, answer_text="3개월 동안 주 3회 일했어요")
    assert answer_body["mode"] == "question"

    coverage = session_client.get(f"/api/v1/sessions/{session_id}/coverage", headers=headers).json()
    assert len(coverage["categories_without_period"]) == 1


def test_long_activities_get_a_bigger_followup_budget(session_client):
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
