"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { useJobSearchState } from "@/lib/use-job-search-state";
import { useAuth } from "@/lib/auth-context";
import { JobSearchInterviewSection } from "@/components/JobSearchInterviewSection";
import { JobSearchPreferencesSection } from "@/components/JobSearchPreferencesSection";
import { JobSearchResultsSection } from "@/components/JobSearchResultsSection";
import { ChatComposer, type ActiveStep, type ComposerEvent } from "@/components/ChatComposer";
import { LoadingNotice } from "@/components/LoadingNotice";

/** kind="job_search" 세션 전용 오케스트레이터 — 공백기 채우기의
 * `app/sessions/[id]/page.tsx`와 같은 구조(하나의 URL 안에서 status로 단계
 * 전환, 공유 ChatComposer)를 그대로 따르되 완전히 별도 트리로 둔다 — 두
 * 플로우가 status 컬럼만 공유할 뿐 도메인이 다르기 때문(job_search.py의
 * _require_status 주석과 동일한 이유).
 *
 * status===JOB_PREFERENCES_INPUT인 동안은 최초 1회차 대화형 질문
 * (JobSearchInterviewSection, 공백기 채우기 인터뷰와 같은 원리로 한 번에
 * 하나씩), 그 이후는 완료 요약 + 자유 재편집(JobSearchPreferencesSection) —
 * 서로 완전히 다른 화면이라 상태로 배타적으로 분기한다. */
export function JobSearchChatPage({ sessionId }: { sessionId: string }) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const { data: state, isLoading, error: loadError } = useJobSearchState(sessionId);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [composerEvent, setComposerEvent] = useState<ComposerEvent | null>(null);
  const [composerPrefill, setComposerPrefill] = useState<string | null>(null);
  const [interviewSubmitting, setInterviewSubmitting] = useState(false);

  useEffect(() => {
    if (!state) return;
    queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state?.status, queryClient]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state?.status]);

  if (loadError) {
    return (
      <main style={{ maxWidth: 640, margin: "80px auto", padding: "0 16px" }}>
        <p style={{ color: "crimson" }}>{errorMessage(loadError)}</p>
      </main>
    );
  }
  if (isLoading || !state) {
    return (
      <main style={{ maxWidth: 640, margin: "80px auto" }}>
        <LoadingNotice />
      </main>
    );
  }

  const interviewActive = state.status === "JOB_PREFERENCES_INPUT";
  const resultsActive = state.status === "JOB_SEARCHING" || state.status === "JOB_RESULTS_REVIEW";
  // 이 페이지에서 공유 입력창이 쓰이는 곳은 선호도 관련뿐이다(결과 섹션은
  // 버튼만 쓰고 입력창을 소비하지 않음) — 확정 후에도 조건을 자유 텍스트로
  // 다시 말할 수 있어야 하므로(대화형 수정), 상태와 무관하게 항상 켜둔다.
  const activeStep: ActiveStep = "job_preferences";

  return (
    <div style={{ height: "100dvh", display: "flex", flexDirection: "column" }}>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <main
          style={{ maxWidth: 640, margin: "80px auto 24px", padding: "0 16px", display: "flex", flexDirection: "column", gap: 24 }}
        >
          {interviewActive ? (
            <JobSearchInterviewSection
              sessionId={sessionId}
              accessToken={accessToken!}
              composerEvent={composerEvent?.forStep === "job_preferences" ? composerEvent : null}
              onPrefillChange={setComposerPrefill}
              onSubmittingChange={setInterviewSubmitting}
            />
          ) : (
            <JobSearchPreferencesSection
              sessionId={sessionId}
              accessToken={accessToken!}
              preferences={state.preferences}
              composerEvent={composerEvent?.forStep === "job_preferences" ? composerEvent : null}
            />
          )}

          {resultsActive && (
            <JobSearchResultsSection
              sessionId={sessionId}
              accessToken={accessToken!}
              status={state.status}
              results={state.results}
              lastSearchedAt={state.last_searched_at}
            />
          )}

          <div ref={bottomRef} />
        </main>
      </div>

      {activeStep && (
        <div style={{ flexShrink: 0, borderTop: "1px solid var(--border)", background: "var(--background)", padding: "12px 16px" }}>
          <div style={{ maxWidth: 640, margin: "0 auto" }}>
            <ChatComposer
              key={activeStep}
              activeStep={activeStep}
              onSend={setComposerEvent}
              prefillText={interviewActive ? composerPrefill : null}
              disabled={interviewActive && interviewSubmitting}
            />
          </div>
        </div>
      )}
    </div>
  );
}
