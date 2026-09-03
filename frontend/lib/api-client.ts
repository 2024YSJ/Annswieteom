const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function throwIfError(res: Response): Promise<void> {
  if (res.ok) return;
  let detail = res.statusText;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") {
      detail = body.detail;
    }
  } catch {
    // no JSON body to read the detail from
  }
  throw new ApiError(res.status, detail);
}

// The access token lives in AuthProvider's React state (never localStorage —
// spec 14-3), but api-client is a plain module outside the component tree.
// AuthProvider registers itself here on mount so a silent refresh triggered
// from deep inside a request() call can push the new token back into React
// state, instead of every call site having to know about refreshing.
let onTokenRefreshed: ((token: string) => void) | null = null;

export function registerTokenRefreshHandler(handler: (token: string) => void) {
  onTokenRefreshed = handler;
}

const REFRESH_PATH = "/api/v1/auth/refresh";

/** One silent retry on 401: refresh the access token via the refresh_token
 * cookie and replay the original request with it. Skipped for the refresh
 * call itself (would recurse) and for requests that had no bearer token to
 * begin with (public endpoints legitimately returning 401, e.g. bad login).
 */
async function withAuthRetry(path: string, headers: HeadersInit | undefined, doFetch: (headers: HeadersInit | undefined) => Promise<Response>): Promise<Response> {
  const res = await doFetch(headers);
  const hadBearerToken = typeof headers === "object" && headers !== null && "Authorization" in headers;
  if (res.status !== 401 || path === REFRESH_PATH || !hadBearerToken) {
    return res;
  }

  const refreshRes = await fetch(`${API_BASE_URL}${REFRESH_PATH}`, { method: "POST", credentials: "include" });
  if (!refreshRes.ok) return res; // not logged in (anymore) - surface the original 401

  const { access_token } = (await refreshRes.json()) as TokenPair;
  onTokenRefreshed?.(access_token);
  return doFetch({ ...headers, Authorization: `Bearer ${access_token}` });
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await withAuthRetry(path, options.headers, (headers) =>
    fetch(`${API_BASE_URL}${path}`, {
      ...options,
      // Required so the browser sends/accepts the refresh_token cookie across
      // the frontend (Vercel) <-> backend (Railway) cross-site boundary.
      credentials: "include",
      headers: { "Content-Type": "application/json", ...headers },
    }),
  );

  await throwIfError(res);

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

/** For non-JSON responses (e.g. the plain-text export endpoint). */
async function requestText(path: string, options: RequestInit = {}, accessToken?: string): Promise<string> {
  const headers = accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined;
  const res = await withAuthRetry(path, headers, (h) =>
    fetch(`${API_BASE_URL}${path}`, { ...options, credentials: "include", headers: { ...h, ...options.headers } }),
  );
  await throwIfError(res);
  return res.text();
}

/** multipart/form-data requests must NOT set Content-Type manually (the
 * browser needs to add its own boundary), so this bypasses `request()`. */
async function requestForm<T>(path: string, formData: FormData, accessToken: string): Promise<T> {
  const res = await withAuthRetry(path, { Authorization: `Bearer ${accessToken}` }, (headers) =>
    fetch(`${API_BASE_URL}${path}`, { method: "POST", credentials: "include", headers, body: formData }),
  );
  await throwIfError(res);
  return (await res.json()) as T;
}

function authHeaders(accessToken: string): HeadersInit {
  return { Authorization: `Bearer ${accessToken}` };
}

export interface TokenPair {
  access_token: string;
  token_type: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  nickname: string;
}

export interface RegisterResponse {
  user_id: string;
}

export interface UserRead {
  id: string;
  email: string | null;
  nickname: string;
  is_guest: boolean;
  created_at: string;
}

export const authApi = {
  register: (payload: RegisterPayload, accessToken?: string) =>
    request<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      headers: accessToken ? authHeaders(accessToken) : undefined,
      body: JSON.stringify(payload),
    }),

  login: (email: string, password: string) =>
    request<TokenPair>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  guestLogin: () => request<TokenPair>("/api/v1/auth/guest", { method: "POST" }),

  refresh: () => request<TokenPair>("/api/v1/auth/refresh", { method: "POST" }),

  logout: (accessToken: string) =>
    request<void>("/api/v1/auth/logout", {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    }),

  me: (accessToken: string) =>
    request<UserRead>("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${accessToken}` },
    }),
};

// ---------------------------------------------------------------------------
// Sessions / interview state machine
// ---------------------------------------------------------------------------

export type SessionStatus =
  | "PERIOD_INPUT"
  | "CATEGORY_SELECT"
  | "RECORD_UPLOAD"
  | "FREQ_DRAFT"
  | "FREQ_CONFIRM"
  | "TASK_DRAFT"
  | "TASK_CONFIRM"
  | "ACHIEVEMENT_DRAFT"
  | "ACHIEVEMENT_CONFIRM"
  | "RESULT_GENERATE"
  | "RESULT_REVIEW";

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
  status: SessionStatus;
  created_at: string;
}

export interface GapPeriodRead {
  start_date: string;
  end_date: string;
}

export interface ConfirmedFactRead {
  id: string;
  fact_type: "frequency" | "task" | "achievement";
  content: string;
  source_type: "user_confirmed" | "user_edited" | "record_cited";
  created_at: string;
}

