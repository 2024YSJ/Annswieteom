"use client";

import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { recordsApi, sessionApi, type RecordRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";
import { RecordStatusRow } from "@/components/RecordStatusRow";

export function RecordsSection({
  sessionId,
  accessToken,
  mode,
}: {
  sessionId: string;
  accessToken: string;
  mode: "completed" | "active";
}) {
  const queryClient = useQueryClient();
  const [recordIds, setRecordIds] = useState<string[]>([]);
  const [textDraft, setTextDraft] = useState("");
  const [isAttachMenuOpen, setIsAttachMenuOpen] = useState(false);
  const [isUrlFormOpen, setIsUrlFormOpen] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSkipping, setIsSkipping] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (mode === "completed") {
    return <ChatBubble side="right">기록물 업로드를 완료했어요.</ChatBubble>;
  }

  function addRecord(record: RecordRead) {
    setRecordIds((prev) => [...prev, record.id]);
    queryClient.setQueryData(queryKeys.record(sessionId, record.id), record);
  }

  async function handleSendText() {
    if (textDraft.trim().length === 0) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const record = await recordsApi.createText(sessionId, textDraft, accessToken);
      addRecord(record);
      setTextDraft("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleUrlSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const record = await recordsApi.createBlogUrl(sessionId, urlDraft, accessToken);
      addRecord(record);
      setUrlDraft("");
      setIsUrlFormOpen(false);
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

  async function handleAdvance() {
    setError(null);
    setIsSkipping(true);
    try {
      await sessionApi.skipRecords(sessionId, accessToken);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSkipping(false);
    }
  }

  return (
    <ChatBubble side="left">
      <div aria-live="polite">
        <p style={{ margin: "0 0 4px", fontWeight: "bold" }}>참고할 기록물이 있나요?</p>
        <p style={{ margin: "0 0 12px", color: "#666" }}>
          블로그 글, 자격증 이미지, 또는 메모를 입력창에 적어 보내면 더 구체적인 초안을 만들어드려요. 없어도 괜찮아요.
        </p>
      </div>

      {recordIds.length > 0 && (
        <ul style={{ marginBottom: 12 }}>
          {recordIds.map((id) => (
            <RecordStatusRow key={id} sessionId={sessionId} recordId={id} accessToken={accessToken} />
          ))}
        </ul>
      )}

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const file = e.dataTransfer.files?.[0];
          if (file) uploadImage(file);
        }}
        style={{ display: "flex", flexDirection: "column", gap: 8 }}
      >
        <div style={{ display: "flex", gap: 8, alignItems: "center", position: "relative" }}>
          <button type="button" onClick={() => setIsAttachMenuOpen((v) => !v)} title="첨부" aria-label="첨부">
            📎
          </button>
          <input
            type="text"
            placeholder="메모를 적어 기록물로 등록하거나, 첨부 버튼으로 URL/이미지를 추가하세요"
            value={textDraft}
            onChange={(e) => setTextDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleSendText();
              }
            }}
            style={{ flex: 1 }}
          />
          <button type="button" onClick={handleSendText} disabled={isSubmitting || textDraft.trim().length === 0}>
            보내기
          </button>

          {isAttachMenuOpen && (
            <div
              style={{
                position: "absolute",
                bottom: "100%",
                left: 0,
                marginBottom: 4,
                background: "#fff",
                border: "1px solid #ddd",
                borderRadius: 8,
                padding: 4,
                display: "flex",
                flexDirection: "column",
                zIndex: 1,
              }}
            >
              <button
                type="button"
                onClick={() => {
                  setIsUrlFormOpen(true);
                  setIsAttachMenuOpen(false);
                }}
              >
                블로그 URL 추가
              </button>
              <button
                type="button"
                onClick={() => {
                  fileInputRef.current?.click();
                  setIsAttachMenuOpen(false);
                }}
              >
                이미지 추가
              </button>
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleImageInputChange}
            disabled={isSubmitting}
            style={{ display: "none" }}
          />
        </div>

        {isUrlFormOpen && (
          <form onSubmit={handleUrlSubmit} style={{ display: "flex", gap: 8 }}>
            <input
              type="url"
              required
              autoFocus
              placeholder="https://blog.naver.com/..."
              value={urlDraft}
              onChange={(e) => setUrlDraft(e.target.value)}
              style={{ flex: 1 }}
            />
            <button type="submit" disabled={isSubmitting}>
              등록
            </button>
            <button type="button" onClick={() => setIsUrlFormOpen(false)}>
              취소
            </button>
          </form>
        )}
      </div>

      {error && <p style={{ color: "crimson" }}>{error}</p>}
      <button type="button" onClick={handleAdvance} disabled={isSkipping} style={{ marginTop: 16 }}>
        {isSkipping ? "진행 중..." : recordIds.length > 0 ? "다음으로" : "기록물 없이 넘어가기"}
      </button>
    </ChatBubble>
  );
}
