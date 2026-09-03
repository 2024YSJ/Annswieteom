"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  sessionApi,
  type ActivityCategoryRead,
  type BasedOnRead,
  type InterviewConfirmStep,
  type SessionStatus,
} from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { CONFIRM_STEP_BY_DRAFT_STEP, STEP_LABELS } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { InterviewChatThread } from "@/components/InterviewChatThread";

const DRAFT_STEPS = new Set(["FREQ_DRAFT", "TASK_DRAFT", "ACHIEVEMENT_DRAFT"]);
const CONFIRM_STEPS = new Set(["FREQ_CONFIRM", "TASK_CONFIRM", "ACHIEVEMENT_CONFIRM"]);

interface Pending {
  step: InterviewConfirmStep;
  stepLabel: string;
  draftText: string;
  basedOn: BasedOnRead;
}

export function InterviewSection({
  sessionId,
  accessToken,
  status,
  categories,
  currentCategoryId,
}: {
  sessionId: string;
  accessToken: string;
  status: SessionStatus;
  categories: ActivityCategoryRead[];
  currentCategoryId: string | null;
}) {
  const queryClient = useQueryClient();

  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Guards GET /interview/next from firing twice for the same draft step —
  // that call has a server-side side effect (DRAFT -> CONFIRM), so React 19's
  // dev-mode double-invoked effects would otherwise trigger it twice. This
  // also survives the section staying mounted across every category (unlike
  // the old per-category page, which remounted fresh each time).
  const fetchedForRef = useRef<string | null>(null);

  useEffect(() => {
    if (!DRAFT_STEPS.has(status)) return;
    const fetchKey = `${status}:${currentCategoryId}`;
    if (fetchedForRef.current === fetchKey) return;
    fetchedForRef.current = fetchKey;

    sessionApi
      .interviewNext(sessionId, accessToken)
      .then((next) => {
        setPending({
          step: CONFIRM_STEP_BY_DRAFT_STEP[next.step],
          stepLabel: STEP_LABELS[next.step],
          draftText: next.ai_draft,
          basedOn: next.based_on,
        });
      })
      .catch((err) => setError(errorMessage(err)));
  }, [status, currentCategoryId, sessionId, accessToken]);

  async function submitConfirm(step: InterviewConfirmStep, finalText: string, wasEdited: boolean) {
    setError(null);
    setIsSubmitting(true);
    try {
      await sessionApi.interviewConfirm(sessionId, { step, final_text: finalText, was_edited: wasEdited }, accessToken);
      setPending(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      // The ctx refetch above updates `status`/`currentCategoryId`, and the
      // effect above picks up the next draft step (or the next category's
      // FREQ_DRAFT, or the parent stops rendering this section once status
      // reaches RESULT_GENERATE).
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleConfirm(finalText: string, wasEdited: boolean) {
    if (!pending) return;
    submitConfirm(pending.step, finalText, wasEdited);
  }

  // Once the interview is over (status has moved on to RESULT_GENERATE/
  // RESULT_REVIEW), this section stays mounted so earlier confirmed facts
  // remain visible in the scrollback — it must NOT show the "no draft after
  // reload" fallback then, only while an actual *_CONFIRM step is pending.
  const isConfirmStepWithoutDraft = CONFIRM_STEPS.has(status) && !pending;

  return (
    <div>
      <InterviewChatThread
        categories={categories}
        currentCategoryId={currentCategoryId}
        pending={pending ? { stepLabel: pending.stepLabel, draftText: pending.draftText, basedOn: pending.basedOn } : null}
        onConfirm={handleConfirm}
        isSubmitting={isSubmitting}
      />

      {isConfirmStepWithoutDraft && (
        <ManualConfirmFallback
          stepLabel={STEP_LABELS[status]}
          onConfirm={(text) => submitConfirm(status as InterviewConfirmStep, text, true)}
        />
      )}

      {error && <p style={{ color: "crimson" }}>{error}</p>}
    </div>
  );
}

/** Covers the one gap in the state machine: refreshing while status is a
 * *_CONFIRM step loses the in-memory draft text (there's no "peek at the
 * pending draft" endpoint), so this lets the user type their answer directly
 * instead of getting stuck.
 */
function ManualConfirmFallback({ stepLabel, onConfirm }: { stepLabel: string; onConfirm: (text: string) => void }) {
  const [text, setText] = useState("");
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 12, marginTop: 12 }}>
      <p style={{ fontSize: 13, color: "#888" }}>
        새로고침으로 이전 AI 초안을 다시 보여드릴 수 없어요. &quot;{stepLabel}&quot;에 대한 답변을 직접 적어주세요.
      </p>
      <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} style={{ width: "100%" }} />
      <button type="button" disabled={text.trim().length === 0} onClick={() => onConfirm(text)} style={{ marginTop: 8 }}>
        확인
      </button>
    </div>
  );
}
