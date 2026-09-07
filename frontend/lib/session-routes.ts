import type { CategoryType, SessionStatus } from "./api-client";

/** Phase 2: every status now renders inline on the same `/sessions/{id}`
 * page, so these just gate which section is "active" instead of picking a
 * route to redirect to.
 */
export const INTERVIEW_STATUSES = new Set<SessionStatus>(["INTERVIEWING"]);

export const RESULT_STATUSES = new Set<SessionStatus>(["RESULT_GENERATE", "RESULT_REVIEW"]);

export const JOB_SEARCH_STATUSES = new Set<SessionStatus>([
  "JOB_PREFERENCES_INPUT",
  "JOB_SEARCHING",
  "JOB_RESULTS_REVIEW",
]);

export const GAP_FILL_STATUS_LABELS: Record<string, string> = {
  PERIOD_INPUT: "기간 입력",
  CATEGORY_SELECT: "카테고리 선택",
  RECORD_UPLOAD: "기록물 업로드",
  INTERVIEWING: "인터뷰 중",
  RESULT_GENERATE: "결과 생성 중",
  RESULT_REVIEW: "결과 확인",
};

export const JOB_SEARCH_STATUS_LABELS: Record<string, string> = {
  JOB_PREFERENCES_INPUT: "조건 입력",
  JOB_SEARCHING: "채용정보 찾는 중",
  JOB_RESULTS_REVIEW: "결과 확인",
};

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
