"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type GapPeriodRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";

const QUESTION_TEXT = "공백기가 언제부터 언제까지였나요? 달력에서 시작일과 종료일을 골라주세요.";

export function PeriodSection({
  sessionId,
  accessToken,
  mode,
  gapPeriod,
}: {
  sessionId: string;
  accessToken: string;
  mode: "completed" | "active";
  gapPeriod: GapPeriodRead | null;
}) {
  const queryClient = useQueryClient();
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!startDate || !endDate) return;
    if (new Date(startDate) > new Date(endDate)) {
      setError("종료일은 시작일보다 빠를 수 없어요.");
      return;
    }

    setIsSubmitting(true);
    try {
      await sessionApi.setPeriod(sessionId, startDate, endDate, accessToken);
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

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 320 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          시작일
          <input type="date" required value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          종료일
          <input type="date" required value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
        {error && <p style={{ color: "crimson" }}>{error}</p>}
        <button type="submit" disabled={isSubmitting} style={{ alignSelf: "flex-start" }}>
          {isSubmitting ? "저장 중..." : "확인"}
        </button>
      </form>
    </>
  );
}
