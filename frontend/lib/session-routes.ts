import type { CategoryType, SessionStatus } from "./api-client";

/** Phase 2: every status now renders inline on the same `/sessions/{id}`
 * page, so these just gate which section is "active" instead of picking a
 * route to redirect to.
 */
export const INTERVIEW_STATUSES = new Set<SessionStatus>([
  "FREQ_DRAFT",
  "FREQ_CONFIRM",
  "TASK_DRAFT",
  "TASK_CONFIRM",
  "ACHIEVEMENT_DRAFT",
  "ACHIEVEMENT_CONFIRM",
]);

export const RESULT_STATUSES = new Set<SessionStatus>(["RESULT_GENERATE", "RESULT_REVIEW"]);

export const CATEGORY_LABELS: Record<CategoryType, string> = {
  part_time: "아르바이트",
  freelance: "프리랜서",
  volunteer: "봉사활동",
  study: "학습/자격증",
  project: "개인 프로젝트",
  caregiving: "돌봄",
  travel: "여행",
  other: "기타",
};

export const STEP_LABELS: Record<string, string> = {
  FREQ_DRAFT: "얼마나 자주 하셨나요?",
  FREQ_CONFIRM: "얼마나 자주 하셨나요?",
  TASK_DRAFT: "구체적으로 무슨 일을 하셨나요?",
  TASK_CONFIRM: "구체적으로 무슨 일을 하셨나요?",
  ACHIEVEMENT_DRAFT: "어떤 성과나 배운 점이 있었나요?",
  ACHIEVEMENT_CONFIRM: "어떤 성과나 배운 점이 있었나요?",
};

export const CONFIRM_STEP_BY_DRAFT_STEP: Record<string, "FREQ_CONFIRM" | "TASK_CONFIRM" | "ACHIEVEMENT_CONFIRM"> = {
  FREQ_DRAFT: "FREQ_CONFIRM",
  TASK_DRAFT: "TASK_CONFIRM",
  ACHIEVEMENT_DRAFT: "ACHIEVEMENT_CONFIRM",
};

/** Lets InterviewChatThread show the actual question for an already-confirmed
 * fact (only its fact_type is available at that point, not the step it was
 * asked from) — same three strings as STEP_LABELS, keyed differently.
 */
export const QUESTION_BY_FACT_TYPE: Record<"frequency" | "task" | "achievement", string> = {
  frequency: STEP_LABELS.FREQ_DRAFT,
  task: STEP_LABELS.TASK_DRAFT,
  achievement: STEP_LABELS.ACHIEVEMENT_DRAFT,
};
