"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { recordsApi, type RecordRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";

type Tab = "url" | "image" | "text";

const PARSE_STATUS_LABELS: Record<RecordRead["parse_status"], string> = {
  PENDING: "대기 중...",
  PROCESSING: "처리 중...",
  DONE: "완료",
  FAILED: "실패",
};

function RecordStatusRow({ sessionId, recordId, accessToken }: { sessionId: string; recordId: string; accessToken: string }) {
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

export function RecordUploadPanel({
  sessionId,
  accessToken,
  onRecordsChange,
}: {
  sessionId: string;
  accessToken: string;
  onRecordsChange?: (count: number) => void;
}) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("url");
  const [recordIds, setRecordIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [url, setUrl] = useState("");
  const [text, setText] = useState("");

  function addRecord(record: RecordRead) {
    setRecordIds((prev) => {
      const next = [...prev, record.id];
      onRecordsChange?.(next.length);
      return next;
    });
    queryClient.setQueryData(queryKeys.record(sessionId, record.id), record);
  }

  async function handleUrlSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const record = await recordsApi.createBlogUrl(sessionId, url, accessToken);
      addRecord(record);
      setUrl("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleTextSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const record = await recordsApi.createText(sessionId, text, accessToken);
      addRecord(record);
      setText("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function uploadImage(file: File) {
    setError(null);
    setIsSubmitting(true);
    try {
      const record = await recordsApi.uploadImage(sessionId, file, accessToken);
      addRecord(record);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleImageInputChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // allow re-selecting the same file later
    if (file) uploadImage(file);
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button type="button" onClick={() => setTab("url")} disabled={tab === "url"}>블로그 URL</button>
        <button type="button" onClick={() => setTab("image")} disabled={tab === "image"}>이미지</button>
        <button type="button" onClick={() => setTab("text")} disabled={tab === "text"}>텍스트 붙여넣기</button>
      </div>

      {tab === "url" && (
        <form onSubmit={handleUrlSubmit} style={{ display: "flex", gap: 8 }}>
          <input
            type="url"
            required
            placeholder="https://blog.naver.com/..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            style={{ flex: 1 }}
          />
          <button type="submit" disabled={isSubmitting}>등록</button>
        </form>
      )}

      {tab === "image" && (
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files?.[0];
            if (file) uploadImage(file);
          }}
          style={{ border: "2px dashed #999", padding: 24, textAlign: "center", borderRadius: 8 }}
        >
          <p>이미지를 여기로 드래그하거나 아래에서 선택하세요 (자격증, 수료증 등)</p>
          <input type="file" accept="image/jpeg,image/png,image/webp" onChange={handleImageInputChange} disabled={isSubmitting} />
        </div>
      )}

      {tab === "text" && (
        <form onSubmit={handleTextSubmit} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <textarea
            required
            rows={5}
            placeholder="이 기간 동안의 활동을 자유롭게 적어주세요"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button type="submit" disabled={isSubmitting} style={{ alignSelf: "flex-start" }}>등록</button>
        </form>
      )}

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      {recordIds.length > 0 && (
        <ul style={{ marginTop: 16 }}>
          {recordIds.map((id) => (
            <RecordStatusRow key={id} sessionId={sessionId} recordId={id} accessToken={accessToken} />
          ))}
        </ul>
      )}
    </div>
  );
}
