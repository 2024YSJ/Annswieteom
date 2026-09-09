import { authHeaders, request } from "./client";

export interface FeedItemRead {
  id: string;
  source: string;
  /** 한국어 라벨은 서버가 채워서 내려준다 — 프론트에서 하드코딩하지 않는다. */
  source_label: string;
  category: string;
  category_label: string;
  feed_kind: "job" | "policy";
  title: string;
  subtitle: string;
  meta_lines: string[];
  detail_url: string | null;
  /** 소스가 등록일을 주는 카테고리에서만 채워진다(대부분은 null). */
  source_published_at: string | null;
  first_seen_at: string;
}

/** 왜 개인화가 아닌지. 셋을 구분하지 않으면 신규 사용자에게 고장 안내를 띄우거나
 * 실제 고장을 "정보 부족"으로 숨기게 된다 — 서버 스키마(schemas/feed.py)의
 * 주석과 같은 이유다. */
export type FeedFallbackReason = "no_profile" | "preparing" | "ai_unavailable";

export interface FeedRead {
  items: FeedItemRead[];
  total: number;
  limit: number;
  offset: number;
  personalized: boolean;
  fallback_reason: FeedFallbackReason | null;
  /** 캐시가 비어 있어 서버가 방금 수집을 예약한 상태. 수집은 응답 이후에 돌기
   * 때문에 최초 1회는 구조적으로 items가 빈 채로 온다 — 프론트는 이걸 "없음"이
   * 아니라 "준비 중"으로 그리고 잠시 뒤 다시 물어봐야 한다. */
  is_warming: boolean;
  refreshed_at: string | null;
}

interface FeedQuery {
  category?: string;
  limit?: number;
  offset?: number;
}

function queryString({ category, limit, offset }: FeedQuery): string {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const feedApi = {
  /** 청년 지원 정책 — 최신 등록순. 로그아웃 방문자도 그대로 받는다. */
  policies: (options: FeedQuery = {}, accessToken?: string | null) =>
    request<FeedRead>(`/api/v1/feed/policies${queryString(options)}`, {
      headers: accessToken ? authHeaders(accessToken) : undefined,
    }),

  /** 공고 — 최신순. 로그인 여부와 무관하게 같은 목록. */
  jobs: (options: FeedQuery = {}, accessToken?: string | null) =>
    request<FeedRead>(`/api/v1/feed/jobs${queryString(options)}`, {
      headers: accessToken ? authHeaders(accessToken) : undefined,
    }),

  /** 맞춤 공고 — 문답 기록으로 만든 프로필 벡터와의 코사인 거리순. 로그인 필수
   * (게스트도 허용). 프로필이 없으면 오류가 아니라 최신순 + fallback_reason으로
   * 내려온다. */
  recommendedJobs: (options: Omit<FeedQuery, "category"> = {}, accessToken: string) =>
    request<FeedRead>(`/api/v1/feed/jobs/recommended${queryString(options)}`, {
      headers: authHeaders(accessToken),
    }),
};
