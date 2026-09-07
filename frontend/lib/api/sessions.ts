import { authHeaders, request } from "./client";
import type { RecordRead } from "./records";

export type SessionStatus =
  | "PERIOD_INPUT"
  | "CATEGORY_SELECT"
  | "RECORD_UPLOAD"
  | "INTERVIEWING"
  | "RESULT_GENERATE"
  | "RESULT_REVIEW"
  | "JOB_PREFERENCES_INPUT"
  | "JOB_SEARCHING"
  | "JOB_RESULTS_REVIEW";

export type SessionKind = "gap_fill" | "job_search";

export type CategoryType =
  | "part_time"
  | "freelance"
  | "volunteer"
  | "study"
  | "project"
  | "caregiving"
  | "travel"
  | "other";

export interface SessionRead {
  id: string;
  title: string | null;
  kind: SessionKind;
  linked_gap_session_id: string | null;
  status: SessionStatus;
  created_at: string;
}

export interface GapPeriodRead {
  start_date: string;
  end_date: string;
}

export interface PeriodExtractRead {
  start_date: string | null;
  end_date: string | null;
}

export interface ConfirmedFactRead {
  id: string;
  fact_type: string;
  content: string;
  source_type: "user_confirmed" | "user_edited" | "record_cited";
  source_question_text: string | null;
  created_at: string;
}

export interface ActivityCategoryRead {
  id: string;
  category_type: CategoryType;
  custom_label: string | null;
  order_index: number;
  status: "PENDING" | "IN_PROGRESS" | "DONE";
  parent_category_id: string | null;
  confirmed_facts: ConfirmedFactRead[];
  records: RecordRead[];
}

export interface CategoryInput {
  category_type: CategoryType;
  custom_label?: string;
}

export interface CategorySuggestion {
  category_type: CategoryType;
  custom_label: string;
}

export interface CategoryExtractRead {
  suggestions: CategorySuggestion[];
}

export interface RecordChunkExcerptRead {
  chunk_id: string;
  text: string;
  published_at: string | null;
}

export interface SessionContextRead {
  session_id: string;
  status: SessionStatus;
  gap_period: GapPeriodRead | null;
  categories: ActivityCategoryRead[];
  current_category: ActivityCategoryRead | null;
  confirmed_facts: ConfirmedFactRead[];
  available_record_chunks: RecordChunkExcerptRead[];
}

export interface StatusRead {
  status: SessionStatus;
}

export interface RecordsSkipRead {
  status: SessionStatus;
  current_category_id: string;
}

export interface RecordExcerptRead {
  chunk_id: string;
  text: string;
  published_at: string | null;
}

export interface BasedOnRead {
  type: "record" | "generic_pattern";
  excerpts: RecordExcerptRead[];
}

export interface InterviewAskRead {
  category_id: string;
  question_text: string;
  question_source: "base" | "followup" | "split_check";
  draft_answer: string;
}

export interface FactCandidateRead {
  index: number;
  content: string;
  fact_type: string;
  based_on: BasedOnRead;
}

export interface InterviewAnswerRead {
  candidates: FactCandidateRead[];
}

export interface FactConfirmation {
  index: number;
  final_text: string;
  was_edited: boolean;
  include?: boolean;
}

export interface InterviewConfirmRead {
  status: SessionStatus;
  current_category_id: string | null;
  category_done: boolean;
  confirmed_facts: ConfirmedFactRead[];
}

export const sessionApi = {
  create: (accessToken: string, options?: { kind?: SessionKind; linked_gap_session_id?: string }) =>
    request<SessionRead>("/api/v1/sessions", {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify(options ?? {}),
    }),

  list: (accessToken: string) =>
    request<SessionRead[]>("/api/v1/sessions", {
      headers: authHeaders(accessToken),
    }),

  get: (sessionId: string, accessToken: string) =>
    request<SessionContextRead>(`/api/v1/sessions/${sessionId}`, {
      headers: authHeaders(accessToken),
    }),

  rename: (sessionId: string, title: string, accessToken: string) =>
    request<SessionRead>(`/api/v1/sessions/${sessionId}`, {
      method: "PATCH",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ title }),
    }),

  remove: (sessionId: string, accessToken: string) =>
    request<void>(`/api/v1/sessions/${sessionId}`, {
      method: "DELETE",
      headers: authHeaders(accessToken),
    }),

  setPeriod: (sessionId: string, startDate: string, endDate: string, accessToken: string) =>
    request<StatusRead>(`/api/v1/sessions/${sessionId}/period`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ start_date: startDate, end_date: endDate }),
    }),

  extractPeriod: (sessionId: string, text: string, accessToken: string) =>
    request<PeriodExtractRead>(`/api/v1/sessions/${sessionId}/period/extract`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ text }),
    }),

  selectCategories: (sessionId: string, categories: CategoryInput[], accessToken: string) =>
    request<StatusRead>(`/api/v1/sessions/${sessionId}/categories`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ categories }),
    }),

  extractCategories: (sessionId: string, text: string, accessToken: string) =>
    request<CategoryExtractRead>(`/api/v1/sessions/${sessionId}/categories/extract`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ text }),
    }),

  skipRecords: (sessionId: string, accessToken: string) =>
    request<RecordsSkipRead>(`/api/v1/sessions/${sessionId}/records/skip`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  interviewAsk: (sessionId: string, accessToken: string) =>
    request<InterviewAskRead>(`/api/v1/sessions/${sessionId}/interview/ask`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  interviewAnswer: (sessionId: string, text: string, accessToken: string) =>
    request<InterviewAnswerRead>(`/api/v1/sessions/${sessionId}/interview/answer`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ text }),
    }),

  interviewConfirm: (sessionId: string, confirmations: FactConfirmation[], accessToken: string) =>
    request<InterviewConfirmRead>(`/api/v1/sessions/${sessionId}/interview/confirm`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ confirmations }),
    }),
};
