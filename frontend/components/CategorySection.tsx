"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type ActivityCategoryRead, type CategoryInput } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { CATEGORY_LABELS } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";

interface SuggestionRow extends CategoryInput {
  localId: string;
}

let nextLocalId = 0;

export function CategorySection({
  sessionId,
  accessToken,
  mode,
  categories,
}: {
  sessionId: string;
  accessToken: string;
  mode: "completed" | "active";
  categories: ActivityCategoryRead[];
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [suggestions, setSuggestions] = useState<SuggestionRow[]>([]);
  const [isExtracting, setIsExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (mode === "completed") {
    const labels = categories
      .slice()
      .sort((a, b) => a.order_index - b.order_index)
      .map((c) => c.custom_label ?? CATEGORY_LABELS[c.category_type])
      .join(", ");
    return <ChatBubble side="right">선택한 활동: {labels}</ChatBubble>;
  }

  async function handleExtract() {
    setError(null);
    if (text.trim().length === 0) {
      setError("먼저 활동을 적어주세요.");
      return;
    }
    setIsExtracting(true);
    try {
      const { suggestions: found } = await sessionApi.extractCategories(sessionId, text, accessToken);
      // Replaces the previous list rather than accumulating — editing the
      // text and re-extracting starts from a fresh suggestion list.
      setSuggestions(found.map((s) => ({ ...s, localId: `${nextLocalId++}` })));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsExtracting(false);
    }
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
    <ChatBubble side="left">
      <div aria-live="polite">
        <p style={{ margin: "0 0 4px", fontWeight: "bold" }}>어떤 활동을 하셨나요?</p>
        <p style={{ margin: "0 0 12px", color: "#666" }}>
          쉬는 동안 어떤 활동을 하셨는지 자유롭게 적어주세요. AI가 활동 카테고리를 찾아드릴게요.
        </p>
      </div>

      <textarea
        rows={4}
        autoFocus
        placeholder="예: 편의점에서 6개월 정도 아르바이트를 했고, 정보처리기사 자격증도 땄어요."
        value={text}
        onChange={(e) => setText(e.target.value)}
        style={{ width: "100%" }}
      />
      <button type="button" onClick={handleExtract} disabled={isExtracting} style={{ marginTop: 8 }}>
        {isExtracting ? "찾는 중..." : suggestions.length > 0 ? "다시 찾기" : "카테고리 찾기"}
      </button>

      {suggestions.length > 0 && (
        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
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
        </div>
      )}

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      {suggestions.length > 0 && (
        <button type="button" onClick={handleSubmit} disabled={isSubmitting} style={{ marginTop: 12 }}>
          {isSubmitting ? "저장 중..." : "확인"}
        </button>
      )}
    </ChatBubble>
  );
}
