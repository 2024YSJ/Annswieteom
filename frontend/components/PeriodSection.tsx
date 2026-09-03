"use client";

import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type GapPeriodRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";

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

  if (mode === "completed") {
    return <ChatBubble side="right">공백기: {gapPeriod?.start_date} ~ {gapPeriod?.end_date}</ChatBubble>;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (new Date(startDate) > new Date(endDate)) {
      setError("종료일은 시작일보다 빠를 수 없습니다.");
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

  return (
    <ChatBubble side="left">
      <div aria-live="polite">
        <p style={{ margin: "0 0 4px", fontWeight: "bold" }}>공백기 기간을 알려주세요</p>
        <p style={{ margin: "0 0 12px", color: "#666" }}>이 기간 동안의 활동을 바탕으로 커리어 내러티브를 만들어드릴게요.</p>
      </div>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          시작일
          <input type="date" required autoFocus value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          종료일
          <input type="date" required value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
        {error && <p style={{ color: "crimson" }}>{error}</p>}
        <button type="submit" disabled={isSubmitting} style={{ alignSelf: "flex-start" }}>
          {isSubmitting ? "저장 중..." : "다음"}
        </button>
      </form>
    </ChatBubble>
  );
}
