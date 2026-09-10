"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { errorMessage } from "@/lib/error-messages";
import { INTERVIEW_STATUSES, RESULT_STATUSES } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { useSessionContext } from "@/lib/use-session-context";
import { useSessionsList } from "@/lib/use-sessions-list";
import { useAuth } from "@/lib/auth-context";
import { PeriodSection } from "@/components/PeriodSection";
import { CategorySection } from "@/components/CategorySection";
import { RecordsSection } from "@/components/RecordsSection";
import { InterviewSection } from "@/components/InterviewSection";
import { ResultSection } from "@/components/ResultSection";
import { JobSearchChatPage } from "@/components/JobSearchChatPage";
import { ChatComposer, type ActiveStep, type ComposerEvent } from "@/components/ChatComposer";
import { LoadingNotice } from "@/components/LoadingNotice";

export default function SessionChatPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  // 이 세션이 어느 kind인지는 사이드바가 이미 불러온 목록(useSessionsList,
  // 같은 react-query 캐시를 공유)에서 알아낸다 — kind별로 완전히 다른
  // 오케스트레이터(JobSearchChatPage vs 아래 공백기 채우기 트리)를 렌더링해야
  // 하므로, gap-fill 전용 컨텍스트(useSessionContext)는 kind가 job_search로
  // 확정되기 전까지만 활성화한다(불필요한 요청 방지).
  const { data: sessions } = useSessionsList();
  const currentSession = sessions?.find((s) => s.id === sessionId);
  const kind = currentSession?.kind;
  const { data: ctx, isLoading, error: loadError } = useSessionContext(sessionId, kind !== "job_search");
  const bottomRef = useRef<HTMLDivElement>(null);
  const [composerEvent, setComposerEvent] = useState<ComposerEvent | null>(null);
  const [composerPrefill, setComposerPrefill] = useState<string | null>(null);
  const [interviewSubmitting, setInterviewSubmitting] = useState(false);

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

  // All hooks above this point must run on every render regardless of kind
  // (React's rules of hooks) — this branch is the earliest point it's safe
  // to diverge into the completely separate job-search orchestrator.
  if (kind === "job_search") {
    return <JobSearchChatPage sessionId={sessionId} linkedGapSessionId={currentSession?.linked_gap_session_id ?? null} />;
  }
  if (kind === undefined) {
    // Still resolving which kind this session is (sessions list not loaded
    // yet) — avoid flashing the gap-fill tree (or its loading/error states,
    // which depend on a query we deliberately didn't enable yet) before we
    // know which orchestrator actually applies.
    return (
      <main style={{ maxWidth: 640, margin: "64px auto" }}>
        <LoadingNotice />
      </main>
    );
  }

  // Must be checked before the loading branch below: react-query resolves
  // `isLoading` to false once a query settles into an error, but `data`
  // (`ctx`) stays undefined either way — so `isLoading || !ctx` alone can't
  // tell "still loading" apart from "failed", and would always take the pure
  // loading branch first, leaving this error branch unreachable and the
  // visitor stuck on a bare "불러오는 중" with no error shown and no escape.
  if (loadError) {
    return (
      <main style={{ maxWidth: 640, margin: "64px auto", padding: "0 16px" }}>
        <p style={{ color: "var(--danger)" }}>{errorMessage(loadError)}</p>
      </main>
    );
  }
  if (isLoading || !ctx) {
    return (
      <main style={{ maxWidth: 640, margin: "64px auto" }}>
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
    // 화면 높이에서 sticky 헤더만큼 뺀다 — 100dvh를 그대로 쓰면 헤더 높이만큼
    // 아래로 밀려서, 바닥에 고정한 입력창이 화면 밖으로 내려간다.
    <div style={{ height: "calc(100dvh - var(--header-height))", display: "flex", flexDirection: "column" }}>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <main style={{ maxWidth: 640, margin: "32px auto 24px", padding: "0 16px", display: "flex", flexDirection: "column", gap: 24 }}>
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
              categories={ctx.categories}
              currentCategoryId={ctx.current_category?.id ?? null}
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
              onSubmittingChange={setInterviewSubmitting}
            />
          )}

          {/* "공백기 채움 현황" 카드는 2026-09-11에 뺐다(devlog 34). 인터뷰 진행도가
           * 아니라 활동 기간(날짜)이 공백기를 덮은 비율이라, "1년 동안 알바"처럼
           * 긴 활동 하나만으로 인터뷰 첫 턴에 100%가 됐다. 백엔드
           * (/coverage, 기간 추론)는 후속 질문 예산에 쓰이므로 남아 있다. */}

          {resultActive && <ResultSection sessionId={sessionId} accessToken={accessToken!} status={ctx.status} />}

          <div ref={bottomRef} />
        </main>
      </div>

      {/* Period uses its own calendar form, not the shared free-text composer.
       * Sits outside the scrollable area above so it stays pinned to the
       * bottom of the viewport and grows in place (via the textarea inside
       * it) instead of scrolling away with the conversation. */}
      {activeStep && activeStep !== "period" && (
        <div style={{ flexShrink: 0, borderTop: "1px solid var(--border)", background: "var(--background)", padding: "12px 16px" }}>
          <div style={{ maxWidth: 640, margin: "0 auto" }}>
            <ChatComposer
              key={activeStep}
              activeStep={activeStep}
              onSend={setComposerEvent}
              prefillText={activeStep === "interview" ? composerPrefill : null}
              disabled={activeStep === "interview" && interviewSubmitting}
            />
          </div>
        </div>
      )}
    </div>
  );
}
