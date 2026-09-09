import { authHeaders, request } from "./client";

export interface DateRangeRead {
  start: string;
  end: string;
  days: number;
}

export interface CoverageRead {
  gap_start: string;
  gap_end: string;
  total_days: number;
  covered_days: number;
  /** 기간을 아는 카테고리만으로 계산한 **하한선** — `categories_without_period`가
   * 비어 있지 않으면 실제 커버리지는 이보다 높다. */
  coverage_ratio: number;
  covered_ranges: DateRangeRead[];
  uncovered_ranges: DateRangeRead[];
  categories_without_period: string[];
  suggested_probe_question: string | null;
}

export interface CoverageFillRead {
  status: string;
  category_id: string;
  category_label: string;
}

export const coverageApi = {
  get: (sessionId: string, accessToken: string) =>
    request<CoverageRead>(`/api/v1/sessions/${sessionId}/coverage`, {
      headers: authHeaders(accessToken),
    }),

  setCategoryPeriod: (
    sessionId: string,
    categoryId: string,
    startDate: string,
    endDate: string,
    accessToken: string,
  ) =>
    request<void>(`/api/v1/sessions/${sessionId}/categories/${categoryId}/period`, {
      method: "PATCH",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ start_date: startDate, end_date: endDate }),
    }),

  /** 빈 구간 전용 카테고리를 만들고 인터뷰를 그쪽으로 옮긴다. */
  fill: (sessionId: string, startDate: string, endDate: string, accessToken: string) =>
    request<CoverageFillRead>(`/api/v1/sessions/${sessionId}/coverage/fill`, {
      method: "POST",
      headers: authHeaders(accessToken),
      body: JSON.stringify({ start_date: startDate, end_date: endDate }),
    }),
};
