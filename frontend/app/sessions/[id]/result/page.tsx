"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { documentApi, type DocumentRead, type SentenceRead, type Tone } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { pathForStatus } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { useSessionContext } from "@/lib/use-session-context";
import { useAuth } from "@/lib/auth-context";
import { EvidenceTag } from "@/components/EvidenceTag";
import { ToneSlider } from "@/components/ToneSlider";

const RESULT_STATUSES = new Set(["RESULT_GENERATE", "RESULT_REVIEW"]);

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
        background: sentence.consistency_check_passed ? "#fff" : "#fff8e1",
        border: sentence.consistency_check_passed ? "1px solid #eee" : "1px solid #f0c36d",
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

export default function ResultPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const router = useRouter();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const { data: ctx, isLoading: ctxLoading, error: ctxError } = useSessionContext(sessionId);

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
    queryFn: () => documentApi.get(sessionId, accessToken!),
    enabled: !!accessToken && ctx?.status === "RESULT_REVIEW",
  });

  useEffect(() => {
    if (!ctx) return;
    if (!RESULT_STATUSES.has(ctx.status)) {
      router.replace(pathForStatus(sessionId, ctx.status));
      return;
    }
    if (ctx.status !== "RESULT_GENERATE" || generateFiredRef.current) return;
    generateFiredRef.current = true;

    documentApi
      .generate(sessionId, "neutral", accessToken!)
      .then((doc) => {
        queryClient.setQueryData(queryKeys.document(sessionId), doc);
        queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      })
      .catch((err) => setError(errorMessage(err)));
  }, [ctx, sessionId, accessToken, router, queryClient]);

  function setDocument(doc: DocumentRead) {
    queryClient.setQueryData(queryKeys.document(sessionId), doc);
  }

  async function handleToneChange(tone: Tone) {
    setError(null);
    setIsBusy(true);
    try {
      const doc = await documentApi.regenerate(sessionId, tone, accessToken!);
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
      const updated = await documentApi.updateSentence(sessionId, sentenceId, text, accessToken!);
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
      const updated = await documentApi.regenerateSentence(sessionId, sentenceId, accessToken!);
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
      const doc = await documentApi.finalize(sessionId, accessToken!);
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
      const text = await documentApi.exportText(sessionId, accessToken!);
      setExportedText(text);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleCopy() {
    if (exportedText) await navigator.clipboard.writeText(exportedText);
  }

  if (ctxLoading || !ctx) return <main style={{ maxWidth: 720, margin: "80px auto" }}>불러오는 중...</main>;
  if (ctxError) {
    return (
      <main style={{ maxWidth: 720, margin: "80px auto", padding: "0 16px" }}>
        <p style={{ color: "crimson" }}>{errorMessage(ctxError)}</p>
      </main>
    );
  }

  if (ctx.status === "RESULT_GENERATE" && !document) {
    return <main style={{ maxWidth: 720, margin: "80px auto", padding: "0 16px" }}>초안을 생성하는 중이에요...</main>;
  }
  if (docLoading && !document) return <main style={{ maxWidth: 720, margin: "80px auto" }}>불러오는 중...</main>;
  if (docError && !document) {
    return (
      <main style={{ maxWidth: 720, margin: "80px auto", padding: "0 16px" }}>
        <p style={{ color: "crimson" }}>{errorMessage(docError)}</p>
      </main>
    );
  }
  if (!document) return null;

  return (
    <main style={{ maxWidth: 720, margin: "80px auto", padding: "0 16px" }}>
      <h1>완성된 커리어 내러티브</h1>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <ToneSlider value={document.tone} onChange={handleToneChange} disabled={isBusy || document.status === "FINAL"} />
        <span style={{ fontSize: 12, color: "#888" }}>버전 {document.version} · {document.status === "FINAL" ? "확정됨" : "초안"}</span>
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
    </main>
  );
}
