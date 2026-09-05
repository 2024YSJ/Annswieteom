"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";

// Grows the composer with the text instead of staying single-line — capped so
// a very long paste doesn't push the fixed bottom bar to an unreasonable
// height; beyond this it scrolls internally like any textarea.
const TEXTAREA_MAX_HEIGHT_PX = 160;

export type ActiveStep = "period" | "categories" | "records" | "interview";

export type ComposerEvent =
  | { kind: "text"; value: string; nonce: number; forStep: ActiveStep }
  | { kind: "url"; value: string; nonce: number; forStep: ActiveStep }
  | { kind: "file"; file: File; nonce: number; forStep: ActiveStep };

/** The single shared chat input for the whole session screen (spec:
 * docs/specs/phase5_shared_chat_composer.md). Pure input-capture — it never
 * calls the API itself. Whichever Section is currently `activeStep` reacts to
 * the events this emits and owns the actual network calls, since Period and
 * Categories both need to interpret free text (extract-then-confirm) rather
 * than just forward it, and Records should not be special-cased relative to
 * them.
 *
 * Records and Interview both get the attach (📎) button — a record can now be
 * attached at any point during the interview, not just the dedicated Records
 * step. Period/Categories answers are always plain free text.
 */
const ATTACH_ENABLED_STEPS = new Set<ActiveStep>(["records", "interview"]);

export function ChatComposer({
  activeStep,
  onSend,
  disabled,
  prefillText,
}: {
  activeStep: ActiveStep;
  onSend: (event: ComposerEvent) => void;
  disabled?: boolean;
  /** AI가 이번 질문에 대해 미리 써본 답변 — 입력창에 편집 가능한 값으로 채워둔다.
   * 사용자가 그대로 보내든, 이어 쓰든, 고치든, 지우고 새로 쓰든 최종 선택은
   * 사용자 몫이다 (interview/answer -> interview/confirm의 확인 절차는 그대로
   * 거치므로 이 prefill이 정직성 가드레일을 건너뛰지 않는다). */
  prefillText?: string | null;
}) {
  const [text, setText] = useState("");
  const [isAttachMenuOpen, setIsAttachMenuOpen] = useState(false);
  const [isUrlFormOpen, setIsUrlFormOpen] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const nonceRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Re-measure on every text change, not just onChange — `text` also changes
  // from outside typing (a prefill arriving, or clearing after send), and
  // scrollHeight is only accurate once the browser has painted the new value.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT_PX)}px`;
  }, [text]);

  // Note: this component is remounted (via `key={activeStep}` in the
  // orchestrator) whenever the active step changes, so any uncommitted draft
  // text/popover state is naturally discarded instead of needing an effect —
  // stray keystrokes meant for one step's question can never leak into the
  // next step's context.

  // Adopt a new prefill the moment it arrives — "adjust state during render"
  // instead of an effect, so there's no extra render/flash before the box
  // fills in. Only reacts to prefillText actually changing (a fresh question),
  // not to every render, and never overwrites text the user already typed
  // in response to this same prefill.
  const [lastSeenPrefill, setLastSeenPrefill] = useState<string | null | undefined>(undefined);
  if (prefillText !== lastSeenPrefill) {
    setLastSeenPrefill(prefillText);
    setText(prefillText ?? "");
  }

  function sendText() {
    if (text.trim().length === 0) return;
    nonceRef.current += 1;
    onSend({ kind: "text", value: text, nonce: nonceRef.current, forStep: activeStep });
    setText("");
  }

  function sendUrl(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (urlDraft.trim().length === 0) return;
    nonceRef.current += 1;
    onSend({ kind: "url", value: urlDraft, nonce: nonceRef.current, forStep: activeStep });
    setUrlDraft("");
    setIsUrlFormOpen(false);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // allow re-selecting the same file later
    if (!file) return;
    nonceRef.current += 1;
    onSend({ kind: "file", file, nonce: nonceRef.current, forStep: activeStep });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {prefillText && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color: "var(--accent)" }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--accent)", display: "inline-block" }} />
          AI가 미리 써봤어요 · 이어 쓰거나 고쳐서 보내세요
        </div>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", position: "relative" }}>
        {ATTACH_ENABLED_STEPS.has(activeStep) && (
          <button
            type="button"
            onClick={() => setIsAttachMenuOpen((v) => !v)}
            title="첨부"
            aria-label="첨부"
            style={{ flexShrink: 0 }}
          >
            📎
          </button>
        )}
        {prefillText && (
          <button
            type="button"
            onClick={() => setText("")}
            title="지우고 새로 쓰기"
            aria-label="지우고 새로 쓰기"
            style={{ borderRadius: "50%", width: 34, height: 34, padding: 0, flexShrink: 0 }}
          >
            ↺
          </button>
        )}
        <textarea
          ref={textareaRef}
          placeholder="메시지를 입력하세요 (Shift+Enter로 줄바꿈)"
          value={text}
          disabled={disabled}
          rows={1}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              sendText();
            }
          }}
          style={{
            flex: 1,
            minWidth: 0,
            resize: "none",
            maxHeight: TEXTAREA_MAX_HEIGHT_PX,
            overflowY: "auto",
            fontFamily: "inherit",
            lineHeight: 1.4,
            borderColor: prefillText ? "var(--accent)" : undefined,
          }}
        />
        <button type="button" onClick={sendText} disabled={disabled || text.trim().length === 0} style={{ flexShrink: 0 }}>
          보내기
        </button>

        {ATTACH_ENABLED_STEPS.has(activeStep) && isAttachMenuOpen && (
          <div
            style={{
              position: "absolute",
              bottom: "100%",
              left: 0,
              marginBottom: 4,
              background: "var(--surface-strong)",
              color: "var(--surface-strong-text)",
              border: "1px solid var(--border-strong)",
              borderRadius: 8,
              padding: 4,
              display: "flex",
              flexDirection: "column",
              zIndex: 1,
            }}
          >
            <button
              type="button"
              onClick={() => {
                setIsUrlFormOpen(true);
                setIsAttachMenuOpen(false);
              }}
            >
              블로그 URL 추가
            </button>
            <button
              type="button"
              onClick={() => {
                fileInputRef.current?.click();
                setIsAttachMenuOpen(false);
              }}
            >
              이미지 추가
            </button>
          </div>
        )}
        {ATTACH_ENABLED_STEPS.has(activeStep) && (
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleFileChange}
            disabled={disabled}
            style={{ display: "none" }}
          />
        )}
      </div>

      {ATTACH_ENABLED_STEPS.has(activeStep) && isUrlFormOpen && (
        <form onSubmit={sendUrl} style={{ display: "flex", gap: 8 }}>
          <input
            type="url"
            required
            autoFocus
            placeholder="https://blog.naver.com/..."
            value={urlDraft}
            onChange={(e) => setUrlDraft(e.target.value)}
            style={{ flex: 1, minWidth: 0 }}
          />
          <button type="submit" disabled={disabled}>
            등록
          </button>
          <button type="button" onClick={() => setIsUrlFormOpen(false)}>
            취소
          </button>
        </form>
      )}
    </div>
  );
}
