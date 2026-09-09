import { authHeaders, request } from "./client";

export interface JobInfoResultRead {
  title: string;
  subtitle: string;
  meta_lines: string[];
  detail_url: string | null;
}

export interface JobInfoCategoryResultRead {
  category: string;
  category_label: string;
  results: JobInfoResultRead[];
}

/** `POST /job-search/query` 응답 — 한 질문이 여러 카테고리에 동시에 걸릴 수
 * 있어 categories가 배열이다. 관련 카테고리를 하나도 못 찾으면 categories는
 * 빈 배열이고 clarification_question이 채워진다. */
export interface JobInfoQueryRead {
  categories: JobInfoCategoryResultRead[];
  clarification_question: string | null;
  /** 조회/판단이 실패하거나 시간을 초과해 이번 응답에서 빠진 카테고리 라벨. */
  skipped_category_labels: string[];
}

/** 백엔드의 전체 시간 예산(_QUERY_BUDGET_SECONDS = 90초)보다 길어야 한다 —
 * 더 짧으면 서버가 부분 결과를 돌려주기 직전에 클라이언트가 끊어버린다.
 * 예전에는 타임아웃이 아예 없어서 응답이 안 오면 "관련 정보를 찾고 있어요..."
 * 에서 무한 대기했다(devlog 20). */
const QUERY_TIMEOUT_MS = 105_000;

export interface JobInfoDraftQueryRead {
  draft_query: string;
}

export const jobSearchApi = {
  query: (sessionId: string, query: string, accessToken: string) =>
    request<JobInfoQueryRead>(`/api/v1/sessions/${sessionId}/job-search/query`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ query }),
      signal: AbortSignal.timeout(QUERY_TIMEOUT_MS),
    }),

  draftQueryFromGap: (sessionId: string, accessToken: string) =>
    request<JobInfoDraftQueryRead>(`/api/v1/sessions/${sessionId}/job-search/draft-query-from-gap`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),
};
