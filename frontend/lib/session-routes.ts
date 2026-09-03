import type { CategoryType, SessionStatus } from "./api-client";

/** Where a session's current status should route to — used both to advance
 * after a step completes and to redirect back on-load (refresh mid-flow,
 * stale bookmark, direct URL entry) so the user always lands on the step
 * that matches their actual server-side progress (14-4절 공통 UX 체크).
 */
export function pathForStatus(sessionId: string, status: SessionStatus): string {
  switch (status) {
    case "PERIOD_INPUT":
      return `/sessions/${sessionId}/period`;
    case "CATEGORY_SELECT":
      return `/sessions/${sessionId}/categories`;
    case "RECORD_UPLOAD":
      return `/sessions/${sessionId}/records`;
    case "FREQ_DRAFT":
    case "FREQ_CONFIRM":
    case "TASK_DRAFT":
    case "TASK_CONFIRM":
    case "ACHIEVEMENT_DRAFT":
    case "ACHIEVEMENT_CONFIRM":
      return `/sessions/${sessionId}/interview`;
    case "RESULT_GENERATE":
    case "RESULT_REVIEW":
      return `/sessions/${sessionId}/result`;
  }
}

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
