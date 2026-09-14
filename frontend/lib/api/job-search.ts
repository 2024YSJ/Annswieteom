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
  /** 질문의 일부가 6개 카테고리 중 어디에도 해당하지 않을 때(예: 아르바이트/
   * 파트타임 채용정보) 그게 뭔지 설명하는 문구. skipped_category_labels와 달리
   * 애초에 다루지 않는 개념이라는 뜻이다. */
  unsupported_note: string | null;
}

/** 백엔드의 전체 시간 예산(_QUERY_BUDGET_SECONDS)보다 길어야 한다 — 더 짧으면
 * 서버가 부분 결과(스킵된 카테고리 안내 포함)를 돌려주기 직전에 클라이언트가
 * 연결을 직접 끊어버린다. 예전엔 이 값이 105초였고 그때는 맞는 값이었지만
 * (당시 백엔드 예산 90초), 2026-09-10에 DGX Spark 추론 지연 때문에 백엔드
 * 예산이 600초로 올라간 뒤 이 값이 안 따라와서 여러 카테고리짜리 질문이
 * 105초를 넘기면 백엔드가 다 끝내기도 전에 요청 자체가 끊겨 "응답 없음"으로
 * 보이는 문제가 있었다(2026-09-14 리포트) — 백엔드 예산보다 넉넉히 길게 잡는다.
 * 예전처럼 타임아웃이 아예 없으면 응답이 안 올 때 "관련 정보를 찾고 있어요..."
 * 에서 무한 대기한다(devlog 20). */
const QUERY_TIMEOUT_MS = 620_000;

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
