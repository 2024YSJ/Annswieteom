"use client";

import { useRef, useState, type ChangeEvent } from "react";

export type ActiveStep = "period" | "categories" | "records";

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
 * Only Records gets the attach (📎) button — Period/Categories answers are
 * always free text.
 */
export function ChatComposer({
  activeStep,
  onSend,
  disabled,
}: {
  activeStep: ActiveStep;
  onSend: (event: ComposerEvent) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const [isAttachMenuOpen, setIsAttachMenuOpen] = useState(false);
  const [isUrlFormOpen, setIsUrlFormOpen] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const nonceRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Note: this component is remounted (via `key={activeStep}` in the
  // orchestrator) whenever the active step changes, so any uncommitted draft
  // text/popover state is naturally discarded instead of needing an effect —
  // stray keystrokes meant for one step's question can never leak into the
  // next step's context.

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
      <div style={{ display: "flex", gap: 8, alignItems: "center", position: "relative" }}>
        {activeStep === "records" && (
          <button type="button" onClick={() => setIsAttachMenuOpen((v) => !v)} title="첨부" aria-label="첨부">
            📎
          </button>
        )}
        <input
          type="text"
          placeholder="메시지를 입력하세요"
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              sendText();
            }
          }}
          style={{ flex: 1 }}
        />
        <button type="button" onClick={sendText} disabled={disabled || text.trim().length === 0}>
          보내기
        </button>

        {activeStep === "records" && isAttachMenuOpen && (
          <div
            style={{
              position: "absolute",
              bottom: "100%",
              left: 0,
              marginBottom: 4,
              background: "#fff",
              border: "1px solid #ddd",
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
        {activeStep === "records" && (
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

      {activeStep === "records" && isUrlFormOpen && (
        <form onSubmit={sendUrl} style={{ display: "flex", gap: 8 }}>
          <input
            type="url"
            required
            autoFocus
            placeholder="https://blog.naver.com/..."
            value={urlDraft}
            onChange={(e) => setUrlDraft(e.target.value)}
            style={{ flex: 1 }}
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
