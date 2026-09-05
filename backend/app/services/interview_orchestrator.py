from __future__ import annotations

from app.models.activity_category import ActivityCategory


class StateMachineViolation(Exception):
    """허용되지 않은 순서로 인터뷰 API가 호출됐을 때 (409)."""


# 카테고리 하나가 던질 수 있는 질문의 총 개수(고정 질문 + AI가 끼워넣거나 덧붙이는
# 질문 전부 합쳐서) 상한. 한 번은 3으로 낮췄었지만(2026-09-05), 곧바로 "프로젝트 →
# 목적 → 그 근본적인 이유"처럼 여러 단계로 파고드는 질문이 자주 나오게 해달라는
# 요청이 이어져 6으로 다시 올렸다 — 고정 질문 4개를 다 쓰고도 AI가 다단계로
# 파고들 여지를 남기기 위함. ActivityCategory.questions_asked가 이 상한과
# 맞대어 실제 카운트를 추적한다.
MAX_QUESTIONS_PER_CATEGORY = 6

# 기록물(블로그/사진/텍스트) 생성 엔드포인트가 허용되는 세션 상태. RESULT_GENERATE 이후는
# 제외한다 — 문서 생성이 시작된 뒤에는 그걸 소비할 인터뷰 루프가 더 없어 고아 데이터가 된다.
RECORD_CREATABLE_STATUSES = ("RECORD_UPLOAD", "INTERVIEWING")

# action -> (요구되는 현재 상태, 전이 후 상태) — 목적지가 하나뿐인 단순 전이만 여기 있다.
SIMPLE_TRANSITIONS: dict[str, tuple[str, str]] = {
    "period": ("PERIOD_INPUT", "CATEGORY_SELECT"),
    "categories": ("CATEGORY_SELECT", "RECORD_UPLOAD"),
    "records_skip": ("RECORD_UPLOAD", "INTERVIEWING"),
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


def next_category(categories: list[ActivityCategory], current: ActivityCategory) -> ActivityCategory | None:
    ordered = sorted(categories, key=lambda c: c.order_index)
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
