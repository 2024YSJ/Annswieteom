import { authHeaders, request } from "./client";

export interface ArchivedFact {
  content: string;
  fact_type: string;
  source_type: "user_confirmed" | "user_edited" | "record_cited";
}

export interface ArchivedAnswer {
  id: string;
  /** null이면 원래 세션이 삭제된 뒤에도 남은 기록. */
  session_id: string | null;
  category_label: string;
  category_type: string;
  question_text: string;
  question_source: string;
  answer_text: string;
  confirmed_facts: ArchivedFact[];
  created_at: string;
}

export interface ArchiveSummary {
  total_answers: number;
  total_confirmed_facts: number;
  category_types: string[];
}

export const profileApi = {
  /** 계정에 쌓인 문답 기록, 최신순. 이메일로 등록된 계정만 접근 가능(게스트는 403). */
  listAnswers: (
    accessToken: string,
    options: { excludeSessionId?: string; confirmedOnly?: boolean; limit?: number } = {},
  ) => {
    const params = new URLSearchParams();
    if (options.excludeSessionId) params.set("exclude_session_id", options.excludeSessionId);
    if (options.confirmedOnly) params.set("confirmed_only", "true");
    if (options.limit) params.set("limit", String(options.limit));
    const query = params.toString();
    return request<ArchivedAnswer[]>(`/api/v1/me/answers${query ? `?${query}` : ""}`, {
      headers: authHeaders(accessToken),
    });
  },

  summary: (accessToken: string) =>
    request<ArchiveSummary>("/api/v1/me/answers/summary", {
      headers: authHeaders(accessToken),
    }),

  deleteAnswer: (answerId: string, accessToken: string) =>
    request<void>(`/api/v1/me/answers/${answerId}`, {
      method: "DELETE",
      headers: authHeaders(accessToken),
    }),
};
