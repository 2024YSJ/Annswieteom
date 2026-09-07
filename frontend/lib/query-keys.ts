export const queryKeys = {
  sessions: () => ["sessions"] as const,
  session: (sessionId: string) => ["session", sessionId] as const,
  record: (sessionId: string, recordId: string) => ["session", sessionId, "record", recordId] as const,
  document: (sessionId: string) => ["session", sessionId, "document"] as const,
  jobSearch: (sessionId: string) => ["session", sessionId, "job-search"] as const,
};
