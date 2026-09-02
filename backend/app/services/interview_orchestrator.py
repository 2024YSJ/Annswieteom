from __future__ import annotations

from app.models.activity_category import ActivityCategory


class StateMachineViolation(Exception):
    """허용되지 않은 순서로 인터뷰 API가 호출됐을 때 (명세서 8-2절, 9-6절 — 409)."""


DRAFT_STEPS = ("FREQ_DRAFT", "TASK_DRAFT", "ACHIEVEMENT_DRAFT")
CONFIRM_STEPS = ("FREQ_CONFIRM", "TASK_CONFIRM", "ACHIEVEMENT_CONFIRM")

FACT_TYPE_BY_STEP: dict[str, str] = {
    "FREQ_DRAFT": "frequency",
    "FREQ_CONFIRM": "frequency",
    "TASK_DRAFT": "task",
    "TASK_CONFIRM": "task",
    "ACHIEVEMENT_DRAFT": "achievement",
    "ACHIEVEMENT_CONFIRM": "achievement",
}

# GET /interview/next가 세션을 넘겨주는 상태 (DRAFT -> CONFIRM)
NEXT_STEP_AFTER_DRAFT: dict[str, str] = {
    "FREQ_DRAFT": "FREQ_CONFIRM",
    "TASK_DRAFT": "TASK_CONFIRM",
    "ACHIEVEMENT_DRAFT": "ACHIEVEMENT_CONFIRM",
}

# POST /interview/confirm이 세션을 넘겨주는 상태. ACHIEVEMENT_CONFIRM은 다음 카테고리
# 유무에 따라 갈라지므로(8-2절) 이 표에 없고 resolve_after_achievement_confirm으로 처리한다.
NEXT_STEP_AFTER_CONFIRM: dict[str, str] = {
    "FREQ_CONFIRM": "TASK_DRAFT",
    "TASK_CONFIRM": "ACHIEVEMENT_DRAFT",
}

# action -> (요구되는 현재 상태, 전이 후 상태) — 목적지가 하나뿐인 단순 전이만 여기 있다.
SIMPLE_TRANSITIONS: dict[str, tuple[str, str]] = {
    "period": ("PERIOD_INPUT", "CATEGORY_SELECT"),
    "categories": ("CATEGORY_SELECT", "RECORD_UPLOAD"),
    "records_skip": ("RECORD_UPLOAD", "FREQ_DRAFT"),
}


def require_simple_transition(action: str, current_status: str) -> str:
    from_status, to_status = SIMPLE_TRANSITIONS[action]
    if current_status != from_status:
        raise StateMachineViolation(
            f"'{action}' requires session status '{from_status}', got '{current_status}'"
        )
    return to_status


def require_status(action: str, current_status: str, required_status: str) -> None:
    """For actions that don't transition the state machine (e.g. records
    upload, which stays in RECORD_UPLOAD — spec 8-2절) but still must only
    run in one specific status.
    """
    if current_status != required_status:
        raise StateMachineViolation(
            f"'{action}' requires session status '{required_status}', got '{current_status}'"
        )


def require_draft_step(current_status: str) -> str:
    """interview/next 호출 가능 여부 확인. 반환값은 전이할 *_CONFIRM 상태."""
    if current_status not in DRAFT_STEPS:
        raise StateMachineViolation(
            f"interview/next requires a *_DRAFT session status, got '{current_status}'"
        )
    return NEXT_STEP_AFTER_DRAFT[current_status]


def require_confirm_step(current_status: str) -> None:
    """interview/confirm 호출 가능 여부 확인."""
    if current_status not in CONFIRM_STEPS:
        raise StateMachineViolation(
            f"interview/confirm requires a *_CONFIRM session status, got '{current_status}'"
        )


def next_category(categories: list[ActivityCategory], current: ActivityCategory) -> ActivityCategory | None:
    ordered = sorted(categories, key=lambda c: c.order_index)
    ids = [c.id for c in ordered]
    idx = ids.index(current.id)
    return ordered[idx + 1] if idx + 1 < len(ordered) else None


def resolve_after_achievement_confirm(
    categories: list[ActivityCategory],
    current_category: ActivityCategory,
) -> tuple[str, ActivityCategory | None]:
    """ACHIEVEMENT_CONFIRM 다음 분기 (8-2절): 다음 카테고리 있으면 FREQ_DRAFT, 없으면 RESULT_GENERATE."""
    nxt = next_category(categories, current_category)
    if nxt is not None:
        return "FREQ_DRAFT", nxt
    return "RESULT_GENERATE", None
