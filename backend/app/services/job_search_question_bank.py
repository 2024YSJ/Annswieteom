from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JobSearchQuestion:
    field: str
    text: str


# 일자리 찾기 최초 1회차 입력 전용 고정 질문 은행 — interview_question_bank.py와
# 같은 원리(파이썬 리스트라 마이그레이션 없이 문구를 다듬을 수 있음)이되,
# 카테고리 분기가 없어 리스트 하나뿐이다. field는 job_search_preferences의
# 실제 컬럼(들)과 1:1 또는 1:N으로 대응한다(job_search.py의
# _apply_turn_field 참고).
JOB_SEARCH_QUESTIONS: list[JobSearchQuestion] = [
    JobSearchQuestion("keyword", "어떤 직무나 분야의 일자리를 찾고 계신가요? (예: 백엔드 개발, 마케팅, 물류 등)"),
    JobSearchQuestion("location", "어느 지역에서 근무하고 싶으신가요? 상관없으면 '상관없음'이라고 답해주세요."),
    JobSearchQuestion("salary", "희망하시는 급여 수준이 어느 정도 되시나요? (예: 3000만원 이상, 월 250만원 등)"),
    JobSearchQuestion("education", "학력 조건이 있으신가요? 없으면 '학력무관'이라고 답해주세요."),
    JobSearchQuestion("career", "관련 경력이 몇 년 정도 되시나요? 신입이면 0이라고 답해주세요."),
    JobSearchQuestion(
        "work_style", "선호하는 업무 스타일이나 근무 조건이 있으신가요? (예: 재택 가능, 유연근무, 야근 없음 등, 여러 개 가능)"
    ),
]


def next_question(completed_fields: list[str]) -> JobSearchQuestion | None:
    """다음으로 물어야 할 고정 질문. 이미 다 나왔으면 None(→ 확정 완료 처리)."""
    completed = set(completed_fields)
    for question in JOB_SEARCH_QUESTIONS:
        if question.field not in completed:
            return question
    return None
