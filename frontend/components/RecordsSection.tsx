"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { recordsApi, sessionApi, type RecordRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";
import { RecordStatusRow } from "@/components/RecordStatusRow";
import type { ComposerEvent } from "@/components/ChatComposer";

const QUESTION_TEXT =
  "블로그 글, 자격증 이미지, 또는 메모를 입력창에 적어 보내면 더 구체적인 초안을 만들어드려요. 없어도 괜찮아요.";

export function RecordsSection({
  sessionId,
  accessToken,
  mode,
  composerEvent,
}: {
  sessionId: string;
  accessToken: string;
  mode: "completed" | "active";
  composerEvent: ComposerEvent | null;
}) {
  const queryClient = useQueryClient();
  const [recordIds, setRecordIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSkipping, setIsSkipping] = useState(false);
  const highestNonceRef = useRef(0);

  function addRecord(record: RecordRead) {
    setRecordIds((prev) => [...prev, record.id]);
    queryClient.setQueryData(queryKeys.record(sessionId, record.id), record);
  }

  useEffect(() => {
    if (mode !== "active" || !composerEvent) return;
    const nonce = composerEvent.nonce;
    highestNonceRef.current = nonce;

    async function run() {
      setError(null);
      setIsSubmitting(true);
      try {
        const record =
          composerEvent!.kind === "text"
            ? await recordsApi.createText(sessionId, composerEvent!.value, accessToken)
            : composerEvent!.kind === "url"
              ? await recordsApi.createBlogUrl(sessionId, composerEvent!.value, accessToken)
              : await recordsApi.uploadImage(sessionId, composerEvent!.file, accessToken);
        if (highestNonceRef.current !== nonce) return;
        addRecord(record);
      } catch (err) {
        if (highestNonceRef.current !== nonce) return;
        setError(errorMessage(err));
      } finally {
        if (highestNonceRef.current === nonce) setIsSubmitting(false);
      }
    }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerEvent?.nonce]);

  if (mode === "completed") {
    return (
      <>
        <ChatBubble side="left">{QUESTION_TEXT}</ChatBubble>
        <ChatBubble side="right">기록물 업로드를 완료했어요.</ChatBubble>
      </>
    );
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
    <>
      <ChatBubble side="left">
        <span aria-live="polite">{QUESTION_TEXT}</span>
      </ChatBubble>

      {recordIds.length > 0 && (
        <ChatBubble side="left">
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {recordIds.map((id) => (
              <RecordStatusRow key={id} sessionId={sessionId} recordId={id} accessToken={accessToken} />
            ))}
          </ul>
        </ChatBubble>
      )}

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const file = e.dataTransfer.files?.[0];
          if (file) uploadImage(file);
        }}
      >
        {error && <p style={{ color: "crimson" }}>{error}</p>}
        <button type="button" onClick={handleAdvance} disabled={isSkipping || isSubmitting}>
          {isSkipping ? "진행 중..." : recordIds.length > 0 ? "다음으로" : "기록물 없이 넘어가기"}
        </button>
      </div>
    </>
  );
}
