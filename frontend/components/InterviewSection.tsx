"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  sessionApi,
  type ActivityCategoryRead,
  type CategoryReviewRead,
  type InterviewAskRead,
  type SessionStatus,
} from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import {
  InterviewChatThread,
  type CandidateDraft,
  type CategoryReviewDraft,
} from "@/components/InterviewChatThread";
import type { ComposerEvent } from "@/components/ChatComposer";

function toCandidateDrafts(candidates: CandidateDraft["candidate"][]): CandidateDraft[] {
  return candidates.map((candidate) => ({
    candidate,
    finalText: candidate.content,
    wasEdited: false,
    include: true,
  }));
}

function toReviewDraft(review: CategoryReviewRead): CategoryReviewDraft {
  return {
    categoryId: review.category_id,
    categoryLabel: review.category_label,
    groups: review.groups.map((group) => ({
      turnId: group.turn_id,
      questionText: group.question_text,
      answerText: group.answer_text,
      factType: group.fact_type,
      rows: toCandidateDrafts(group.drafts),
    })),
  };
}

// A new, empty, user-authored row — the only way to grow a list past what the
// AI proposed (excluding a row can only shrink it). fact_type/based_on on the
// synthetic candidate are display-only — the server always uses the fact_type
// of the question the row belongs to (interview.py).
function manualRow(index: number, factType: string): CandidateDraft {
  return {
    candidate: { index, content: "", fact_type: factType, based_on: { type: "generic_pattern", excerpts: [] } },
    finalText: "",
    wasEdited: true,
    include: true,
    isManual: true,
  };
}

