from __future__ import annotations

import uuid

import pytest

from app.services import interview_orchestrator as orch


def _category(order_index: int, parent_category_id=None) -> object:
    class _C:
        pass

    c = _C()
    c.id = uuid.uuid4()
    c.order_index = order_index
    c.parent_category_id = parent_category_id
    return c


def test_require_simple_transition_allows_matching_status():
    assert orch.require_simple_transition("period", "PERIOD_INPUT") == "CATEGORY_SELECT"


def test_require_simple_transition_rejects_wrong_status():
    with pytest.raises(orch.StateMachineViolation):
        orch.require_simple_transition("period", "CATEGORY_SELECT")


def test_resolve_after_records_moves_to_next_category():
    cats = [_category(0), _category(1)]
    status, nxt = orch.resolve_after_records(cats, cats[0])
    assert status == "RECORD_UPLOAD"
    assert nxt is cats[1]


def test_resolve_after_records_starts_interviewing_at_first_category_when_last():
    cats = [_category(0), _category(1)]
    status, nxt = orch.resolve_after_records(cats, cats[1])
    assert status == "INTERVIEWING"
    assert nxt is cats[0]


def test_require_interviewing_allows_interviewing():
    orch.require_interviewing("INTERVIEWING")  # does not raise


def test_require_interviewing_rejects_other_status():
    with pytest.raises(orch.StateMachineViolation):
        orch.require_interviewing("RECORD_UPLOAD")


def test_require_record_creatable_allows_record_upload_and_interviewing():
    """INTERVIEWING이 다시 허용된다(2026-09-09) — 기록물이 쓸모 있어지는 시점은
    질문을 받은 뒤이고, 질문 문구로 청크를 검색하게 된 이후로는 방금 올린
    기록물이 바로 다음 턴의 근거가 된다."""
    orch.require_record_creatable("RECORD_UPLOAD")
    orch.require_record_creatable("INTERVIEWING")


def test_require_record_creatable_rejects_result_statuses():
    with pytest.raises(orch.StateMachineViolation):
        orch.require_record_creatable("RESULT_GENERATE")
    with pytest.raises(orch.StateMachineViolation):
        orch.require_record_creatable("RESULT_REVIEW")


def test_resolve_after_confirm_stays_on_same_category_when_not_advancing():
    cats = [_category(0), _category(1)]
    status, current = orch.resolve_after_confirm(cats, cats[0], advance=False)
    assert status == "INTERVIEWING"
    assert current is cats[0]


def test_resolve_after_confirm_moves_to_next_category_when_advancing():
    cats = [_category(0), _category(1)]
    status, nxt = orch.resolve_after_confirm(cats, cats[0], advance=True)
    assert status == "INTERVIEWING"
    assert nxt is cats[1]


def test_resolve_after_confirm_goes_to_result_generate_when_last_category_done():
    cats = [_category(0), _category(1)]
    status, nxt = orch.resolve_after_confirm(cats, cats[1], advance=True)
    assert status == "RESULT_GENERATE"
    assert nxt is None


def test_walk_order_expands_a_split_category_into_its_children():
    """A category split into sub-categories (parent_category_id) is a
    container that's never visited directly — _walk_order must list its
    children (in the parent's position) instead of the parent itself. (The
    real flow never calls next_category with the parent as `current` post-split
    — interview_confirm's activity_breakdown branch jumps straight to the
    first child — so this is checked at the _walk_order level instead.)"""
    parent = _category(0)
    other_top_level = _category(1)
    child_a = _category(0, parent_category_id=parent.id)
    child_b = _category(1, parent_category_id=parent.id)
    cats = [parent, other_top_level, child_a, child_b]

    order = orch._walk_order(cats)
    assert order == [child_a, child_b, other_top_level]


def test_next_category_moves_past_last_child_to_next_top_level_sibling():
    parent = _category(0)
    other_top_level = _category(1)
    child_a = _category(0, parent_category_id=parent.id)
    child_b = _category(1, parent_category_id=parent.id)
    cats = [parent, other_top_level, child_a, child_b]

    assert orch.next_category(cats, child_a) is child_b
    assert orch.next_category(cats, child_b) is other_top_level


def test_next_category_unaffected_when_no_categories_have_children():
    cats = [_category(0), _category(1), _category(2)]
    assert orch.next_category(cats, cats[0]) is cats[1]
    assert orch.next_category(cats, cats[2]) is None


# --- devlog 54: 근접 중복 후속 질문 감지 -------------------------------------


def test_is_near_duplicate_question_detects_reworded_repeat():
    asked = ["프로필에 저장하신 희망직무(백엔드 개발자) 정보를 참고해서 여쭤볼게요 — 어떤 개발 도구를 쓰셨나요?"]
    candidate = "프로필에 저장하신 희망직무(백엔드 개발자) 정보를 참고해서 여쭤볼게요 — 어떤 개발 툴을 쓰셨나요?"

    assert orch.is_near_duplicate_question(candidate, asked) is True


def test_is_near_duplicate_question_allows_a_genuinely_different_question():
    asked = ["그 일을 하면서 가장 기억에 남는 순간은 언제였나요?"]
    candidate = "그 활동을 위해 어떤 준비 과정을 거쳤나요?"

    assert orch.is_near_duplicate_question(candidate, asked) is False


def test_is_near_duplicate_question_normalizes_whitespace():
    asked = ["그   일을 하면서\n가장 기억에 남는 순간은 언제였나요?"]
    candidate = "그 일을 하면서 가장 기억에 남는 순간은 언제였나요?"

    assert orch.is_near_duplicate_question(candidate, asked) is True


def test_is_near_duplicate_question_empty_asked_questions_is_never_duplicate():
    assert orch.is_near_duplicate_question("아무 질문", []) is False
