import { authHeaders, request } from "./client";
import type { SessionStatus } from "./sessions";

export interface JobPreferencesRead {
  desired_keyword: string | null;
  salary_min: number | null;
  salary_max: number | null;
  location: string | null;
  education_level: string | null;
  career_years: number | null;
  work_style_tags: string[];
}

export interface JobPreferencesSuggestionRead {
  desired_keyword: string | null;
  salary_min: number | null;
  salary_max: number | null;
  location: string | null;
  education_level: string | null;
  career_years: number | null;
  work_style_tags: string[];
}

export interface JobPreferencesConfirmInput {
  desired_keyword: string | null;
  salary_min: number | null;
  salary_max: number | null;
  location: string | null;
  education_level: string | null;
  career_years: number | null;
  work_style_tags: string[];
}

export interface JobPreferencesConfirmRead {
  status: SessionStatus;
  preferences: JobPreferencesRead;
}

export interface JobPostingRead {
  source: string;
  external_id: string;
  title: string;
  company: string;
  salary_text: string;
  location: string;
  education_requirement: string;
  career_requirement: string;
  work_type: string;
  url: string;
  fit: boolean;
  reason: string;
}

export interface JobSearchStateRead {
  status: SessionStatus;
  linked_gap_session_id: string | null;
  preferences: JobPreferencesRead | null;
  completed_fields: string[];
  last_searched_at: string | null;
  results: JobPostingRead[];
}

export interface JobSearchSeedRead {
  work_style_tags: string[];
  keyword_hints: string[];
  notes: string;
}

/** 최초 1회차 대화형 질문 하나 — `field`가 null이면(`done: true`) 6개를
 * 다 답한 것이고, 이 시점부터는 `JobSearchStateRead.status`가 이미
 * `JOB_SEARCHING`으로 전이돼 있다. */
export interface JobSearchQuestionRead {
  done: boolean;
  status: SessionStatus;
  field: string | null;
  question_text: string | null;
  draft_answer: string;
}

/** 진행 중인 턴에 해당하는 값만 채워 보낸다 — 나머지 키는 서버가 무시한다. */
export interface JobSearchTurnConfirmInput {
  desired_keyword?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  location?: string | null;
  education_level?: string | null;
  career_years?: number | null;
  work_style_tags?: string[] | null;
}

export const jobSearchApi = {
  getState: (sessionId: string, accessToken: string) =>
    request<JobSearchStateRead>(`/api/v1/sessions/${sessionId}/job-search`, {
      headers: authHeaders(accessToken),
    }),

  extractPreferences: (sessionId: string, text: string, accessToken: string) =>
    request<JobPreferencesSuggestionRead>(`/api/v1/sessions/${sessionId}/job-search/preferences/extract`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ text }),
    }),

  confirmPreferences: (sessionId: string, payload: JobPreferencesConfirmInput, accessToken: string) =>
    request<JobPreferencesConfirmRead>(`/api/v1/sessions/${sessionId}/job-search/preferences`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify(payload),
    }),

  askPreferenceQuestion: (sessionId: string, accessToken: string) =>
    request<JobSearchQuestionRead>(`/api/v1/sessions/${sessionId}/job-search/preferences/ask`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  confirmPreferenceTurn: (sessionId: string, payload: JobSearchTurnConfirmInput, accessToken: string) =>
    request<JobSearchQuestionRead>(`/api/v1/sessions/${sessionId}/job-search/preferences/turn-confirm`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify(payload),
    }),

  search: (sessionId: string, accessToken: string) =>
    request<JobSearchStateRead>(`/api/v1/sessions/${sessionId}/job-search/search`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  seedFromGap: (sessionId: string, accessToken: string) =>
    request<JobSearchSeedRead>(`/api/v1/sessions/${sessionId}/job-search/seed-from-gap`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),
};
