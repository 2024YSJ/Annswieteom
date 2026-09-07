"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { recordsApi, type RecordRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
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
  onDeleted,
}: {
  sessionId: string;
  recordId: string;
  accessToken: string;
  /** Omit to render the row read-only (no delete button) — RecordsSection
   * passes this for records still deletable, currently every row it renders. */
  onDeleted?: () => void;
}) {
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { data } = useQuery({
    queryKey: queryKeys.record(sessionId, recordId),
    queryFn: () => recordsApi.get(sessionId, recordId, accessToken),
    refetchInterval: (query) => {
      const status = query.state.data?.parse_status;
      return status === "DONE" || status === "FAILED" ? false : 2000;
    },
  });

  async function handleDelete() {
    setDeleteError(null);
    setIsDeleting(true);
    try {
      await recordsApi.remove(sessionId, recordId, accessToken);
      onDeleted?.();
    } catch (err) {
      setDeleteError(errorMessage(err));
      setIsDeleting(false);
    }
  }

  if (!data) return null;

  return (
    <li>
      <strong>
        {data.original_filename ??
          (data.record_type === "blog_url" ? data.source_url : data.record_type === "image" ? "이미지" : "텍스트")}
      </strong>
      {" — "}
      {PARSE_STATUS_LABELS[data.parse_status]}
      {data.parse_status === "FAILED" && data.parse_error && (
        <span style={{ color: "crimson" }}> ({data.parse_error})</span>
      )}
      {onDeleted && (
        <button type="button" onClick={handleDelete} disabled={isDeleting} style={{ marginLeft: 8, fontSize: 12 }}>
          {isDeleting ? "삭제 중..." : "삭제"}
        </button>
      )}
      {deleteError && <span style={{ color: "crimson", marginLeft: 8, fontSize: 12 }}>{deleteError}</span>}
    </li>
  );
}
