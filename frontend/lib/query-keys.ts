export const queryKeys = {
  sessions: () => ["sessions"] as const,
  session: (sessionId: string) => ["session", sessionId] as const,
  record: (sessionId: string, recordId: string) => ["session", sessionId, "record", recordId] as const,
  interviewNext: (sessionId: string, step: string) => ["session", sessionId, "interview", "next", step] as const,
  document: (sessionId: string) => ["session", sessionId, "document"] as const,
};
