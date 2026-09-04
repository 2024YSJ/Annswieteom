import type { CategoryType, SessionStatus } from "./api-client";

/** Phase 2: every status now renders inline on the same `/sessions/{id}`
 * page, so these just gate which section is "active" instead of picking a
 * route to redirect to.
 */
export const INTERVIEW_STATUSES = new Set<SessionStatus>(["INTERVIEWING"]);

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
