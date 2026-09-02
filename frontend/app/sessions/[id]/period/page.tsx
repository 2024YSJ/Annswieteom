"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { sessionApi } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { pathForStatus } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { useSessionContext } from "@/lib/use-session-context";
import { useAuth } from "@/lib/auth-context";
import { useQueryClient } from "@tanstack/react-query";

export default function PeriodPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const router = useRouter();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const { data: ctx, isLoading, error: loadError } = useSessionContext(sessionId);

  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (ctx && ctx.status !== "PERIOD_INPUT") {
      router.replace(pathForStatus(sessionId, ctx.status));
    }
  }, [ctx, sessionId, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (new Date(startDate) > new Date(endDate)) {
      setError("종료일은 시작일보다 빠를 수 없습니다.");
      return;
    }

    setIsSubmitting(true);
    try {
      await sessionApi.setPeriod(sessionId, startDate, endDate, accessToken!);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      router.push(`/sessions/${sessionId}/categories`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading) return <main style={{ maxWidth: 480, margin: "80px auto" }}>불러오는 중...</main>;
  if (loadError) {
    return (
      <main style={{ maxWidth: 480, margin: "80px auto", padding: "0 16px" }}>
        <p style={{ color: "crimson" }}>{errorMessage(loadError)}</p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 480, margin: "80px auto", padding: "0 16px" }}>
      <h1>공백기 기간을 알려주세요</h1>
      <p>이 기간 동안의 활동을 바탕으로 커리어 내러티브를 만들어드릴게요.</p>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          시작일
          <input type="date" required value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          종료일
          <input type="date" required value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
        {error && <p style={{ color: "crimson" }}>{error}</p>}
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "저장 중..." : "다음"}
        </button>
      </form>
    </main>
  );
}
