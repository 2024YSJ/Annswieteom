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

export interface SentenceRead {
  id: string;
  order_index: number;
  text: string;
  evidence: EvidenceRead[];
  consistency_check_passed: boolean;
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

  finalize: (sessionId: string, accessToken: string) =>
    request<DocumentRead>(`/api/v1/sessions/${sessionId}/document/finalize`, {
      method: "POST",
      headers: authHeaders(accessToken),
    }),

  exportText: (sessionId: string, accessToken: string) =>
    requestText(`/api/v1/sessions/${sessionId}/export?format=txt`, {}, accessToken),
};
