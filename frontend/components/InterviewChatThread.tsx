"use client";

import { useState } from "react";
import type { ActivityCategoryRead, BasedOnRead } from "@/lib/api-client";
import { CATEGORY_LABELS, QUESTION_BY_FACT_TYPE } from "@/lib/session-routes";
import { ChatBubble } from "@/components/ChatBubble";

const FACT_TYPE_LABELS: Record<string, string> = {
  frequency: "빈도",
  task: "업무",
  achievement: "성과",
};

function BasedOnBadge({ basedOn }: { basedOn: BasedOnRead }) {
  if (basedOn.type === "record") {
    return (
      <span style={{ fontSize: 12, background: "#e6f4ea", color: "#1a7f37", padding: "2px 8px", borderRadius: 999 }}>
        📎 내 기록물 근거 ({basedOn.excerpts.length}건)
      </span>
    );
  }
  return (
    <span style={{ fontSize: 12, background: "#f1f1f1", color: "#666", padding: "2px 8px", borderRadius: 999 }}>
      💭 AI의 일반적인 추측
    </span>
  );
}

interface PendingDraft {
  stepLabel: string;
  draftText: string;
  basedOn: BasedOnRead;
}

export function InterviewChatThread({
  categories,
  currentCategoryId,
  pending,
  onConfirm,
  isSubmitting,
}: {
  categories: ActivityCategoryRead[];
  currentCategoryId: string | null;
  pending: PendingDraft | null;
  onConfirm: (finalText: string, wasEdited: boolean) => void;
  isSubmitting: boolean;
}) {
  const [draftEdit, setDraftEdit] = useState("");
  const [isEditing, setIsEditing] = useState(false);

  // Reset the edit box whenever a new draft arrives.
  const [lastSeenDraft, setLastSeenDraft] = useState<string | null>(null);
  if (pending && pending.draftText !== lastSeenDraft) {
    setLastSeenDraft(pending.draftText);
    setDraftEdit(pending.draftText);
    setIsEditing(false);
  }

  // Only categories that have at least one confirmed fact, or are the one
  // currently being interviewed, are shown — categories not reached yet
  // stay invisible (the AI doesn't preview future questions).
  const visibleCategories = categories
    .slice()
    .sort((a, b) => a.order_index - b.order_index)
    .filter((c) => c.confirmed_facts.length > 0 || c.id === currentCategoryId);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {visibleCategories.map((category) => (
        <div key={category.id} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ fontSize: 13, color: "#666", fontWeight: "bold" }}>
            ▸ {category.custom_label ?? CATEGORY_LABELS[category.category_type]}
          </div>
          {category.confirmed_facts.map((fact) => (
            <div key={fact.id} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <ChatBubble side="left">{QUESTION_BY_FACT_TYPE[fact.fact_type]}</ChatBubble>
              <ChatBubble side="right" label={`${FACT_TYPE_LABELS[fact.fact_type]} · 확인됨`}>
                {fact.content}
              </ChatBubble>
            </div>
          ))}

          {category.id === currentCategoryId && pending && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }} aria-live="polite">
              <ChatBubble side="left">{pending.stepLabel}</ChatBubble>
              <div
                style={{
                  background: "var(--surface)",
                  color: "var(--surface-text)",
                  padding: "12px",
                  borderRadius: 12,
                  marginBottom: 8,
                }}
              >
                <div style={{ marginBottom: 8 }}>
                  <BasedOnBadge basedOn={pending.basedOn} />
                </div>
                {isEditing ? (
                  <textarea
                    rows={3}
                    value={draftEdit}
                    onChange={(e) => setDraftEdit(e.target.value)}
                    style={{ width: "100%" }}
                  />
                ) : (
                  <p style={{ margin: 0 }}>{pending.draftText}</p>
                )}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {isEditing ? (
                  <button
                    type="button"
                    disabled={isSubmitting || draftEdit.trim().length === 0}
                    onClick={() => onConfirm(draftEdit, true)}
                  >
                    수정한 내용으로 확인
                  </button>
                ) : (
                  <>
                    <button type="button" disabled={isSubmitting} onClick={() => onConfirm(pending.draftText, false)}>
                      맞아요, 이대로 확인
                    </button>
                    <button type="button" disabled={isSubmitting} onClick={() => setIsEditing(true)}>
                      고쳐서 확인할게요
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
