import { authHeaders, request } from "./client";

export interface TrustScoreRead {
  total_sentences: number;
  evidence_coverage_ratio: number | null;
  consistency_pass_rate: number | null;
  ai_acceptance_rate: number | null;
  interview_ai_acceptance_rate: number | null;
  machine_checked_sentences: number;
  user_edited_sentences: number;
}

export const trustApi = {
  session: (sessionId: string, accessToken: string) =>
    request<TrustScoreRead>(`/api/v1/sessions/${sessionId}/trust-score`, {
      headers: authHeaders(accessToken),
    }),

  /** 완전 무인증 — 심사위원/투표자가 로그인 없이 확인할 수 있는 발표용 전역 지표. */
  global: () => request<TrustScoreRead>("/api/v1/trust-score/global"),
};
