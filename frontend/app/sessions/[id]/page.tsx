"use client";

import { useEffect, useRef, useState } from "react";
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
import { ChatComposer, type ActiveStep, type ComposerEvent } from "@/components/ChatComposer";
import { LoadingNotice } from "@/components/LoadingNotice";

export default function SessionChatPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const { data: ctx, isLoading, error: loadError } = useSessionContext(sessionId);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [composerEvent, setComposerEvent] = useState<ComposerEvent | null>(null);
  const [composerPrefill, setComposerPrefill] = useState<string | null>(null);

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

  // Must be checked before the loading branch below: react-query resolves
  // `isLoading` to false once a query settles into an error, but `data`
  // (`ctx`) stays undefined either way — so `isLoading || !ctx` alone can't
  // tell "still loading" apart from "failed", and would always take the pure
  // loading branch first, leaving this error branch unreachable and the
  // visitor stuck on a bare "불러오는 중" with no error shown and no escape.
  if (loadError) {
    return (
      <main style={{ maxWidth: 640, margin: "80px auto", padding: "0 16px" }}>
        <p style={{ color: "crimson" }}>{errorMessage(loadError)}</p>
      </main>
    );
  }
  if (isLoading || !ctx) {
    return (
      <main style={{ maxWidth: 640, margin: "80px auto" }}>
        <LoadingNotice />
      </main>
    );
  }

  const periodDone = !!ctx.gap_period;
  const categoriesDone = ctx.categories.length > 0;
  const recordsDone = !["PERIOD_INPUT", "CATEGORY_SELECT", "RECORD_UPLOAD"].includes(ctx.status);
  const interviewActive = INTERVIEW_STATUSES.has(ctx.status);
  const resultActive = RESULT_STATUSES.has(ctx.status);

  const activeStep: ActiveStep | null = !periodDone
    ? "period"
    : !categoriesDone
      ? "categories"
      : !recordsDone
        ? "records"
        : interviewActive
          ? "interview"
          : null;

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
          composerEvent={composerEvent?.forStep === "categories" ? composerEvent : null}
        />
      )}

      {categoriesDone && (
        <RecordsSection
          sessionId={sessionId}
          accessToken={accessToken!}
          mode={recordsDone ? "completed" : "active"}
          composerEvent={composerEvent?.forStep === "records" ? composerEvent : null}
        />
      )}

      {(interviewActive || resultActive) && (
        <InterviewSection
          sessionId={sessionId}
          accessToken={accessToken!}
          status={ctx.status}
          categories={ctx.categories}
          currentCategoryId={ctx.current_category?.id ?? null}
          composerEvent={composerEvent?.forStep === "interview" ? composerEvent : null}
          onPrefillChange={setComposerPrefill}
        />
      )}

      {resultActive && <ResultSection sessionId={sessionId} accessToken={accessToken!} status={ctx.status} />}

      {/* Period uses its own calendar form, not the shared free-text composer. */}
      {activeStep && activeStep !== "period" && (
        <ChatComposer
          key={activeStep}
          activeStep={activeStep}
          onSend={setComposerEvent}
          prefillText={activeStep === "interview" ? composerPrefill : null}
        />
      )}

      <div ref={bottomRef} />
    </main>
  );
}
