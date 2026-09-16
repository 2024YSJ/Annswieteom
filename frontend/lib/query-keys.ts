export const queryKeys = {
  sessions: () => ["sessions"] as const,
  session: (sessionId: string) => ["session", sessionId] as const,
  record: (sessionId: string, recordId: string) => ["session", sessionId, "record", recordId] as const,
  document: (sessionId: string) => ["session", sessionId, "document"] as const,
  trustScore: (sessionId: string) => ["session", sessionId, "trust-score"] as const,
  globalTrustScore: () => ["trust-score", "global"] as const,
  demoDocument: () => ["demo", "document"] as const,
  sharePreview: (slug: string) => ["share", slug] as const,
  jobSearch: (sessionId: string) => ["session", sessionId, "job-search"] as const,
  archive: () => ["me", "answers"] as const,
  preferences: () => ["me", "preferences"] as const,
  attributes: () => ["me", "attributes"] as const,
  /** 피드는 세션과 무관한 전역 캐시다. `scope`로 섹션(policies/jobs/recommended)을
   * 나눠서, 한 섹션을 무효화해도 나머지가 다시 안 불리게 한다.
   *
   * "더보기"는 페이지를 키에 넣지 않는다 — `useInfiniteQuery`가 이 키 하나 아래에
   * 페이지 배열을 모으므로, 페이지를 키에 넣으면 오히려 이어붙이기가 깨진다. */
  feed: (
    scope: "policies" | "trainings" | "jobs" | "recommended" | "recommended_policies" | "recommended_trainings",
  ) => ["feed", scope] as const,
};
