import type { CategoryType, SessionRead, SessionStatus } from "./api-client";

/** Phase 2: every status now renders inline on the same `/sessions/{id}`
 * page, so these just gate which section is "active" instead of picking a
 * route to redirect to.
 */
export const INTERVIEW_STATUSES = new Set<SessionStatus>(["INTERVIEWING"]);

export const RESULT_STATUSES = new Set<SessionStatus>(["RESULT_GENERATE", "RESULT_REVIEW"]);

export const GAP_FILL_STATUS_LABELS: Record<string, string> = {
  PERIOD_INPUT: "기간 입력",
  CATEGORY_SELECT: "카테고리 선택",
  RECORD_UPLOAD: "기록물 업로드",
  INTERVIEWING: "인터뷰 중",
  RESULT_GENERATE: "결과 생성 중",
  RESULT_REVIEW: "결과 확인",
};

// job_search 세션은 더 이상 단계 전이가 없는 상시 대화형 세션이라(devlog 16)
// 생성 시점부터 계속 JOB_SEARCHING 하나로 고정된다 — 나머지 값은 이전
// 턴 기반 조건 입력 UI가 쓰던 것으로 이제 안 나오지만, 혹시 남아있는 옛
// 세션을 위해 매핑은 유지한다.
export const JOB_SEARCH_STATUS_LABELS: Record<string, string> = {
  JOB_PREFERENCES_INPUT: "조건 입력",
  JOB_SEARCHING: "취업 정보 검색",
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
  internship: "인턴십",
  club: "동호회·모임",
  other: "기타",
};

/** 사이드바와 메인 화면의 "이어서 하기" 카드가 같은 라벨을 써야 해서 여기로
 * 올렸다 — kind에 따라 라벨 표를 고르는 규칙이 두 군데로 갈라지면 한쪽만
 * 고치는 일이 생긴다. */
export function sessionStatusLabel(session: SessionRead): string {
  const labels = session.kind === "job_search" ? JOB_SEARCH_STATUS_LABELS : GAP_FILL_STATUS_LABELS;
  return labels[session.status] ?? session.status;
}
