"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type ActivityCategoryRead, type CategoryInput } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { CATEGORY_LABELS } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";
import type { ComposerEvent } from "@/components/ChatComposer";

interface SuggestionRow extends CategoryInput {
  localId: string;
}

let nextLocalId = 0;

const QUESTION_TEXT = "쉬는 동안 어떤 활동을 하셨는지 자유롭게 적어주세요. AI가 활동 카테고리를 찾아드릴게요.";

export function CategorySection({
  sessionId,
  accessToken,
  mode,
  categories,
  composerEvent,
}: {
  sessionId: string;
  accessToken: string;
  mode: "completed" | "active";
  categories: ActivityCategoryRead[];
  composerEvent: ComposerEvent | null;
}) {
  const queryClient = useQueryClient();
  const [suggestions, setSuggestions] = useState<SuggestionRow[]>([]);
  const [isExtracting, setIsExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const highestNonceRef = useRef(0);

  useEffect(() => {
    if (mode !== "active" || !composerEvent || composerEvent.kind !== "text") return;
    const nonce = composerEvent.nonce;
    const text = composerEvent.value;
    highestNonceRef.current = nonce;

    async function run() {
      setError(null);
      setIsExtracting(true);
      try {
        const { suggestions: found } = await sessionApi.extractCategories(sessionId, text, accessToken);
        if (highestNonceRef.current !== nonce) return; // a newer request already resolved
        // Replaces the previous list rather than accumulating — sending a
        // new message re-extracts from scratch.
        setSuggestions(found.map((s) => ({ ...s, localId: `${nextLocalId++}` })));
      } catch (err) {
        if (highestNonceRef.current !== nonce) return;
        setError(errorMessage(err));
      } finally {
        if (highestNonceRef.current === nonce) setIsExtracting(false);
      }
    }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerEvent?.nonce]);

  if (mode === "completed") {
    const labels = categories
      .slice()
      .sort((a, b) => a.order_index - b.order_index)
      .map((c) => c.custom_label ?? CATEGORY_LABELS[c.category_type])
      .join(", ");
    return (
      <>
        <ChatBubble side="left">{QUESTION_TEXT}</ChatBubble>
        <ChatBubble side="right">선택한 활동: {labels}</ChatBubble>
      </>
    );
  }

  function updateLabel(localId: string, custom_label: string) {
    setSuggestions((prev) => prev.map((s) => (s.localId === localId ? { ...s, custom_label } : s)));
  }

  function removeSuggestion(localId: string) {
    setSuggestions((prev) => prev.filter((s) => s.localId !== localId));
  }

  function addManualSuggestion() {
    setSuggestions((prev) => [...prev, { category_type: "other", custom_label: "", localId: `${nextLocalId++}` }]);
  }

  async function handleSubmit() {
    setError(null);
    const cleaned = suggestions.filter((s) => (s.custom_label ?? "").trim().length > 0);
    if (cleaned.length === 0) {
      setError("하나 이상 있어야 해요.");
      return;
    }

    setIsSubmitting(true);
    try {
      await sessionApi.selectCategories(
        sessionId,
        cleaned.map(({ category_type, custom_label }) => ({ category_type, custom_label })),
        accessToken,
      );
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <>
      <ChatBubble side="left">
        <span aria-live="polite">{QUESTION_TEXT}</span>
      </ChatBubble>

      {isExtracting && <ChatBubble side="left">찾는 중...</ChatBubble>}

      {suggestions.length > 0 && !isExtracting && (
        <ChatBubble side="left">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {suggestions.map((s) => (
              <div key={s.localId} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  type="text"
                  value={s.custom_label ?? ""}
                  onChange={(e) => updateLabel(s.localId, e.target.value)}
                  style={{ flex: 1 }}
                />
                <button type="button" onClick={() => removeSuggestion(s.localId)}>
                  삭제
                </button>
              </div>
            ))}
            <button type="button" onClick={addManualSuggestion} style={{ alignSelf: "flex-start" }}>
              + 직접 추가
            </button>
            <p style={{ fontSize: 12, color: "#888", margin: 0 }}>다시 설명하려면 입력창에 다시 적어 보내세요.</p>
          </div>
          <button type="button" onClick={handleSubmit} disabled={isSubmitting} style={{ marginTop: 12 }}>
            {isSubmitting ? "저장 중..." : "확인"}
          </button>
        </ChatBubble>
      )}

      {error && <p style={{ color: "crimson" }}>{error}</p>}
    </>
  );
}
