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
    candidate: {
      index,
      content: "",
      fact_type: factType,
      based_on: { type: "generic_pattern", excerpts: [] },
      conflict_with: [],
    },
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
  onSubmittingChange,
}: {
  sessionId: string;
  accessToken: string;
  status: SessionStatus;
  categories: ActivityCategoryRead[];
  currentCategoryId: string | null;
  composerEvent: ComposerEvent | null;
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
  // "candidates"가 빈 배열로 도착한 걸 이미 자동 제출했는지 — 배열 참조로 비교해서
  // 같은 도착에 두 번 쏘지 않는다(아래 자동 진행 effect 참고).
  const autoAdvancedCandidatesRef = useRef<CandidateDraft[] | null>(null);

  function applyAsk(ask: InterviewAskRead) {
    if (ask.mode === "review" && ask.review) {
      setQuestion(null);
      setReview(toReviewDraft(ask.review));
    } else if (ask.mode === "candidates") {
      // 질문 말풍선을 남겨둬야 그 아래 후보 카드가 보인다 — InterviewChatThread의
      // 렌더 조건이 questionText 존재를 전제로 한다(submitAnswer의 candidates
      // 분기도 같은 이유로 question을 그대로 둔다).
      setQuestion(ask);
      setReview(null);
      setCandidates(toCandidateDrafts(ask.candidates));
    } else {
      setReview(null);
      setQuestion(ask);
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
        // /answer already carries the next question — show it directly. Until
        // 2026-09-12 this also called /ask again, purely to fetch the AI's
        // composer prefill; with that feature gone the extra round trip
        // (and its LLM call) is gone too.
        setQuestion(answer.question);
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

    setError(null);
    setPendingAnswerText(composerEvent.value);
    setIsSubmitting(true);
    void submitAnswer(composerEvent.value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerEvent?.nonce]);

  function retryAnswer() {
    if (!pendingAnswerText) return;
    setError(null);
    setIsSubmitting(true);
    void submitAnswer(pendingAnswerText);
  }

  // "여러 활동 있나요?"에 후보가 0건으로 왔으면("하나뿐이에요" 등) 사용자가 굳이
  // "다음"을 눌러야 할 이유가 없다 — 서버가 이미 후보 없음을 알려준 상태이므로
  // 빈 확인을 자동으로 제출한다(2026-09-12 검증에서 발견된 불필요한 클릭).
  useEffect(() => {
    if (candidates !== null && candidates.length === 0 && autoAdvancedCandidatesRef.current !== candidates) {
      autoAdvancedCandidatesRef.current = candidates;
      void submitSplitCheck();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidates]);

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

      {error && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <p style={{ color: "var(--danger)", margin: 0 }}>{error}</p>
          {/* 실패한 답변은 pendingAnswerText에 그대로 남아 있다(성공 시에만 지워짐) —
              그 값으로 같은 답을 다시 보낸다. 사용자가 처음부터 다시 타이핑하지 않아도
              된다(JobSearchChatPage의 "다시 시도"와 같은 패턴, 2026-09-12 검증 발견). */}
          {pendingAnswerText && (
            <button type="button" onClick={retryAnswer} disabled={isSubmitting} style={{ fontSize: 12 }}>
              다시 시도
            </button>
          )}
        </div>
      )}
    </div>
  );
}
