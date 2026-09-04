from __future__ import annotations

from dataclasses import dataclass

from app.models.activity_category import CATEGORY_TYPES


@dataclass(frozen=True)
class BaseQuestion:
    id: str
    fact_type: str
    text: str


# 카테고리 성격에 맞는 고정 질문 세트. DB 테이블이 아니라 파이썬 dict로 두는 이유는
# 문구를 다듬을 때마다 마이그레이션을 안 거치게 하기 위해서다. 한 카테고리 안에서
# fact_type은 반드시 유일해야 한다 (next_base_question이 confirmed_facts에서 이미
# 나온 fact_type을 걸러내는 방식으로 "몇 번째 질문까지 답했는지"를 판단하므로) —
# tests/services/test_interview_question_bank.py가 이 불변식을 강제한다.
BASE_QUESTIONS: dict[str, list[BaseQuestion]] = {
    "part_time": [
        BaseQuestion("part_time_freq", "frequency", "이 아르바이트를 얼마나 자주, 어느 정도 기간 동안 하셨나요?"),
        BaseQuestion("part_time_task", "task", "구체적으로 어떤 업무를 맡으셨나요?"),
        BaseQuestion("part_time_hardship", "hardship_and_coping", "일하면서 가장 힘들었던 점은 무엇이었고, 어떻게 극복하셨나요?"),
        BaseQuestion("part_time_achievement", "achievement", "이 경험을 통해 얻은 성과나 배운 점이 있다면 무엇인가요?"),
    ],
    "freelance": [
        BaseQuestion("freelance_scope", "task", "어떤 종류의 프리랜스 작업을 하셨나요? 주로 어떤 고객/의뢰를 맡으셨어요?"),
        BaseQuestion("freelance_freq", "frequency", "이 일을 얼마나 자주, 어느 정도 기간 동안 하셨나요?"),
        BaseQuestion("freelance_hardship", "hardship_and_coping", "일감을 구하거나 진행하면서 힘들었던 점은 무엇이었고, 어떻게 대응하셨나요?"),
        BaseQuestion("freelance_outcome", "outcome", "결과물이나 성과(수입, 포트폴리오, 후기 등)가 있다면 무엇인가요?"),
    ],
    "volunteer": [
        BaseQuestion("volunteer_org", "context", "어떤 단체나 활동에서, 어떤 역할로 봉사하셨나요?"),
        BaseQuestion("volunteer_freq", "frequency", "얼마나 자주, 어느 정도 기간 동안 활동하셨나요?"),
        BaseQuestion("volunteer_hardship", "hardship_and_coping", "활동하면서 힘들었던 점은 무엇이었고, 어떻게 극복하셨나요?"),
        BaseQuestion("volunteer_achievement", "achievement", "이 활동으로 얻은 배움이나 변화가 있다면 무엇인가요?"),
    ],
    "study": [
        BaseQuestion("study_goal", "study_goal", "무엇을 목표로 공부/자격증 준비를 시작하셨나요?"),
        BaseQuestion("study_method", "study_method", "어떤 방식으로 공부하셨나요? (독학/학원/스터디 등과 하루 루틴)"),
        BaseQuestion("study_hardship", "hardship_and_coping", "공부하면서 가장 힘들었던 점은 무엇이었고, 어떻게 극복하셨나요?"),
        BaseQuestion("study_achievement", "achievement", "결과(합격, 점수, 완주 등)나 배운 점이 있다면 무엇인가요?"),
    ],
    "project": [
        BaseQuestion("project_what", "task", "어떤 프로젝트였나요? 그 안에서 맡은 역할은 무엇이었나요?"),
        BaseQuestion("project_freq", "frequency", "얼마나 자주, 어느 정도 기간 동안 진행하셨나요?"),
        BaseQuestion("project_hardship", "hardship_and_coping", "진행하면서 힘들었던 점은 무엇이었고, 어떻게 해결하셨나요?"),
        BaseQuestion("project_outcome", "outcome", "결과물이나 성과가 있다면 무엇인가요?"),
    ],
    "caregiving": [
        BaseQuestion("caregiving_who", "context", "누구를, 어떤 상황에서 돌보셨나요?"),
        BaseQuestion("caregiving_freq", "frequency", "얼마나 자주, 어느 정도 기간 동안 돌보셨나요?"),
        BaseQuestion("caregiving_hardship", "hardship_and_coping", "가장 힘들었던 점은 무엇이었고, 어떻게 버티거나 해결하셨나요?"),
        BaseQuestion("caregiving_achievement", "achievement", "이 경험을 통해 배운 점이나 달라진 점이 있다면 무엇인가요?"),
    ],
    "travel": [
        BaseQuestion("travel_where", "context", "어디로, 어떤 목적으로 다녀오셨나요?"),
        BaseQuestion("travel_freq", "frequency", "언제, 얼마나 오래 다녀오셨나요?"),
        BaseQuestion("travel_hardship", "hardship_and_coping", "여행 중 힘들었던 점이나 예상 밖의 상황은 무엇이었고, 어떻게 대처하셨나요?"),
        BaseQuestion("travel_achievement", "achievement", "이 경험으로 얻은 것(생각의 변화, 계획 등)이 있다면 무엇인가요?"),
    ],
    "other": [
        BaseQuestion("other_what", "task", "이 기간 동안 구체적으로 어떤 일을 하셨나요?"),
        BaseQuestion("other_reason", "motivation", "이걸 하게 된 계기나 이유가 있으셨나요?"),
        BaseQuestion("other_hardship", "hardship_and_coping", "그 과정에서 힘들었던 점과 어떻게 대응하셨는지 궁금해요."),
        BaseQuestion("other_achievement", "achievement", "돌아보면 얻은 것이 있다면 무엇인가요?"),
    ],
}

assert set(BASE_QUESTIONS) == set(CATEGORY_TYPES), "BASE_QUESTIONS must cover exactly ActivityCategory.CATEGORY_TYPES"


def next_base_question(category_type: str, answered_fact_types: set[str]) -> BaseQuestion | None:
    """다음으로 물어야 할 고정 질문. 이미 다 나왔으면 None (→ AI 후속 질문 단계로 전환)."""
    questions = BASE_QUESTIONS.get(category_type, BASE_QUESTIONS["other"])
    for question in questions:
        if question.fact_type not in answered_fact_types:
            return question
    return None
