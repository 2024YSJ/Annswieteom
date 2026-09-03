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
        {label && <div style={{ fontSize: 12, color: "#888", textAlign: "right" }}>{label}</div>}
        <div style={{ background: "#daf1ff", padding: "8px 12px", borderRadius: 12 }}>{children}</div>
      </div>
    );
  }

  if (variant === "card") {
    return (
      <div style={{ alignSelf: "flex-start", width: "100%" }}>
        {label && <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>{label}</div>}
        <div style={{ background: "#fff", border: "1px solid #eee", borderRadius: 12, padding: 16 }}>{children}</div>
      </div>
    );
  }

  return (
    <div style={{ alignSelf: "flex-start", maxWidth: "85%" }}>
      {label && <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>{label}</div>}
      <div style={{ background: "#f1f1f1", padding: "12px", borderRadius: 12 }}>{children}</div>
    </div>
  );
}
