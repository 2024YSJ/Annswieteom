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

export interface Preference {
  /** 사용자가 직접 쓴 맞춤 정보. 아직 안 썼으면 빈 문자열(404가 아니다). */
  wish_text: string;
  updated_at: string | null;
}

/** inferred = 대화에서 추정(아직 확인 안 함), confirmed = "맞아요"를 누름,
 * user_edited = 직접 고치거나 입력. */
export type AttributeStatus = "inferred" | "confirmed" | "user_edited";

export interface ProfileAttribute {
  id: string;
  key: string;
  key_label: string;
  label: string;
  status: AttributeStatus;
  sensitive: boolean;
  source_kind: string;
  /** 추정 근거가 된 사용자 본인의 말. 직접 입력한 값이면 null. */
  evidence_text: string | null;
  created_at: string | null;
}

export interface AttributeKey {
  key: string;
  label: string;
  sensitive: boolean;
  multi_valued: boolean;
  /** 비어 있으면 자유 텍스트 입력. */
  choices: string[];
}

export interface SensitiveConsent {
  granted: boolean;
  granted_at: string | null;
  /** 동의 없이 민감정보를 말한 적이 있다(값은 저장하지 않았다). */
  sensitive_mentioned: boolean;
}

export interface ProfileAttributes {
  attributes: ProfileAttribute[];
  keys: AttributeKey[];
  consent: SensitiveConsent;
}

export const profileApi = {
  /** 대화로 알게 됐거나 직접 입력한 속성 + 편집용 키 목록·선택지·동의 상태. 게스트도 허용. */
  attributes: (accessToken: string) =>
    request<ProfileAttributes>("/api/v1/me/attributes", { headers: authHeaders(accessToken) }),

  addAttribute: (key: string, value: string, accessToken: string) =>
    request<ProfileAttribute>("/api/v1/me/attributes", {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ key, value }),
    }),

  updateAttribute: (attributeId: string, value: string, accessToken: string) =>
    request<ProfileAttribute>(`/api/v1/me/attributes/${attributeId}`, {
      method: "PATCH",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ value }),
    }),

  confirmAttribute: (attributeId: string, accessToken: string) =>
    request<ProfileAttribute>(`/api/v1/me/attributes/${attributeId}/confirm`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  deleteAttribute: (attributeId: string, accessToken: string) =>
    request<void>(`/api/v1/me/attributes/${attributeId}`, {
      method: "DELETE",
      headers: authHeaders(accessToken),
    }),

  /** 소득·해당 대상·혼인 정보 수집 동의/철회. 동의는 가입 계정만(게스트 403). */
  setSensitiveConsent: (granted: boolean, accessToken: string) =>
    request<SensitiveConsent>("/api/v1/me/consents/sensitive-profiling", {
      method: "PUT",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ granted }),
    }),

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

  /** 직접 쓴 맞춤 정보. 문답이 없어도 이것만으로 맞춤 공고가 켜진다. */
  preferences: (accessToken: string) =>
    request<Preference>("/api/v1/me/preferences", { headers: authHeaders(accessToken) }),

  savePreferences: (wishText: string, accessToken: string) =>
    request<Preference>("/api/v1/me/preferences", {
      method: "PUT",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ wish_text: wishText }),
    }),

  deleteAnswer: (answerId: string, accessToken: string) =>
    request<void>(`/api/v1/me/answers/${answerId}`, {
      method: "DELETE",
      headers: authHeaders(accessToken),
    }),
};
