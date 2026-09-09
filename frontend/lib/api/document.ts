import { authHeaders, request, requestText } from "./client";

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

export type EvidenceGrade = "record_backed" | "self_reported" | "unsupported";

export interface SentenceRead {
  id: string;
  order_index: number;
  text: string;
  evidence: EvidenceRead[];
  consistency_check_passed: boolean;
  /** 판정에 쓰인 코사인 유사도. 근거가 없어 검사를 못 했거나 사용자가 직접 고쳐 쓴 문장이면 null. */
  consistency_score: number | null;
  /** 사용자가 직접 고쳐 쓴 문장인지 — consistency_check_passed=true를 "검증 통과"로 읽으면 안 되는 경우. */
  edited_by_user: boolean;
  evidence_grade: EvidenceGrade;
}

/** finalize가 409로 막았을 때 함께 내려오는, 정합성 검사에 걸린 문장들. */
export interface UnverifiedSentence {
  id: string;
  order_index: number;
  text: string;
  consistency_score: number | null;
}

export interface ParagraphRead {
  id: string;
  order_index: number;
  topic: string;
  user_confirmed: boolean;
  sentences: SentenceRead[];
}

export interface DocumentRead {
  id: string;
  tone: Tone;
  version: number;
  status: DocumentStatus;
  paragraphs: ParagraphRead[];
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

  moveSentence: (sessionId: string, sentenceId: string, direction: "prev" | "next", accessToken: string) =>
    request<SentenceRead>(`/api/v1/sessions/${sessionId}/document/sentences/${sentenceId}/move`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ direction }),
    }),

  updateParagraph: (
    sessionId: string,
    paragraphId: string,
    payload: { topic?: string; user_confirmed?: boolean },
    accessToken: string,
  ) =>
    request<ParagraphRead>(`/api/v1/sessions/${sessionId}/document/paragraphs/${paragraphId}`, {
      method: "PATCH",
      headers: authHeaders(accessToken),
      body: JSON.stringify(payload),
    }),

  mergeParagraphWithNext: (sessionId: string, paragraphId: string, accessToken: string) =>
    request<ParagraphRead>(`/api/v1/sessions/${sessionId}/document/paragraphs/${paragraphId}/merge-next`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  deleteParagraph: (sessionId: string, paragraphId: string, accessToken: string) =>
    request<void>(`/api/v1/sessions/${sessionId}/document/paragraphs/${paragraphId}`, {
      method: "DELETE",
      headers: authHeaders(accessToken),
    }),

  /** 정합성 검사에 걸린 문장이 남아 있으면 서버가 409로 막는다 —
   * acknowledgeUnverified=true로 다시 호출해야 확정된다. */
  finalize: (sessionId: string, accessToken: string, acknowledgeUnverified = false) =>
    request<DocumentRead>(`/api/v1/sessions/${sessionId}/document/finalize`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ acknowledge_unverified: acknowledgeUnverified }),
    }),

  exportText: (sessionId: string, accessToken: string, withCitations = false) =>
    requestText(
      `/api/v1/sessions/${sessionId}/export?format=txt&citations=${withCitations}`,
      {},
      accessToken,
    ),
};
