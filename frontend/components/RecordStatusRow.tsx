"use client";

import { useQuery } from "@tanstack/react-query";
import { recordsApi, type RecordRead } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";

export const PARSE_STATUS_LABELS: Record<RecordRead["parse_status"], string> = {
  PENDING: "대기 중...",
  PROCESSING: "처리 중...",
  DONE: "완료",
  FAILED: "실패",
};

export function RecordStatusRow({
  sessionId,
  recordId,
  accessToken,
}: {
  sessionId: string;
  recordId: string;
  accessToken: string;
}) {
  const { data } = useQuery({
    queryKey: queryKeys.record(sessionId, recordId),
    queryFn: () => recordsApi.get(sessionId, recordId, accessToken),
    refetchInterval: (query) => {
      const status = query.state.data?.parse_status;
      return status === "DONE" || status === "FAILED" ? false : 2000;
    },
  });

  if (!data) return null;

  return (
    <li>
      <strong>{data.record_type === "blog_url" ? data.source_url : data.record_type === "image" ? "이미지" : "텍스트"}</strong>
      {" — "}
      {PARSE_STATUS_LABELS[data.parse_status]}
      {data.parse_status === "FAILED" && data.parse_error && (
        <span style={{ color: "crimson" }}> ({data.parse_error})</span>
      )}
    </li>
  );
}
