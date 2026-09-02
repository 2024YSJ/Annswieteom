from __future__ import annotations

import uuid

import pytest

from app.services import interview_orchestrator as orch


def _category(order_index: int) -> object:
    class _C:
        pass

    c = _C()
    c.id = uuid.uuid4()
    c.order_index = order_index
    return c


def test_require_simple_transition_allows_matching_status():
    assert orch.require_simple_transition("period", "PERIOD_INPUT") == "CATEGORY_SELECT"


def test_require_simple_transition_rejects_wrong_status():
    with pytest.raises(orch.StateMachineViolation):
        orch.require_simple_transition("period", "CATEGORY_SELECT")


def test_require_draft_step_maps_to_matching_confirm_step():
    assert orch.require_draft_step("FREQ_DRAFT") == "FREQ_CONFIRM"
    assert orch.require_draft_step("TASK_DRAFT") == "TASK_CONFIRM"
    assert orch.require_draft_step("ACHIEVEMENT_DRAFT") == "ACHIEVEMENT_CONFIRM"


def test_require_draft_step_rejects_non_draft_status():
    with pytest.raises(orch.StateMachineViolation):
        orch.require_draft_step("FREQ_CONFIRM")


def test_require_confirm_step_rejects_non_confirm_status():
    with pytest.raises(orch.StateMachineViolation):
        orch.require_confirm_step("FREQ_DRAFT")


def test_resolve_after_achievement_confirm_moves_to_next_category():
    cats = [_category(0), _category(1)]
    status, nxt = orch.resolve_after_achievement_confirm(cats, cats[0])
    assert status == "FREQ_DRAFT"
    assert nxt is cats[1]


def test_resolve_after_achievement_confirm_goes_to_result_generate_when_last():
    cats = [_category(0), _category(1)]
    status, nxt = orch.resolve_after_achievement_confirm(cats, cats[1])
    assert status == "RESULT_GENERATE"
    assert nxt is None
