"use client";

import { useState } from "react";
import type { ParagraphRead, SentenceRead } from "@/lib/api-client";
import { sentenceBadge } from "@/lib/sentence-badge";
import { EvidenceTag } from "@/components/EvidenceTag";

/** 문단/문장 렌더링 — ResultSection.tsx(편집 가능한 실제 결과 화면)와
 * app/demo/page.tsx(원클릭 데모, read-only)가 공유한다. 편집 관련 콜백을
 * 전부 옵셔널로 두고, 콜백이 없으면 해당 버튼 자체를 숨기는 방식으로
 * "읽기 전용"을 표현한다 — 별도 readOnly 플래그 없이, 두 화면이 배지/근거
 * 렌더링 로직만은 절대 갈라지지 않게 한다.
 */

export function SentenceRow({
  sentence,
  onSave,
  onRegenerate,
  onMove,
  canMovePrev,
  canMoveNext,
  disabled,
}: {
  sentence: SentenceRead;
  onSave?: (text: string) => Promise<void>;
  onRegenerate?: () => Promise<void>;
  onMove?: (direction: "prev" | "next") => Promise<void>;
  canMovePrev?: boolean;
  canMoveNext?: boolean;
  disabled?: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [text, setText] = useState(sentence.text);

  return (
    <div
      style={{
        padding: 12,
        borderRadius: "var(--radius-md)",
        marginBottom: 8,
        // 일관성 검사에 걸린 문장은 앰버로 표시한다 — 에러가 아니라 "한 번 더
        // 봐야 하는 것"이라, 실패 메시지의 빨강과 색을 다르게 쓴다.
        background: sentence.consistency_check_passed ? "var(--surface-strong)" : "var(--caution-surface)",
        color: sentence.consistency_check_passed ? "var(--surface-strong-text)" : "var(--caution-text)",
        border: sentence.consistency_check_passed ? "1px solid var(--border)" : "1px solid var(--caution-border)",
      }}
    >
      {!sentence.consistency_check_passed && (
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--caution-text)", marginBottom: 4 }}>⚠ 확인이 더 필요한 문장</div>
      )}

      <div style={{ fontSize: 11, opacity: 0.75, marginBottom: 4 }}>{sentenceBadge(sentence)}</div>

      {isEditing ? (
        <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} style={{ width: "100%" }} />
      ) : (
        <p style={{ margin: 0 }}>{sentence.text}</p>
      )}

      <EvidenceTag evidence={sentence.evidence} />

      {(onSave || onRegenerate || onMove) && (
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          {isEditing ? (
            <>
              <button
                type="button"
                disabled={disabled || text.trim().length === 0}
                onClick={async () => {
                  await onSave?.(text);
                  setIsEditing(false);
                }}
              >
                저장
              </button>
              <button type="button" disabled={disabled} onClick={() => { setText(sentence.text); setIsEditing(false); }}>
                취소
              </button>
            </>
          ) : (
            <>
              {onSave && (
                <button type="button" disabled={disabled} onClick={() => setIsEditing(true)}>
                  직접 수정
                </button>
              )}
              {onRegenerate && (
                <button type="button" disabled={disabled} onClick={onRegenerate}>
                  다시 생성
                </button>
              )}
              {onMove && (
                <>
                  <button type="button" disabled={disabled || !canMovePrev} onClick={() => onMove("prev")}>
                    ◀ 이전 문단으로
                  </button>
                  <button type="button" disabled={disabled || !canMoveNext} onClick={() => onMove("next")}>
                    다음 문단으로 ▶
                  </button>
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function ParagraphSection({
  paragraph,
  isFirst,
  isLast,
  onSaveSentence,
  onRegenerateSentence,
  onMoveSentence,
  onRenameTopic,
  onToggleConfirmed,
  onMergeWithNext,
  onDelete,
  disabled,
}: {
  paragraph: ParagraphRead;
  isFirst: boolean;
  isLast: boolean;
  onSaveSentence?: (sentenceId: string, text: string) => Promise<void>;
  onRegenerateSentence?: (sentenceId: string) => Promise<void>;
  onMoveSentence?: (sentenceId: string, direction: "prev" | "next") => Promise<void>;
  onRenameTopic?: (topic: string) => Promise<void>;
  onToggleConfirmed?: () => Promise<void>;
  onMergeWithNext?: () => Promise<void>;
  onDelete?: () => Promise<void>;
  disabled?: boolean;
}) {
  const [isEditingTopic, setIsEditingTopic] = useState(false);
  const [topicDraft, setTopicDraft] = useState(paragraph.topic);

  return (
    <div style={{ marginBottom: 24, paddingBottom: 16, borderBottom: "1px solid var(--border)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        {isEditingTopic ? (
          <>
            <input
              type="text"
              value={topicDraft}
              onChange={(e) => setTopicDraft(e.target.value)}
              style={{ fontWeight: 700, flex: 1, minWidth: 120 }}
            />
            <button
              type="button"
              disabled={disabled || topicDraft.trim().length === 0}
              onClick={async () => {
                await onRenameTopic?.(topicDraft);
                setIsEditingTopic(false);
              }}
            >
              저장
            </button>
            <button type="button" disabled={disabled} onClick={() => { setTopicDraft(paragraph.topic); setIsEditingTopic(false); }}>
              취소
            </button>
          </>
        ) : (
          <>
            <strong style={{ flex: 1 }}>{paragraph.topic || "(제목 없음)"}</strong>
            {onRenameTopic && (
              <button type="button" disabled={disabled} onClick={() => setIsEditingTopic(true)} style={{ fontSize: 12 }}>
                제목 수정
              </button>
            )}
            {onToggleConfirmed && (
              <button
                type="button"
                disabled={disabled}
                onClick={onToggleConfirmed}
                style={{ fontSize: 12, color: paragraph.user_confirmed ? "var(--accent)" : undefined }}
              >
                {paragraph.user_confirmed ? "✓ 확인됨" : "이 묶음 확인"}
              </button>
            )}
            {onMergeWithNext && !isLast && (
              <button type="button" disabled={disabled} onClick={onMergeWithNext} style={{ fontSize: 12 }}>
                다음 문단과 합치기
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  if (window.confirm("이 문단을 삭제할까요? 안의 문장이 전부 사라지고 되돌릴 수 없습니다.")) onDelete();
                }}
                style={{ fontSize: 12, color: "var(--danger)" }}
              >
                문단 삭제
              </button>
            )}
          </>
        )}
      </div>

      {paragraph.sentences.map((sentence) => (
        <SentenceRow
          key={sentence.id}
          sentence={sentence}
          disabled={disabled}
          onSave={onSaveSentence ? (text) => onSaveSentence(sentence.id, text) : undefined}
          onRegenerate={onRegenerateSentence ? () => onRegenerateSentence(sentence.id) : undefined}
          onMove={onMoveSentence ? (direction) => onMoveSentence(sentence.id, direction) : undefined}
          canMovePrev={!isFirst}
          canMoveNext={!isLast}
        />
      ))}
    </div>
  );
}