export interface ActivityCategoryRead {
  id: string;
  category_type: CategoryType;
  custom_label: string | null;
  order_index: number;
  status: "PENDING" | "IN_PROGRESS" | "DONE";
  confirmed_facts: ConfirmedFactRead[];
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

export type InterviewStep = "FREQ_DRAFT" | "TASK_DRAFT" | "ACHIEVEMENT_DRAFT";
export type InterviewConfirmStep = "FREQ_CONFIRM" | "TASK_CONFIRM" | "ACHIEVEMENT_CONFIRM";

export interface InterviewNextRead {
  step: InterviewStep;
  category_id: string;
  ai_draft: string;
  based_on: BasedOnRead;
}

export interface InterviewConfirmRead {
  status: SessionStatus;
  current_category_id: string | null;
}

export const sessionApi = {
  create: (accessToken: string) =>
    request<SessionRead>("/api/v1/sessions", {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  list: (accessToken: string) =>
    request<SessionRead[]>("/api/v1/sessions", {
      headers: authHeaders(accessToken),
    }),

  get: (sessionId: string, accessToken: string) =>
    request<SessionContextRead>(`/api/v1/sessions/${sessionId}`, {
      headers: authHeaders(accessToken),
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

  selectCategories: (sessionId: string, categoryTypes: CategoryType[], accessToken: string) =>
    request<StatusRead>(`/api/v1/sessions/${sessionId}/categories`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ categories: categoryTypes.map((category_type) => ({ category_type })) }),
    }),

  skipRecords: (sessionId: string, accessToken: string) =>
    request<RecordsSkipRead>(`/api/v1/sessions/${sessionId}/records/skip`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  interviewNext: (sessionId: string, accessToken: string) =>
    request<InterviewNextRead>(`/api/v1/sessions/${sessionId}/interview/next`, {
      headers: authHeaders(accessToken),
    }),

  interviewConfirm: (
    sessionId: string,
    payload: { step: InterviewConfirmStep; final_text: string; was_edited: boolean },
    accessToken: string,
  ) =>
    request<InterviewConfirmRead>(`/api/v1/sessions/${sessionId}/interview/confirm`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify(payload),
    }),
};

// ---------------------------------------------------------------------------
// Records
// ---------------------------------------------------------------------------

export type ParseStatus = "PENDING" | "PROCESSING" | "DONE" | "FAILED";

export interface RecordRead {
  id: string;
  record_type: "blog_url" | "image" | "text";
  source_url: string | null;
  platform: string;
  parse_status: ParseStatus;
  parse_error: string | null;
  created_at: string;
}

export const recordsApi = {
  createBlogUrl: (sessionId: string, sourceUrl: string, accessToken: string) =>
    request<RecordRead>(`/api/v1/sessions/${sessionId}/records`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ record_type: "blog_url", source_url: sourceUrl }),
    }),

  createText: (sessionId: string, text: string, accessToken: string) =>
    request<RecordRead>(`/api/v1/sessions/${sessionId}/records/text`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ text }),
    }),

  uploadImage: (sessionId: string, file: File, accessToken: string) => {
    const formData = new FormData();
    formData.append("file", file);
    return requestForm<RecordRead>(`/api/v1/sessions/${sessionId}/records/upload`, formData, accessToken);
  },

  get: (sessionId: string, recordId: string, accessToken: string) =>
    request<RecordRead>(`/api/v1/sessions/${sessionId}/records/${recordId}`, {
      headers: authHeaders(accessToken),
    }),

  remove: (sessionId: string, recordId: string, accessToken: string) =>
    request<void>(`/api/v1/sessions/${sessionId}/records/${recordId}`, {
      method: "DELETE",
      headers: authHeaders(accessToken),
    }),
};

// ---------------------------------------------------------------------------
// Document generation
// ---------------------------------------------------------------------------

export type Tone = "plain" | "neutral" | "assertive";
export type DocumentStatus = "DRAFT" | "FINAL";

export interface CitationRead {
  source_url: string | null;
  published_at: string | null;
}

export interface EvidenceRead {
  fact_id: string;
  content: string;
  source_type: "user_confirmed" | "user_edited" | "record_cited";
  citation: CitationRead | null;
}

export interface SentenceRead {
  id: string;
  order_index: number;
  text: string;
  evidence: EvidenceRead[];
  consistency_check_passed: boolean;
}

export interface DocumentRead {
  id: string;
  tone: Tone;
  version: number;
  status: DocumentStatus;
  sentences: SentenceRead[];
}

export const documentApi = {
  generate: (sessionId: string, tone: Tone, accessToken: string) =>
    request<DocumentRead>(`/api/v1/sessions/${sessionId}/generate`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ tone }),
    }),

  get: (sessionId: string, accessToken: string) =>
    request<DocumentRead>(`/api/v1/sessions/${sessionId}/document`, {
      headers: authHeaders(accessToken),
    }),

  regenerate: (sessionId: string, tone: Tone, accessToken: string) =>
    request<DocumentRead>(`/api/v1/sessions/${sessionId}/document/regenerate`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ tone }),
    }),

  updateSentence: (sessionId: string, sentenceId: string, text: string, accessToken: string) =>
    request<SentenceRead>(`/api/v1/sessions/${sessionId}/document/sentences/${sentenceId}`, {
      method: "PATCH",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ text }),
    }),

  regenerateSentence: (sessionId: string, sentenceId: string, accessToken: string) =>
    request<SentenceRead>(`/api/v1/sessions/${sessionId}/document/sentences/${sentenceId}/regenerate`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  finalize: (sessionId: string, accessToken: string) =>
    request<DocumentRead>(`/api/v1/sessions/${sessionId}/document/finalize`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  exportText: (sessionId: string, accessToken: string) =>
    requestText(`/api/v1/sessions/${sessionId}/export?format=txt`, {}, accessToken),
};
