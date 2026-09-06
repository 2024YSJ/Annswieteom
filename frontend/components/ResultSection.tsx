"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  documentApi,
  type DocumentRead,
  type ParagraphRead,
  type SentenceRead,
  type SessionStatus,
  type Tone,
} from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { EvidenceTag } from "@/components/EvidenceTag";
import { ToneSlider } from "@/components/ToneSlider";
import { ChatBubble } from "@/components/ChatBubble";
import { LoadingNotice } from "@/components/LoadingNotice";

function SentenceRow({
  sentence,
  onSave,
  onRegenerate,
  onMove,
  canMovePrev,
  canMoveNext,
  disabled,
}: {
  sentence: SentenceRead;
  onSave: (text: string) => Promise<void>;
  onRegenerate: () => Promise<void>;
  onMove: (direction: "prev" | "next") => Promise<void>;
  canMovePrev: boolean;
  canMoveNext: boolean;
  disabled: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [text, setText] = useState(sentence.text);

  return (
    <div
      style={{
        padding: 12,
        borderRadius: 8,
        marginBottom: 8,
        background: sentence.consistency_check_passed ? "var(--surface-strong)" : "var(--surface-warn)",
        color: sentence.consistency_check_passed ? "var(--surface-strong-text)" : "var(--surface-warn-text)",
        border: sentence.consistency_check_passed ? "1px solid var(--border)" : "1px solid #f0c36d",
      }}
    >
      {!sentence.consistency_check_passed && (
        <div style={{ fontSize: 12, color: "#8a6d1a", marginBottom: 4 }}>⚠ 확인이 더 필요한 문장</div>
      )}

      {isEditing ? (
        <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} style={{ width: "100%" }} />
      ) : (
        <p style={{ margin: 0 }}>{sentence.text}</p>
      )}

      <EvidenceTag evidence={sentence.evidence} />

      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        {isEditing ? (
          <>
            <button
              type="button"
              disabled={disabled || text.trim().length === 0}
              onClick={async () => {
                await onSave(text);
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
            <button type="button" disabled={disabled} onClick={() => setIsEditing(true)}>
              직접 수정
            </button>
            <button type="button" disabled={disabled} onClick={onRegenerate}>
              다시 생성
            </button>
            <button type="button" disabled={disabled || !canMovePrev} onClick={() => onMove("prev")}>
              ◀ 이전 문단으로
            </button>
            <button type="button" disabled={disabled || !canMoveNext} onClick={() => onMove("next")}>
              다음 문단으로 ▶
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function ParagraphSection({
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
  onSaveSentence: (sentenceId: string, text: string) => Promise<void>;
  onRegenerateSentence: (sentenceId: string) => Promise<void>;
  onMoveSentence: (sentenceId: string, direction: "prev" | "next") => Promise<void>;
  onRenameTopic: (topic: string) => Promise<void>;
  onToggleConfirmed: () => Promise<void>;
  onMergeWithNext: () => Promise<void>;
  onDelete: () => Promise<void>;
  disabled: boolean;
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
                await onRenameTopic(topicDraft);
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
            <button type="button" disabled={disabled} onClick={() => setIsEditingTopic(true)} style={{ fontSize: 12 }}>
              제목 수정
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={onToggleConfirmed}
              style={{ fontSize: 12, color: paragraph.user_confirmed ? "var(--accent)" : undefined }}
            >
              {paragraph.user_confirmed ? "✓ 확인됨" : "이 묶음 확인"}
            </button>
            {!isLast && (
              <button type="button" disabled={disabled} onClick={onMergeWithNext} style={{ fontSize: 12 }}>
                다음 문단과 합치기
              </button>
            )}
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                if (window.confirm("이 문단을 삭제할까요? 안의 문장이 전부 사라지고 되돌릴 수 없습니다.")) onDelete();
              }}
              style={{ fontSize: 12, color: "crimson" }}
            >
              문단 삭제
            </button>
          </>
        )}
      </div>

      {paragraph.sentences.map((sentence) => (
        <SentenceRow
          key={sentence.id}
          sentence={sentence}
          disabled={disabled}
          onSave={(text) => onSaveSentence(sentence.id, text)}
          onRegenerate={() => onRegenerateSentence(sentence.id)}
          onMove={(direction) => onMoveSentence(sentence.id, direction)}
          canMovePrev={!isFirst}
          canMoveNext={!isLast}
        />
      ))}
    </div>
  );
}

export function ResultSection({
  sessionId,
  accessToken,
  status,
}: {
  sessionId: string;
  accessToken: string;
  status: SessionStatus;
}) {
  const queryClient = useQueryClient();

  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [exportedText, setExportedText] = useState<string | null>(null);
  const generateFiredRef = useRef(false);

  const {
    data: document,
    isLoading: docLoading,
    error: docError,
  } = useQuery({
    queryKey: queryKeys.document(sessionId),
    queryFn: () => documentApi.get(sessionId, accessToken),
    enabled: status === "RESULT_REVIEW",
  });

  useEffect(() => {
    if (status !== "RESULT_GENERATE" || generateFiredRef.current) return;
    generateFiredRef.current = true;

    documentApi
      .generate(sessionId, "neutral", accessToken)
      .then((doc) => {
        queryClient.setQueryData(queryKeys.document(sessionId), doc);
        queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      })
      .catch((err) => setError(errorMessage(err)));
  }, [status, sessionId, accessToken, queryClient]);

  function setDocument(doc: DocumentRead) {
    queryClient.setQueryData(queryKeys.document(sessionId), doc);
  }

  function replaceSentence(updated: SentenceRead) {
    if (!document) return;
    setDocument({
      ...document,
      paragraphs: document.paragraphs.map((p) => ({
        ...p,
        sentences: p.sentences.map((s) => (s.id === updated.id ? updated : s)),
      })),
    });
  }

  async function handleToneChange(tone: Tone) {
    setError(null);
    setIsBusy(true);
    try {
      const doc = await documentApi.regenerate(sessionId, tone, accessToken);
      setDocument(doc);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSaveSentence(sentenceId: string, text: string) {
    try {
      const updated = await documentApi.updateSentence(sessionId, sentenceId, text, accessToken);
      replaceSentence(updated);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleRegenerateSentence(sentenceId: string) {
    setError(null);
    setIsBusy(true);
    try {
      const updated = await documentApi.regenerateSentence(sessionId, sentenceId, accessToken);
      replaceSentence(updated);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsBusy(false);
    }
  }

  // Moving a sentence and merging paragraphs both change which paragraph
  // owns which sentences (not just one sentence's own fields), so the
  // simplest correct way to reflect the result is to refetch the whole
  // document rather than trying to patch the cached shape by hand.
  async function refetchDocument() {
    const doc = await documentApi.get(sessionId, accessToken);
    setDocument(doc);
  }

  async function handleMoveSentence(sentenceId: string, direction: "prev" | "next") {
    setError(null);
    setIsBusy(true);
    try {
      await documentApi.moveSentence(sessionId, sentenceId, direction, accessToken);
      await refetchDocument();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRenameTopic(paragraphId: string, topic: string) {
    setError(null);
    try {
      const updated = await documentApi.updateParagraph(sessionId, paragraphId, { topic }, accessToken);
      if (!document) return;
      setDocument({ ...document, paragraphs: document.paragraphs.map((p) => (p.id === paragraphId ? updated : p)) });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleToggleConfirmed(paragraph: ParagraphRead) {
    setError(null);
    try {
      const updated = await documentApi.updateParagraph(
        sessionId,
        paragraph.id,
        { user_confirmed: !paragraph.user_confirmed },
        accessToken,
      );
      if (!document) return;
      setDocument({ ...document, paragraphs: document.paragraphs.map((p) => (p.id === paragraph.id ? updated : p)) });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleMergeWithNext(paragraphId: string) {
    setError(null);
    setIsBusy(true);
    try {
      await documentApi.mergeParagraphWithNext(sessionId, paragraphId, accessToken);
      await refetchDocument();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDeleteParagraph(paragraphId: string) {
    setError(null);
    setIsBusy(true);
    try {
      await documentApi.deleteParagraph(sessionId, paragraphId, accessToken);
      await refetchDocument();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleFinalize() {
    setError(null);
    setIsBusy(true);
    try {
      const doc = await documentApi.finalize(sessionId, accessToken);
      setDocument(doc);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleExport() {
    setError(null);
    try {
      const text = await documentApi.exportText(sessionId, accessToken);
      setExportedText(text);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleCopy() {
    if (exportedText) await navigator.clipboard.writeText(exportedText);
  }

  if (status === "RESULT_GENERATE" && !document) {
    return (
      <ChatBubble side="left" variant="card">
        <LoadingNotice label="초안을 생성하는 중이에요..." />
      </ChatBubble>
    );
  }
  if (docLoading && !document) {
    return (
      <ChatBubble side="left" variant="card">
        <LoadingNotice />
      </ChatBubble>
    );
  }
  if (docError && !document) {
    return <ChatBubble side="left" variant="card"><p style={{ color: "crimson", margin: 0 }}>{errorMessage(docError)}</p></ChatBubble>;
  }
  if (!document) return null;

  const paragraphs = document.paragraphs.slice().sort((a, b) => a.order_index - b.order_index);
  const isReadOnly = isBusy || document.status === "FINAL";

  return (
    <ChatBubble side="left" variant="card" label="완성된 커리어 내러티브">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <ToneSlider value={document.tone} onChange={handleToneChange} disabled={isReadOnly} />
        <span style={{ fontSize: 12, color: "var(--muted-text)" }}>버전 {document.version} · {document.status === "FINAL" ? "확정됨" : "초안"}</span>
      </div>

      {!isReadOnly && paragraphs.length > 1 && (
        <p style={{ fontSize: 13, color: "var(--muted-text)", marginTop: 0 }}>
          문단별로 묶인 내용이 맞는지 확인해주세요 — 제목을 고치거나, 잘못 묶인 문장을 옆 문단으로 옮기거나, 같은 이야기인 인접 문단을 합칠 수 있어요.
        </p>
      )}

      {paragraphs.map((paragraph, index) => (
        <ParagraphSection
          key={paragraph.id}
          paragraph={paragraph}
          isFirst={index === 0}
          isLast={index === paragraphs.length - 1}
          disabled={isReadOnly}
          onSaveSentence={handleSaveSentence}
          onRegenerateSentence={handleRegenerateSentence}
          onMoveSentence={handleMoveSentence}
          onRenameTopic={(topic) => handleRenameTopic(paragraph.id, topic)}
          onToggleConfirmed={() => handleToggleConfirmed(paragraph)}
          onMergeWithNext={() => handleMergeWithNext(paragraph.id)}
          onDelete={() => handleDeleteParagraph(paragraph.id)}
        />
      ))}

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <div style={{ marginTop: 24, display: "flex", gap: 8 }}>
        {document.status !== "FINAL" ? (
          <button type="button" disabled={isBusy} onClick={handleFinalize}>
            최종 확정
          </button>
        ) : (
          <button type="button" onClick={handleExport}>
            텍스트로 내보내기
          </button>
        )}
      </div>

      {exportedText && (
        <div style={{ marginTop: 16 }}>
          <textarea readOnly rows={10} value={exportedText} style={{ width: "100%" }} />
          <button type="button" onClick={handleCopy} style={{ marginTop: 8 }}>
            클립보드에 복사
          </button>
        </div>
      )}
    </ChatBubble>
  );
}
