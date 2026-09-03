"use client";

import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type ActivityCategoryRead, type CategoryType } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { CATEGORY_LABELS } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";

const ALL_CATEGORIES = Object.keys(CATEGORY_LABELS) as CategoryType[];

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
  const [selected, setSelected] = useState<CategoryType[]>([]);
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

  function toggle(category: CategoryType) {
    setSelected((prev) => (prev.includes(category) ? prev.filter((c) => c !== category) : [...prev, category]));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (selected.length === 0) {
      setError("하나 이상 선택해주세요.");
      return;
    }

    setIsSubmitting(true);
    try {
      await sessionApi.selectCategories(sessionId, selected, accessToken);
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
        <p style={{ margin: "0 0 12px", color: "#666" }}>해당하는 활동을 모두 선택해주세요 (복수 선택 가능).</p>
      </div>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {ALL_CATEGORIES.map((category, index) => (
          <label key={category} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              autoFocus={index === 0}
              checked={selected.includes(category)}
              onChange={() => toggle(category)}
            />
            {CATEGORY_LABELS[category]}
          </label>
        ))}
        {error && <p style={{ color: "crimson" }}>{error}</p>}
        <button type="submit" disabled={isSubmitting} style={{ alignSelf: "flex-start", marginTop: 4 }}>
          {isSubmitting ? "저장 중..." : "다음"}
        </button>
      </form>
    </ChatBubble>
  );
}
