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
}

export const jobSearchApi = {
  query: (sessionId: string, query: string, accessToken: string) =>
    request<JobInfoQueryRead>(`/api/v1/sessions/${sessionId}/job-search/query`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ query }),
    }),
};
