"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { documentApi, type DocumentRead, type SentenceRead, type SessionStatus, type Tone } from "@/lib/api-client";
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
  disabled,
}: {
  sentence: SentenceRead;
  onSave: (text: string) => Promise<void>;
  onRegenerate: () => Promise<void>;
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

      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
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
          </>
        )}
      </div>
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
    if (!document) return;
    try {
      const updated = await documentApi.updateSentence(sessionId, sentenceId, text, accessToken);
      setDocument({ ...document, sentences: document.sentences.map((s) => (s.id === sentenceId ? updated : s)) });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleRegenerateSentence(sentenceId: string) {
    if (!document) return;
    setError(null);
    setIsBusy(true);
    try {
      const updated = await documentApi.regenerateSentence(sessionId, sentenceId, accessToken);
      setDocument({ ...document, sentences: document.sentences.map((s) => (s.id === sentenceId ? updated : s)) });
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

  return (
    <ChatBubble side="left" variant="card" label="완성된 커리어 내러티브">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <ToneSlider value={document.tone} onChange={handleToneChange} disabled={isBusy || document.status === "FINAL"} />
        <span style={{ fontSize: 12, color: "var(--muted-text)" }}>버전 {document.version} · {document.status === "FINAL" ? "확정됨" : "초안"}</span>
      </div>

      {document.sentences
        .slice()
        .sort((a, b) => a.order_index - b.order_index)
        .map((sentence) => (
          <SentenceRow
            key={sentence.id}
            sentence={sentence}
            disabled={isBusy || document.status === "FINAL"}
            onSave={(text) => handleSaveSentence(sentence.id, text)}
            onRegenerate={() => handleRegenerateSentence(sentence.id)}
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
