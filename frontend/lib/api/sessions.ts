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

export interface SessionBulkDeleteResult {
  deleted_ids: string[];
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

/** 이 카테고리에서 답했지만 아직 카테고리 끝 확인 전인 턴 — 대화 기록 표시용
 * (질문·답변 원문만). 뽑힌 사실 초안은 확인 카드(CategoryReviewRead)로만 온다. */
export interface DraftTurnRead {
  turn_id: string;
  question_text: string;
  answer_text: string;
}

export interface ActivityCategoryRead {
  id: string;
  category_type: CategoryType;
  custom_label: string | null;
  order_index: number;
  status: "PENDING" | "IN_PROGRESS" | "DONE";
  parent_category_id: string | null;
  confirmed_facts: ConfirmedFactRead[];
  draft_turns: DraftTurnRead[];
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
  /** suggestions가 비었을 때만 채워진다 — AI가 구체적인 갈래를 짚어 되묻는 문장.
   *  LLM을 못 쓰면 null이고, 그때는 정적 예시 안내로 돌아간다. */
  followup_question?: string | null;
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

/** 모순 상대 draft를 가리킨다 — 같은 카테고리 리뷰 카드 안이라도 다른 턴의
 * draft일 수 있어 turn_id+index 조합이 필요하다. */
export interface ConflictRefRead {
  turn_id: string;
  index: number;
}

export interface FactCandidateRead {
  index: number;
  content: string;
  fact_type: string;
  based_on: BasedOnRead;
  /** 같은 카테고리 리뷰 카드 안의 다른 draft와 논리적으로 모순된다고 판단됐을 때
   * 그 상대(들). 확정을 막지 않는 경고용 — 사용자가 직접 확인해야 한다. */
  conflict_with: ConflictRefRead[];
}

/** 카테고리 끝 확인의 한 묶음 — 질문 하나에 대한 답과 거기서 뽑은 사실 초안들. */
export interface ReviewGroupRead {
  turn_id: string;
  question_text: string;
  answer_text: string;
  fact_type: string;
  drafts: FactCandidateRead[];
}

export interface CategoryReviewRead {
  category_id: string;
  category_label: string;
  groups: ReviewGroupRead[];
}

/** mode="question"이면 question_*가, mode="review"면 review가, mode="candidates"면
 * candidates가 채워진다 — candidates는 "여러 활동 있나요?" 답이 이미 후보로 뽑혔지만
 * 아직 확인 전인 상태를 새로고침 후에도 이어가기 위한 복원 경로다(2026-09-12 버그 수정). */
export interface InterviewAskRead {
  category_id: string;
  mode: "question" | "review" | "candidates";
  question_text: string | null;
  question_source: "base" | "followup" | "split_check" | null;
  review: CategoryReviewRead | null;
  candidates: FactCandidateRead[];
}

/** mode="candidates"는 "여러 활동 있나요?" 구조 질문 전용(즉시 확인). 일반 답변은
 * 초안으로 쌓이고 다음 질문(question) 또는 카테고리 끝 확인(review)이 온다. */
export interface InterviewAnswerRead {
  mode: "candidates" | "question" | "review";
  candidates: FactCandidateRead[];
  question: InterviewAskRead | null;
  review: CategoryReviewRead | null;
}

/** `POST /interview/skip` 응답 — 건너뛰기는 question_source==="followup"일 때만
 * 가능하다(고정 질문·소분류 확인 질문은 절대 건너뛸 수 없다). */
export interface InterviewSkipRead {
  mode: "question" | "review";
  question: InterviewAskRead | null;
  review: CategoryReviewRead | null;
}

export interface FactConfirmation {
  index: number;
  final_text: string;
  was_edited: boolean;
  include?: boolean;
}

/** index가 그 턴의 초안 수 이상이면 사용자가 직접 추가한 항목이다. */
export interface ReviewConfirmation {
  turn_id: string;
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

  removeMany: (sessionIds: string[], accessToken: string) =>
    request<SessionBulkDeleteResult>("/api/v1/sessions/bulk-delete", {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ session_ids: sessionIds }),
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

  interviewSkip: (sessionId: string, accessToken: string) =>
    request<InterviewSkipRead>(`/api/v1/sessions/${sessionId}/interview/skip`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  interviewConfirm: (sessionId: string, confirmations: FactConfirmation[], accessToken: string) =>
    request<InterviewConfirmRead>(`/api/v1/sessions/${sessionId}/interview/confirm`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ confirmations }),
    }),

  interviewReview: (sessionId: string, confirmations: ReviewConfirmation[], accessToken: string) =>
    request<InterviewConfirmRead>(`/api/v1/sessions/${sessionId}/interview/review`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ confirmations }),
    }),
};
