"use client";

import { useState } from "react";
import type { BasedOnRead, ConfirmedFactRead } from "@/lib/api-client";

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
  confirmedFacts,
  pending,
  onConfirm,
  isSubmitting,
}: {
  confirmedFacts: ConfirmedFactRead[];
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {confirmedFacts.map((fact) => (
        <div key={fact.id} style={{ alignSelf: "flex-end", maxWidth: "80%" }}>
          <div style={{ fontSize: 12, color: "#888", textAlign: "right" }}>{FACT_TYPE_LABELS[fact.fact_type]} · 확인됨</div>
          <div style={{ background: "#daf1ff", padding: "8px 12px", borderRadius: 12 }}>{fact.content}</div>
        </div>
      ))}

      {pending && (
        <div style={{ alignSelf: "flex-start", maxWidth: "85%" }}>
          <div style={{ fontSize: 12, color: "#888" }}>{pending.stepLabel}</div>
          <div style={{ background: "#f1f1f1", padding: "12px", borderRadius: 12, marginBottom: 8 }}>
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
  );
}
