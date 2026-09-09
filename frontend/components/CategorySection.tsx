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
  // 사용자가 방금 보낸 문장. 즉시 말풍선으로 되돌려주기 위한 것 — 이게 없으면
  // 보낸 직후 화면이 입력 전과 완전히 같아서 "먹통"으로 보인다(2026-09-09 실사용).
  const [sentText, setSentText] = useState<string | null>(null);
  // 추출을 한 번이라도 끝냈는지. suggestions가 빈 것만으로는 "아직 안 보냈다"와
  // "보냈는데 못 찾았다"를 구분할 수 없다.
  const [hasExtracted, setHasExtracted] = useState(false);
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
      // await 전에 먼저 그린다 — 요청이 접수됐다는 신호가 즉시 있어야 한다.
      setSentText(text);
      setHasExtracted(false);
      setIsExtracting(true);
      try {
        const { suggestions: found } = await sessionApi.extractCategories(sessionId, text, accessToken);
        if (highestNonceRef.current !== nonce) return; // a newer request already resolved
        // Replaces the previous list rather than accumulating — sending a
        // new message re-extracts from scratch.
        setSuggestions(found.map((s) => ({ ...s, localId: `${nextLocalId++}` })));
        setHasExtracted(true);
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

      {sentText && <ChatBubble side="right">{sentText}</ChatBubble>}

      {isExtracting && <ChatBubble side="left">찾는 중...</ChatBubble>}

      {/* "잘 모르겠어" 같은 답변에는 백엔드가 정상 200으로 빈 배열을 준다
          (프롬프트가 "못 찾겠으면 빈 배열"이라고 지시한다 — LLM은 설계대로
          동작한 것이다). 이 분기가 없으면 화면에 아무것도 안 그려져서 사이트가
          멈춘 것처럼 보였다. 재질문과 직접 입력을 같이 주는 이유는, 예시를
          줘도 계속 모르겠다는 사용자가 영영 다음 단계로 못 넘어가기 때문이다. */}
      {hasExtracted && suggestions.length === 0 && !isExtracting && (
        <ChatBubble side="left">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <span aria-live="polite">
              구체적인 활동이 잘 안 잡혔어요. 예를 들어 <b>편의점 알바</b>, <b>자격증 공부</b>, <b>운동</b>,
              <b> 가족 돌봄</b>처럼 적어주시면 카테고리를 찾아드릴게요.
            </span>
            <span style={{ fontSize: 13, color: "var(--muted-text)" }}>
              푹 쉬었거나 특별한 활동이 없었어도 괜찮아요 — 그것도 하나의 활동으로 적을 수 있어요.
            </span>
            <button type="button" onClick={addManualSuggestion} style={{ alignSelf: "flex-start" }}>
              직접 입력할게요
            </button>
          </div>
        </ChatBubble>
      )}

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
            <p style={{ fontSize: 12, color: "var(--muted-text)", margin: 0 }}>다시 설명하려면 입력창에 다시 적어 보내세요.</p>
          </div>
          <button type="button" onClick={handleSubmit} disabled={isSubmitting} style={{ marginTop: 12 }}>
            {isSubmitting ? "저장 중..." : "확인"}
          </button>
        </ChatBubble>
      )}

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}
    </>
  );
}
