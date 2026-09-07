from __future__ import annotations

import uuid

from app.models.activity_category import ActivityCategory


class StateMachineViolation(Exception):
    """허용되지 않은 순서로 인터뷰 API가 호출됐을 때 (409)."""


# AI가 고정 질문 사이/이후에 끼워넣는 드릴다운·후속 질문 전용 상한 — 고정 질문
# 자체는 더 이상 이 상한에 걸리지 않는다(2026-09-06). 예전엔 고정+AI 질문을 하나의
# 상한(과거 이름 MAX_QUESTIONS_PER_CATEGORY)으로 묶어 셌는데, 그러면 고정 질문이
# 5개인 카테고리(project/freelance/other)는 AI가 파고들 여지가 사실상 1턴뿐이었고,
# 예산이 바닥나면 "성과/결과" 같은 마지막 고정 질문이 아직 안 나왔어도 강제로 다음
# 카테고리로 넘어가 버렸다("STAR의 Result 없이 카테고리가 끝남" 버그). 이제 고정
# 질문은 절대 건너뛰지 않고 카테고리 유형별 목록을 전부 물어보며, 이 상한은 그
# 바깥에 AI가 덧붙이는 질문에만 적용된다. ActivityCategory.followup_questions_asked가
# 이 상한과 맞대어 실제 카운트를 추적한다.
MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY = 3

# 기록물(블로그/사진/텍스트) 생성 엔드포인트가 허용되는 세션 상태. 카테고리별 기록물
# 요청 단계에서만 첨부 가능하다 — INTERVIEWING 중에는 이미 그 카테고리의 기록물 요청이
# 끝난 뒤이므로 새 기록물을 더 받지 않는다(2026-09-06: 기록물 첨부를 그 단계 전용
# UI로 옮기며 인터뷰 중 첨부도 함께 막기로 함).
RECORD_CREATABLE_STATUSES = ("RECORD_UPLOAD",)

# action -> (요구되는 현재 상태, 전이 후 상태) — 목적지가 하나뿐인 단순 전이만 여기 있다.
# "records_skip"은 여기 없다 — 목적지가 남은 카테고리 유무에 따라 갈리므로
# resolve_after_records()가 담당한다 (resolve_after_confirm()과 같은 이유).
SIMPLE_TRANSITIONS: dict[str, tuple[str, str]] = {
    "period": ("PERIOD_INPUT", "CATEGORY_SELECT"),
    "categories": ("CATEGORY_SELECT", "RECORD_UPLOAD"),
    "generate": ("RESULT_GENERATE", "RESULT_REVIEW"),
}


def require_simple_transition(action: str, current_status: str) -> str:
    from_status, to_status = SIMPLE_TRANSITIONS[action]
    if current_status != from_status:
        raise StateMachineViolation(
            f"'{action}' requires session status '{from_status}', got '{current_status}'"
        )
    return to_status


def require_status(action: str, current_status: str, required_status: str) -> None:
    """For actions that don't transition the state machine but still must
    only run in one specific status.
    """
    if current_status != required_status:
        raise StateMachineViolation(
            f"'{action}' requires session status '{required_status}', got '{current_status}'"
        )


def require_record_creatable(current_status: str) -> None:
    if current_status not in RECORD_CREATABLE_STATUSES:
        raise StateMachineViolation(
            f"records require one of {RECORD_CREATABLE_STATUSES}, got '{current_status}'"
        )


def require_interviewing(current_status: str) -> None:
    if current_status != "INTERVIEWING":
        raise StateMachineViolation(
            f"interview endpoints require session status 'INTERVIEWING', got '{current_status}'"
        )


def _walk_order(categories: list[ActivityCategory]) -> list[ActivityCategory]:
    """Flattens categories into visiting order, expanding any category that
    has been split into sub-categories (parent_category_id) into its children
    at the parent's own position — the parent itself (a container once split)
    is never visited directly. A category with no children still visits
    itself, unchanged from before sub-categories existed.
    """
    by_parent: dict[uuid.UUID | None, list[ActivityCategory]] = {}
    for c in categories:
        by_parent.setdefault(c.parent_category_id, []).append(c)
    for children in by_parent.values():
        children.sort(key=lambda c: c.order_index)

    order: list[ActivityCategory] = []
    for top in by_parent.get(None, []):
        children = by_parent.get(top.id, [])
        order.extend(children if children else [top])
    return order


def next_category(categories: list[ActivityCategory], current: ActivityCategory) -> ActivityCategory | None:
    ordered = _walk_order(categories)
    ids = [c.id for c in ordered]
    idx = ids.index(current.id)
    return ordered[idx + 1] if idx + 1 < len(ordered) else None


def resolve_after_confirm(
    categories: list[ActivityCategory],
    current_category: ActivityCategory,
    advance: bool,
) -> tuple[str, ActivityCategory | None]:
    """confirm 이후 다음 상태 결정.

    advance=False: 아직 이 카테고리에서 더 물어볼 게 있음 — INTERVIEWING 유지, 같은 카테고리.
    advance=True: 이 카테고리는 끝 — 다음 카테고리가 있으면 그쪽으로, 없으면 RESULT_GENERATE.
    """
    if not advance:
        return "INTERVIEWING", current_category
    nxt = next_category(categories, current_category)
    if nxt is not None:
        return "INTERVIEWING", nxt
    return "RESULT_GENERATE", None


def resolve_after_records(
    categories: list[ActivityCategory],
    current_category: ActivityCategory,
) -> tuple[str, ActivityCategory]:
    """기록물 요청 카테고리를 하나 넘긴 뒤 다음 상태 결정.

    다음 카테고리가 있으면 그 카테고리의 기록물 요청으로(RECORD_UPLOAD 유지),
    없으면(마지막 카테고리였으면) 인터뷰를 시작하며 첫 번째 카테고리로 되돌아간다 —
    기록물 요청 순회 동안 current_category_id가 마지막 카테고리까지 옮겨가 있으므로,
    인터뷰는 다시 order_index 0부터 시작해야 한다.
    """
    nxt = next_category(categories, current_category)
    if nxt is not None:
        return "RECORD_UPLOAD", nxt
    ordered = sorted(categories, key=lambda c: c.order_index)
    return "INTERVIEWING", ordered[0]
