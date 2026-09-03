"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type BasedOnRead, type InterviewConfirmStep } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { CATEGORY_LABELS, CONFIRM_STEP_BY_DRAFT_STEP, STEP_LABELS, pathForStatus } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { useSessionContext } from "@/lib/use-session-context";
import { useAuth } from "@/lib/auth-context";
import { InterviewChatThread } from "@/components/InterviewChatThread";

const DRAFT_STEPS = new Set(["FREQ_DRAFT", "TASK_DRAFT", "ACHIEVEMENT_DRAFT"]);
const INTERVIEW_STEPS = new Set([
  "FREQ_DRAFT", "FREQ_CONFIRM", "TASK_DRAFT", "TASK_CONFIRM", "ACHIEVEMENT_DRAFT", "ACHIEVEMENT_CONFIRM",
]);

interface Pending {
  step: InterviewConfirmStep;
  stepLabel: string;
  draftText: string;
  basedOn: BasedOnRead;
}

export default function InterviewPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const router = useRouter();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const { data: ctx, isLoading, error: loadError } = useSessionContext(sessionId);

  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Guards GET /interview/next from firing twice for the same draft step —
  // that call has a server-side side effect (DRAFT -> CONFIRM), so React 19's
  // dev-mode double-invoked effects would otherwise trigger it twice.
  const fetchedForRef = useRef<string | null>(null);

  useEffect(() => {
    if (!ctx) return;
    if (!INTERVIEW_STEPS.has(ctx.status)) {
      router.replace(pathForStatus(sessionId, ctx.status));
      return;
    }

    if (!DRAFT_STEPS.has(ctx.status)) return;
    const fetchKey = `${ctx.status}:${ctx.current_category?.id}`;
    if (fetchedForRef.current === fetchKey) return;
    fetchedForRef.current = fetchKey;

    sessionApi
      .interviewNext(sessionId, accessToken!)
      .then((next) => {
        setPending({
          step: CONFIRM_STEP_BY_DRAFT_STEP[next.step],
          stepLabel: STEP_LABELS[next.step],
          draftText: next.ai_draft,
          basedOn: next.based_on,
        });
      })
      .catch((err) => setError(errorMessage(err)));
  }, [ctx, sessionId, accessToken, router]);

  async function submitConfirm(step: InterviewConfirmStep, finalText: string, wasEdited: boolean) {
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await sessionApi.interviewConfirm(
        sessionId,
        { step, final_text: finalText, was_edited: wasEdited },
        accessToken!,
      );
      setPending(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });

      if (result.status === "RESULT_GENERATE") {
        router.push(`/sessions/${sessionId}/result`);
      }
      // otherwise: the ctx refetch above updates `ctx.status`, and the effect
      // above picks up the next draft step (or the next category's FREQ_DRAFT).
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

  if (isLoading || !ctx) return <main style={{ maxWidth: 640, margin: "80px auto" }}>불러오는 중...</main>;
  if (loadError) {
    return (
      <main style={{ maxWidth: 640, margin: "80px auto", padding: "0 16px" }}>
        <p style={{ color: "crimson" }}>{errorMessage(loadError)}</p>
      </main>
    );
  }

  const categoryLabel =
    ctx.current_category?.custom_label ??
    (ctx.current_category ? CATEGORY_LABELS[ctx.current_category.category_type] : "");
  const isConfirmStepWithoutDraft = !DRAFT_STEPS.has(ctx.status) && !pending;

  return (
    <main style={{ maxWidth: 640, margin: "80px auto", padding: "0 16px" }}>
      <h1>{categoryLabel} 관련 질문이에요</h1>

      <InterviewChatThread
        confirmedFacts={ctx.current_category?.confirmed_facts ?? []}
        pending={pending ? { stepLabel: pending.stepLabel, draftText: pending.draftText, basedOn: pending.basedOn } : null}
        onConfirm={handleConfirm}
        isSubmitting={isSubmitting}
      />

      {isConfirmStepWithoutDraft && (
        <ManualConfirmFallback
          stepLabel={STEP_LABELS[ctx.status]}
          onConfirm={(text) => submitConfirm(ctx.status as InterviewConfirmStep, text, true)}
        />
      )}

      {error && <p style={{ color: "crimson" }}>{error}</p>}
    </main>
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
    <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12, marginTop: 12 }}>
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
