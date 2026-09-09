"use client";

import type { ReactNode } from "react";

/** Shared visual primitive for the unified session chat screen
 * (docs/specs/phase2_unified_chat_ui.md). Two shapes:
 * - `side="right"`: a compact confirmed-summary bubble (things the user
 *   already submitted) — narrow, tinted background, like InterviewChatThread's
 *   confirmed-fact bubbles.
 * - `side="left"`: an AI-side bubble, in one of two variants:
 *   - `variant="message"` (default): narrow (maxWidth 85%) gray bubble, for
 *     plain chat-message content — questions, drafts, short confirmations.
 *   - `variant="card"`: wide, white, bordered card — for content that
 *     genuinely isn't message-shaped (e.g. ResultSection's tone slider +
 *     sentence editor). Only use this when the content wouldn't fit a normal
 *     chat bubble; don't reach for it just because a section has a form.
 */
export function ChatBubble({
  side,
  label,
  variant = "message",
  children,
}: {
  side: "left" | "right";
  label?: string;
  variant?: "card" | "message";
  children: ReactNode;
}) {
  if (side === "right") {
    return (
      <div style={{ alignSelf: "flex-end", maxWidth: "80%" }}>
        {label && <div style={{ fontSize: 12, color: "var(--muted-text)", textAlign: "right" }}>{label}</div>}
        <div
          style={{
            background: "var(--accent-surface)",
            color: "var(--accent-surface-text)",
            padding: "8px 13px",
            borderRadius: "var(--radius-lg)",
          }}
        >
          {children}
        </div>
      </div>
    );
  }

  if (variant === "card") {
    return (
      <div style={{ alignSelf: "flex-start", width: "100%" }}>
        {label && <div style={{ fontSize: 12, color: "var(--muted-text)", marginBottom: 4 }}>{label}</div>}
        <div
          style={{
            background: "var(--surface-strong)",
            color: "var(--surface-strong-text)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-xl)",
            boxShadow: "var(--shadow-sm)",
            padding: 18,
          }}
        >
          {children}
        </div>
      </div>
    );
  }

  return (
    <div style={{ alignSelf: "flex-start", maxWidth: "85%" }}>
      {label && <div style={{ fontSize: 12, color: "var(--muted-text)", marginBottom: 4 }}>{label}</div>}
      {/* 흰 배경 위에서는 --surface(거의 흰색)만으로 면이 구분되지 않아서,
       * 시스템 원칙대로 얇은 보더를 함께 준다. */}
      <div
        style={{
          background: "var(--surface)",
          color: "var(--surface-text)",
          border: "1px solid var(--border)",
          padding: "10px 14px",
          borderRadius: "var(--radius-lg)",
        }}
      >
        {children}
      </div>
    </div>
  );
}
