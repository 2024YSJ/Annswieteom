"use client";

import { useEffect, useRef } from "react";
import { useParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { errorMessage } from "@/lib/error-messages";
import { INTERVIEW_STATUSES, RESULT_STATUSES } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { useSessionContext } from "@/lib/use-session-context";
import { useAuth } from "@/lib/auth-context";
import { PeriodSection } from "@/components/PeriodSection";
import { CategorySection } from "@/components/CategorySection";
import { RecordsSection } from "@/components/RecordsSection";
import { InterviewSection } from "@/components/InterviewSection";
import { ResultSection } from "@/components/ResultSection";

export default function SessionChatPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const { data: ctx, isLoading, error: loadError } = useSessionContext(sessionId);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ctx) return;
    // Unlike the old per-page routes, the URL never changes within a
    // session's flow, so the sidebar's pathname-keyed invalidation
    // (sessions/layout.tsx) doesn't fire as this session progresses —
    // refresh it directly whenever this session's own status advances.
    queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
    // Deliberately keyed on status alone, not all of `ctx` — refetches that
    // don't change status (e.g. a stray revalidation) shouldn't re-trigger this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx?.status, queryClient]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [ctx?.status]);

  if (isLoading || !ctx) return <main style={{ maxWidth: 640, margin: "80px auto" }}>불러오는 중...</main>;
  if (loadError) {
    return (
      <main style={{ maxWidth: 640, margin: "80px auto", padding: "0 16px" }}>
        <p style={{ color: "crimson" }}>{errorMessage(loadError)}</p>
      </main>
    );
  }

  const periodDone = !!ctx.gap_period;
  const categoriesDone = ctx.categories.length > 0;
  const recordsDone = !["PERIOD_INPUT", "CATEGORY_SELECT", "RECORD_UPLOAD"].includes(ctx.status);
  const interviewActive = INTERVIEW_STATUSES.has(ctx.status);
  const resultActive = RESULT_STATUSES.has(ctx.status);

  return (
    <main style={{ maxWidth: 640, margin: "80px auto 40px", padding: "0 16px", display: "flex", flexDirection: "column", gap: 24 }}>
      <PeriodSection
        sessionId={sessionId}
        accessToken={accessToken!}
        mode={periodDone ? "completed" : "active"}
        gapPeriod={ctx.gap_period}
      />

      {(periodDone || categoriesDone) && (
        <CategorySection
          sessionId={sessionId}
          accessToken={accessToken!}
          mode={categoriesDone ? "completed" : "active"}
          categories={ctx.categories}
        />
      )}

      {categoriesDone && (
        <RecordsSection sessionId={sessionId} accessToken={accessToken!} mode={recordsDone ? "completed" : "active"} />
      )}

      {(interviewActive || resultActive) && (
        <InterviewSection
          sessionId={sessionId}
          accessToken={accessToken!}
          status={ctx.status}
          categories={ctx.categories}
          currentCategoryId={ctx.current_category?.id ?? null}
        />
      )}

      {resultActive && <ResultSection sessionId={sessionId} accessToken={accessToken!} status={ctx.status} />}

      <div ref={bottomRef} />
    </main>
  );
}
