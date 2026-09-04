"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  sessionApi,
  type ActivityCategoryRead,
  type InterviewAskRead,
  type SessionStatus,
} from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { useRecordAttach } from "@/lib/use-record-attach";
import { InterviewChatThread, type CandidateDraft } from "@/components/InterviewChatThread";
import type { ComposerEvent } from "@/components/ChatComposer";

export function InterviewSection({
  sessionId,
  accessToken,
  status,
  categories,
  currentCategoryId,
  composerEvent,
  onPrefillChange,
}: {
  sessionId: string;
  accessToken: string;
  status: SessionStatus;
  categories: ActivityCategoryRead[];
  currentCategoryId: string | null;
  composerEvent: ComposerEvent | null;
  /** Reports the current question's AI-drafted answer up to the page, which
   * feeds it into the shared ChatComposer's prefill. Called with null once
   * the composer shouldn't show a prefill anymore (answered, or no question
   * loaded yet). */
  onPrefillChange: (text: string | null) => void;
}) {
  const queryClient = useQueryClient();

  const [question, setQuestion] = useState<InterviewAskRead | null>(null);
  const [candidates, setCandidates] = useState<CandidateDraft[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // /interview/ask is server-side idempotent (it returns the cached pending
  // question instead of re-asking the LLM), so this guard is just to avoid a
  // redundant network round-trip on every render, not a correctness fix.
  const fetchedForRef = useRef<string | null>(null);
  const answeredNonceRef = useRef<number | null>(null);

  useEffect(() => {
    if (status !== "INTERVIEWING" || !currentCategoryId) return;
    const fetchKey = currentCategoryId;
    if (fetchedForRef.current === fetchKey) return;
    fetchedForRef.current = fetchKey;
    setCandidates(null);

    sessionApi
      .interviewAsk(sessionId, accessToken)
      .then((ask) => {
        setQuestion(ask);
        onPrefillChange(ask.draft_answer || null);
      })
      .catch((err) => setError(errorMessage(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, currentCategoryId, sessionId, accessToken]);

  // Text composer events answer the current question — but only while we're
  // actually waiting on an answer (candidates === null); once candidates have
  // come back, further text input is ignored until the review step is submitted.
  useEffect(() => {
    if (!composerEvent || composerEvent.kind !== "text" || composerEvent.forStep !== "interview") return;
    if (!question || candidates !== null) return;
    if (answeredNonceRef.current === composerEvent.nonce) return;
    answeredNonceRef.current = composerEvent.nonce;

    onPrefillChange(null); // answered — the "AI가 미리 써봤어요" tag no longer applies
    setError(null);
    setIsSubmitting(true);
    sessionApi
      .interviewAnswer(sessionId, composerEvent.value, accessToken)
      .then((answer) => {
        setCandidates(
          answer.candidates.map((candidate) => ({
            candidate,
            finalText: candidate.content,
            wasEdited: false,
            include: true,
          })),
        );
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setIsSubmitting(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerEvent?.nonce]);

  const { error: attachError } = useRecordAttach(
    sessionId,
    accessToken,
    composerEvent?.forStep === "interview" ? composerEvent : null,
    () => {
      // Nothing to render locally — the next /interview/ask call re-runs
      // chunk_search and will naturally pick up the newly attached record.
    },
  );

  function updateCandidate(index: number, patch: Partial<Omit<CandidateDraft, "candidate">>) {
    setCandidates((prev) => (prev ? prev.map((c, i) => (i === index ? { ...c, ...patch } : c)) : prev));
  }

  async function submit() {
    if (!candidates) return;
    setError(null);
    setIsSubmitting(true);
    try {
      await sessionApi.interviewConfirm(
        sessionId,
        candidates.map((c, index) => ({
          index,
          final_text: c.finalText,
          was_edited: c.wasEdited,
          include: c.include,
        })),
        accessToken,
      );
      setQuestion(null);
      setCandidates(null);
      fetchedForRef.current = null;
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      // The ctx refetch above updates status/currentCategoryId; the effect
      // above then fetches the next question (same category if not done yet,
      // the next category's first question if it advanced, or this section
      // simply stops rendering once status reaches RESULT_GENERATE).
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div>
      <InterviewChatThread
        categories={categories}
        currentCategoryId={currentCategoryId}
        questionText={question?.question_text ?? null}
        candidates={candidates}
        onUpdateCandidate={updateCandidate}
        onSubmit={submit}
        isSubmitting={isSubmitting}
      />

      {(error || attachError) && <p style={{ color: "crimson" }}>{error ?? attachError}</p>}
    </div>
  );
}