export function InterviewSection({
  sessionId,
  accessToken,
  status,
  categories,
  currentCategoryId,
  composerEvent,
  onPrefillChange,
  onSubmittingChange,
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
  /** Reports whether an answer/confirm round-trip is in flight, so the page
   * can disable the composer — the local dev LLM can take ~20s per call
   * (verified live), and with nothing disabling input or showing progress
   * during that wait, a second submission could race the first and the
   * question just looks frozen ("답해도 다음 단계로 안 넘어감", 2026-09-05). */
  onSubmittingChange?: (isSubmitting: boolean) => void;
}) {
  const queryClient = useQueryClient();

  const [question, setQuestion] = useState<InterviewAskRead | null>(null);
  // Only the "여러 활동 있나요?" split check is still confirmed right after the
  // answer — it's routing (it reshapes the question order), not a fact.
  const [candidates, setCandidates] = useState<CandidateDraft[] | null>(null);
  // 카테고리 단위 확인(2026-09-11): 일반 답변은 확인 없이 바로 다음 질문으로 넘어가고,
  // 카테고리 질문이 끝나면 그 카테고리에서 정리한 사실을 질문별로 한 번에 확인한다.
  const [review, setReview] = useState<CategoryReviewDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Echoes the just-sent answer immediately as its own bubble, before the
  // server round-trip finishes — otherwise the composer clears on send but
  // nothing shows the text landed anywhere until extraction finishes several
  // seconds later, which reads as the input having briefly vanished
  // (2026-09-05). Cleared once the answer shows up as a draft turn in the
  // thread (or the split-check cards take over); left in place on error so
  // the attempted answer isn't lost from view.
  const [pendingAnswerText, setPendingAnswerText] = useState<string | null>(null);
  const [isSubmitting, setIsSubmittingState] = useState(false);
  function setIsSubmitting(value: boolean) {
    setIsSubmittingState(value);
    onSubmittingChange?.(value);
  }
  // /interview/ask is server-side idempotent (it returns the cached pending
  // question instead of re-asking the LLM), so this guard is just to avoid a
  // redundant network round-trip on every render, not a correctness fix.
  const fetchedForRef = useRef<string | null>(null);
  const answeredNonceRef = useRef<number | null>(null);

  function applyAsk(ask: InterviewAskRead) {
    if (ask.mode === "review" && ask.review) {
      setQuestion(null);
      setReview(toReviewDraft(ask.review));
      onPrefillChange(null);
    } else {
      setReview(null);
      setQuestion(ask);
      onPrefillChange(ask.draft_answer || null);
    }
  }

  useEffect(() => {
    if (status !== "INTERVIEWING" || !currentCategoryId) return;
    const fetchKey = currentCategoryId;
    if (fetchedForRef.current === fetchKey) return;
    fetchedForRef.current = fetchKey;
    setCandidates(null);

    sessionApi
      .interviewAsk(sessionId, accessToken)
      .then(applyAsk)
      .catch((err) => setError(errorMessage(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, currentCategoryId, sessionId, accessToken]);

  async function submitAnswer(text: string) {
    try {
      const answer = await sessionApi.interviewAnswer(sessionId, text, accessToken);
      if (answer.mode === "candidates") {
        setPendingAnswerText(null); // the split-check cards take over from here
        setCandidates(toCandidateDrafts(answer.candidates));
        return;
      }

      // The answer is now a draft turn on the category — refetch so the thread
      // shows it before the echo bubble goes away (no flicker of a vanished answer).
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      setPendingAnswerText(null);

      if (answer.mode === "review" && answer.review) {
        setQuestion(null);
        setReview(toReviewDraft(answer.review));
        return;
      }
      if (answer.question) {
        // /answer leaves the composer prefill to /ask (one fewer LLM call on
        // the blocking path). Show the question right away, but keep the
        // composer disabled until the prefill arrives — a prefill landing
        // later would replace whatever the user had started typing.
        setQuestion(answer.question);
        const ask = await sessionApi.interviewAsk(sessionId, accessToken);
        applyAsk(ask);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  // Text composer events answer the current question — but only while a
  // question is actually waiting on an answer (no split-check cards or
  // category review on screen).
  useEffect(() => {
    if (!composerEvent || composerEvent.kind !== "text" || composerEvent.forStep !== "interview") return;
    if (!question || candidates !== null || review !== null) return;
    if (answeredNonceRef.current === composerEvent.nonce) return;
    answeredNonceRef.current = composerEvent.nonce;

    onPrefillChange(null); // answered — the "AI가 미리 써봤어요" tag no longer applies
    setError(null);
    setPendingAnswerText(composerEvent.value);
    setIsSubmitting(true);
    void submitAnswer(composerEvent.value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerEvent?.nonce]);

  function updateCandidate(index: number, patch: Partial<Omit<CandidateDraft, "candidate">>) {
    setCandidates((prev) => (prev ? prev.map((c, i) => (i === index ? { ...c, ...patch } : c)) : prev));
  }

  function addManualCandidate() {
    setCandidates((prev) => (prev ? [...prev, manualRow(prev.length, prev[0]?.candidate.fact_type ?? "")] : prev));
  }

  function updateReviewRow(groupIndex: number, rowIndex: number, patch: Partial<Omit<CandidateDraft, "candidate">>) {
    setReview((prev) =>
      prev
        ? {
            ...prev,
            groups: prev.groups.map((group, g) =>
              g === groupIndex
                ? { ...group, rows: group.rows.map((row, r) => (r === rowIndex ? { ...row, ...patch } : row)) }
                : group,
            ),
          }
        : prev,
    );
  }

  function addReviewRow(groupIndex: number) {
    setReview((prev) =>
      prev
        ? {
            ...prev,
            groups: prev.groups.map((group, g) =>
              g === groupIndex ? { ...group, rows: [...group.rows, manualRow(group.rows.length, group.factType)] } : group,
            ),
          }
        : prev,
    );
  }

  // After either confirmation step, move on: the next question in this or the
  // next category, or nothing (the interview is over).
  async function advanceAfter(result: { status: SessionStatus; current_category_id: string | null }) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
    if (result.status === "INTERVIEWING" && result.current_category_id) {
      // Fetch the next question directly instead of relying on the effect
      // above to react to a prop change — staying in the same category
      // changes neither `status` nor `currentCategoryId`, so that effect
      // would never re-fire (production bug, 2026-09-05). Pre-mark
      // fetchedForRef so the effect doesn't also double-fetch if this DID
      // move to a new category.
      fetchedForRef.current = result.current_category_id;
      applyAsk(await sessionApi.interviewAsk(sessionId, accessToken));
    } else {
      setQuestion(null);
      fetchedForRef.current = null;
    }
  }

  async function submitSplitCheck() {
    if (!candidates) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await sessionApi.interviewConfirm(
        sessionId,
        candidates.map((c, index) => ({
          index,
          final_text: c.finalText,
          was_edited: c.wasEdited,
          include: c.include,
        })),
        accessToken,
      );
      setCandidates(null);
      await advanceAfter(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitReview() {
    if (!review) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await sessionApi.interviewReview(
        sessionId,
        review.groups.flatMap((group) =>
          group.rows.map((row, index) => ({
            turn_id: group.turnId,
            index,
            final_text: row.finalText,
            was_edited: row.wasEdited,
            include: row.include,
          })),
        ),
        accessToken,
      );
      setReview(null);
      await advanceAfter(result);
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
        pendingAnswerText={pendingAnswerText}
        candidates={candidates}
        onUpdateCandidate={updateCandidate}
        onAddCandidate={addManualCandidate}
        onSubmit={submitSplitCheck}
        review={review}
        onUpdateReviewRow={updateReviewRow}
        onAddReviewRow={addReviewRow}
        onSubmitReview={submitReview}
        isSubmitting={isSubmitting}
        isWaitingForAnswer={isSubmitting && pendingAnswerText !== null}
      />

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}
    </div>
  );
}
