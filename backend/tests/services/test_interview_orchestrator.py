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


def test_records_skip_transitions_to_interviewing():
    assert orch.require_simple_transition("records_skip", "RECORD_UPLOAD") == "INTERVIEWING"


def test_require_interviewing_allows_interviewing():
    orch.require_interviewing("INTERVIEWING")  # does not raise


def test_require_interviewing_rejects_other_status():
    with pytest.raises(orch.StateMachineViolation):
        orch.require_interviewing("RECORD_UPLOAD")


def test_require_record_creatable_allows_record_upload_and_interviewing():
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
