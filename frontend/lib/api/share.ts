import { authHeaders, request } from "./client";

export interface ShareLinkRead {
  share_slug: string;
}

/** 공개 공유 페이지가 받는 전부 — session_id/user_id/근거 원문은 여기 없다
 * (백엔드 SharePreviewRead 스키마 자체가 그 필드를 가질 수 없다). */
export interface SharePreviewRead {
  tone: string;
  representative_sentences: string[];
  evidence_grade_summary: Record<string, number>;
}

export const shareApi = {
  create: (sessionId: string, accessToken: string) =>
    request<ShareLinkRead>(`/api/v1/sessions/${sessionId}/document/share`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  revoke: (sessionId: string, accessToken: string) =>
    request<void>(`/api/v1/sessions/${sessionId}/document/share`, {
      method: "DELETE",
      headers: authHeaders(accessToken),
    }),

  /** 완전 무인증 — 공개 공유 미리보기. */
  getPublic: (slug: string) => request<SharePreviewRead>(`/api/v1/share/${slug}`),
};
