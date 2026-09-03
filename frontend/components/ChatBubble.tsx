"use client";

import type { ReactNode } from "react";

/** Shared visual primitive for the unified session chat screen
 * (docs/specs/phase2_unified_chat_ui.md). Two shapes:
 * - `side="right"`: a compact confirmed-summary bubble (things the user
 *   already submitted) — narrow, tinted background, like InterviewChatThread's
 *   confirmed-fact bubbles.
 * - `side="left"`: a wide card (an "AI is asking" prompt containing a real
 *   form) — full-width white card with a border, NOT a narrow chat bubble,
 *   since checkboxes/date pickers/drag-and-drop don't fit a 1-3 line bubble.
 */
export function ChatBubble({
  side,
  label,
  children,
}: {
  side: "left" | "right";
  label?: string;
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

  return (
    <div style={{ alignSelf: "flex-start", width: "100%" }}>
      {label && <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>{label}</div>}
      <div style={{ background: "#fff", border: "1px solid #eee", borderRadius: 12, padding: 16 }}>{children}</div>
    </div>
  );
}
