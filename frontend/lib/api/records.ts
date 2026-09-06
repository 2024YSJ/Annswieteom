import { authHeaders, request, requestForm } from "./client";

export type ParseStatus = "PENDING" | "PROCESSING" | "DONE" | "FAILED";

export interface RecordRead {
  id: string;
  category_id: string | null;
  record_type: "blog_url" | "image" | "text";
  source_url: string | null;
  platform: string;
  parse_status: ParseStatus;
  parse_error: string | null;
  created_at: string;
}

export const recordsApi = {
  // A single URL can expand into multiple records: submitting a velog
  // listing/profile page (e.g. /@user/posts) imports every post in the
  // session's gap period from that page, each as its own record.
  createBlogUrl: (sessionId: string, sourceUrl: string, accessToken: string) =>
    request<RecordRead[]>(`/api/v1/sessions/${sessionId}/records`, {
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
