"use client";

import { useState } from "react";
import type { ActivityCategoryRead, BasedOnRead, ConfirmedFactRead, FactCandidateRead } from "@/lib/api-client";
import { CATEGORY_LABELS } from "@/lib/session-routes";
import { ChatBubble } from "@/components/ChatBubble";

/** One answer can be split into several confirmed facts (extract_facts found
 * more than one thing in it) — grouping consecutive facts that share the same
 * source question avoids repeating the question bubble once per fact, which
 * otherwise reads as the interview asking the same question over and over
 * (reported as looking like a bug, 2026-09-05). */
function groupFactsByQuestion(facts: ConfirmedFactRead[]): { questionText: string; facts: ConfirmedFactRead[] }[] {
  const sorted = facts.slice().sort((a, b) => a.created_at.localeCompare(b.created_at));
  const groups: { questionText: string; facts: ConfirmedFactRead[] }[] = [];
  for (const fact of sorted) {
    const questionText = fact.source_question_text ?? "질문";
    const lastGroup = groups[groups.length - 1];
    if (lastGroup && lastGroup.questionText === questionText) {
      lastGroup.facts.push(fact);
    } else {
      groups.push({ questionText, facts: [fact] });
    }
  }
  return groups;
}

function BasedOnBadge({ basedOn }: { basedOn: BasedOnRead }) {
  if (basedOn.type === "record") {
    return (
      <span style={{ fontSize: 12, background: "#e3f0dc", color: "#4a6b2a", padding: "2px 8px", borderRadius: 999 }}>
        📎 내 기록물 근거 ({basedOn.excerpts.length}건)
      </span>
    );
  }
  return null;
}

export interface CandidateDraft {
  candidate: FactCandidateRead;
  finalText: string;
  wasEdited: boolean;
  include: boolean;
}

export function InterviewChatThread({
  categories,
  currentCategoryId,
  questionText,
  pendingAnswerText,
  candidates,
  onUpdateCandidate,
  onSubmit,
  isSubmitting,
  isWaitingForAnswer,
}: {
  categories: ActivityCategoryRead[];
  currentCategoryId: string | null;
  questionText: string | null;
  /** The answer just sent, echoed immediately (before the server round-trip
   * finishes) so sending never looks like the input vanished — cleared once
   * candidates take over, but left in place if the request errors. */
  pendingAnswerText?: string | null;
  candidates: CandidateDraft[] | null;
  onUpdateCandidate: (index: number, patch: Partial<Omit<CandidateDraft, "candidate">>) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  /** True while the just-submitted answer is being processed by the AI (no
   * candidates yet) — local models can take a while, so this renders a
   * visible "생각 중" bubble instead of leaving the question looking frozen. */
  isWaitingForAnswer?: boolean;
}) {
  // A category the interview split into sub-categories (parent_category_id
  // on some other row points at it) becomes a container — it's never
  // interviewed directly (see interview_confirm's activity_breakdown branch),
  // so it never has confirmed_facts of its own and must be hidden even if it
  // briefly matches currentCategoryId right at the split.
  const parentIds = new Set(categories.map((c) => c.parent_category_id).filter((id): id is string => id !== null));

  function sortKey(c: ActivityCategoryRead): [number, number] {
    if (!c.parent_category_id) return [c.order_index, -1];
    const parent = categories.find((p) => p.id === c.parent_category_id);
    return [parent?.order_index ?? c.order_index, c.order_index];
  }

  // Only categories that have at least one confirmed fact, or are the one
  // currently being interviewed, are shown — categories not reached yet
  // stay invisible (the AI doesn't preview future questions).
  const visibleCategories = categories
    .filter((c) => !parentIds.has(c.id))
    .slice()
    .sort((a, b) => {
      const [aParent, aOwn] = sortKey(a);
      const [bParent, bOwn] = sortKey(b);
      return aParent - bParent || aOwn - bOwn;
    })
    .filter((c) => c.confirmed_facts.length > 0 || c.id === currentCategoryId);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {visibleCategories.map((category) => (
        <div key={category.id} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ fontSize: 13, color: "var(--muted-text)", fontWeight: "bold" }}>
            ▸ {category.custom_label ?? CATEGORY_LABELS[category.category_type]}
          </div>
          {groupFactsByQuestion(category.confirmed_facts).map((group) => (
            <div key={group.facts[0].id} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <ChatBubble side="left">{group.questionText}</ChatBubble>
              {group.facts.map((fact) => (
                <ChatBubble key={fact.id} side="right" label="확인됨">
                  {fact.content}
                </ChatBubble>
              ))}
            </div>
          ))}

          {category.id === currentCategoryId && questionText && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }} aria-live="polite">
              <ChatBubble side="left">{questionText}</ChatBubble>

              {pendingAnswerText && <ChatBubble side="right">{pendingAnswerText}</ChatBubble>}

              {isWaitingForAnswer && (
                <ChatBubble side="left">
                  <span style={{ color: "var(--muted-text)" }}>답변을 정리하고 있어요...</span>
                </ChatBubble>
              )}

              {candidates !== null && (
                <>
                  {candidates.length === 0 && (
                    <p style={{ fontSize: 13, color: "var(--muted-text)" }}>
                      이 답변에서는 특별히 뽑아낼 내용이 없었어요. 그냥 다음으로 넘어가거나, 다시 답해 주세요.
                    </p>
                  )}
                  {candidates.map((draft, index) => (
                    <CandidateRow
                      key={index}
                      index={index}
                      draft={draft}
                      onUpdate={(patch) => onUpdateCandidate(index, patch)}
                    />
                  ))}
                  <div>
                    <button type="button" disabled={isSubmitting} onClick={onSubmit}>
                      다음
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function CandidateRow({
  draft,
  onUpdate,
}: {
  index: number;
  draft: CandidateDraft;
  onUpdate: (patch: Partial<Omit<CandidateDraft, "candidate">>) => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editText, setEditText] = useState(draft.finalText);

  // Reset the edit box whenever this row's underlying candidate text changes
  // externally (a new question's candidate reusing the same row index) —
  // "adjust state during render" instead of an effect, same idiom this
  // component used previously for resetting the single-draft edit box.
  const [lastSeenText, setLastSeenText] = useState(draft.finalText);
  if (draft.finalText !== lastSeenText) {
    setLastSeenText(draft.finalText);
    setEditText(draft.finalText);
  }

  return (
    <div
      style={{
        background: "var(--surface)",
        color: "var(--surface-text)",
        padding: 12,
        borderRadius: 12,
        opacity: draft.include ? 1 : 0.5,
      }}
    >
      <div style={{ marginBottom: 8, display: "flex", gap: 8, alignItems: "center" }}>
        <BasedOnBadge basedOn={draft.candidate.based_on} />
      </div>
      {isEditing ? (
        <textarea
          rows={3}
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          style={{ width: "100%" }}
        />
      ) : (
        <p style={{ margin: 0 }}>{draft.finalText}</p>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        {isEditing ? (
          <button
            type="button"
            disabled={editText.trim().length === 0}
            onClick={() => {
              onUpdate({ finalText: editText, wasEdited: true, include: true });
              setIsEditing(false);
            }}
          >
            수정 완료
          </button>
        ) : (
          <>
            <button type="button" onClick={() => setIsEditing(true)}>
              고쳐 쓰기
            </button>
            <button type="button" onClick={() => onUpdate({ include: !draft.include })}>
              {draft.include ? "제외하기" : "포함하기"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
