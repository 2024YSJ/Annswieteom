import { authHeaders, request } from "./client";
import type { SessionStatus } from "./sessions";

export interface JobPreferencesRead {
  salary_min: number | null;
  salary_max: number | null;
  location: string | null;
  education_level: string | null;
  career_years: number | null;
  work_style_tags: string[];
}

export interface JobPreferencesSuggestionRead {
  salary_min: number | null;
  salary_max: number | null;
  location: string | null;
  education_level: string | null;
  career_years: number | null;
  work_style_tags: string[];
}

export interface JobPreferencesConfirmInput {
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
  last_searched_at: string | null;
  results: JobPostingRead[];
}

export interface JobSearchSeedRead {
  work_style_tags: string[];
  keyword_hints: string[];
  notes: string;
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
