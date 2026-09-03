"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type GapPeriodRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";
import type { ComposerEvent } from "@/components/ChatComposer";

const QUESTION_TEXT = "공백기가 언제부터 언제까지였나요? 정확한 날짜가 기억 안 나면 대략적으로 적어주셔도 돼요.";

export function PeriodSection({
  sessionId,
  accessToken,
  mode,
  gapPeriod,
  composerEvent,
}: {
  sessionId: string;
  accessToken: string;
  mode: "completed" | "active";
  gapPeriod: GapPeriodRead | null;
  composerEvent: ComposerEvent | null;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<{ start_date: string; end_date: string } | null>(null);
  const [parseFailed, setParseFailed] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const highestNonceRef = useRef(0);

  useEffect(() => {
    if (mode !== "active" || !composerEvent || composerEvent.kind !== "text") return;
    const nonce = composerEvent.nonce;
    const text = composerEvent.value;
    highestNonceRef.current = nonce;

    async function run() {
      setError(null);
      setIsExtracting(true);
      try {
        const result = await sessionApi.extractPeriod(sessionId, text, accessToken);
        if (highestNonceRef.current !== nonce) return; // a newer request already resolved
        if (result.start_date && result.end_date) {
          setDraft({ start_date: result.start_date, end_date: result.end_date });
          setParseFailed(false);
        } else {
          setDraft(null);
          setParseFailed(true);
        }
      } catch (err) {
        if (highestNonceRef.current !== nonce) return;
        setError(errorMessage(err));
      } finally {
        if (highestNonceRef.current === nonce) setIsExtracting(false);
      }
    }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerEvent?.nonce]);

  async function handleConfirm() {
    if (!draft) return;
    setError(null);
    setIsSubmitting(true);
    try {
      await sessionApi.setPeriod(sessionId, draft.start_date, draft.end_date, accessToken);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  if (mode === "completed") {
    return (
      <>
        <ChatBubble side="left">{QUESTION_TEXT}</ChatBubble>
        <ChatBubble side="right">공백기: {gapPeriod?.start_date} ~ {gapPeriod?.end_date}</ChatBubble>
      </>
    );
  }

  return (
    <>
      <ChatBubble side="left">
        <span aria-live="polite">{QUESTION_TEXT}</span>
      </ChatBubble>

      {isExtracting && <ChatBubble side="left">이해하는 중...</ChatBubble>}

      {draft && !isExtracting && (
        <ChatBubble side="left">
          <div aria-live="polite">
            다음 기간으로 이해했어요: {draft.start_date} ~ {draft.end_date}, 맞나요?
          </div>
          <button type="button" onClick={handleConfirm} disabled={isSubmitting} style={{ marginTop: 8 }}>
            {isSubmitting ? "저장 중..." : "확인"}
          </button>
        </ChatBubble>
      )}

      {parseFailed && !isExtracting && (
        <ChatBubble side="left">
          <span aria-live="polite">
            죄송해요, 기간을 정확히 이해하지 못했어요. 예: &quot;2024년 1월부터 3월까지&quot;처럼 조금 더 구체적으로 적어주시겠어요?
          </span>
        </ChatBubble>
      )}

      {error && <p style={{ color: "crimson" }}>{error}</p>}
    </>
  );
}
