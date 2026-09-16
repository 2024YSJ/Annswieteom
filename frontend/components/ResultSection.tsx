"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  documentApi,
  sessionApi,
  type DocumentRead,
  type ParagraphRead,
  type SentenceRead,
  type SessionStatus,
  type Tone,
  type UnverifiedSentence,
} from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ToneSlider } from "@/components/ToneSlider";
import { ChatBubble } from "@/components/ChatBubble";
import { LoadingNotice } from "@/components/LoadingNotice";
import { TrustScoreboard } from "@/components/TrustScoreboard";
import { ParagraphSection } from "@/components/DocumentView";

/** finalize가 409로 막았을 때 서버가 함께 내려준 문장 목록. 그 형태가 아니면
 * null을 돌려 평범한 에러 메시지 경로로 보낸다. */
function unverifiedSentencesFrom(err: unknown): UnverifiedSentence[] | null {
  if (!(err instanceof ApiError) || err.detail !== "unverified_sentences") return null;
  const payload = err.payload as { sentences?: UnverifiedSentence[] } | null;
  return payload?.sentences ?? null;
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
  const router = useRouter();
  const queryClient = useQueryClient();

  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [unverified, setUnverified] = useState<UnverifiedSentence[] | null>(null);
  const [isStartingJobSearch, setIsStartingJobSearch] = useState(false);
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

  async function handleFinalize(acknowledgeUnverified = false) {
    setError(null);
    setUnverified(null);
    setIsBusy(true);
    try {
      const doc = await documentApi.finalize(sessionId, accessToken, acknowledgeUnverified);
      setDocument(doc);
    } catch (err) {
      // 서버가 정합성 검사에 걸린 문장 목록을 함께 내려준다 — 일반 에러 메시지로
      // 뭉개지 말고 어떤 문장이 걸렸는지 그대로 보여준 뒤, 그래도 확정할지
      // 사용자가 정하게 한다.
      const sentences = unverifiedSentencesFrom(err);
      if (sentences) {
        setUnverified(sentences);
      } else {
        setError(errorMessage(err));
      }
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

  async function handleStartJobSearch() {
    setError(null);
    setIsStartingJobSearch(true);
    try {
      const jobSession = await sessionApi.create(accessToken, {
        kind: "job_search",
        linked_gap_session_id: sessionId,
      });
      router.push(`/sessions/${jobSession.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setIsStartingJobSearch(false);
    }
  }

  if (status === "RESULT_GENERATE" && !document) {
    return (
      <ChatBubble side="left" variant="card">
        <LoadingNotice
          label="초안을 생성하는 중이에요..."
          notice="경력 활동마다 문장을 만들고 근거를 하나씩 붙이는 중이에요. 활동이 여러 개면 몇 분 걸릴 수 있으니, 창을 닫지 말고 기다려주세요 🙏"
        />
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
    return <ChatBubble side="left" variant="card"><p style={{ color: "var(--danger)", margin: 0 }}>{errorMessage(docError)}</p></ChatBubble>;
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

      <TrustScoreboard sessionId={sessionId} accessToken={accessToken} enabled={document.status === "FINAL"} />

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

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      {unverified && (
        <div
          style={{
            marginTop: 16,
            padding: 12,
            borderRadius: "var(--radius-md)",
            background: "var(--caution-surface)",
            color: "var(--caution-text)",
            border: "1px solid var(--caution-border)",
          }}
        >
          <p style={{ margin: "0 0 8px", fontWeight: 600 }}>
            아래 {unverified.length}개 문장이 근거와 맞지 않아 보여요. 확인 후 확정해주세요.
          </p>
          <ul style={{ margin: "0 0 12px", paddingLeft: 20 }}>
            {unverified.map((sentence) => (
              <li key={sentence.id}>{sentence.text}</li>
            ))}
          </ul>
          <button type="button" disabled={isBusy} onClick={() => handleFinalize(true)}>
            확인했어요, 그대로 확정
          </button>
        </div>
      )}

      <div style={{ marginTop: 24, display: "flex", gap: 8, flexWrap: "wrap" }}>
        {document.status !== "FINAL" ? (
          <button type="button" disabled={isBusy} onClick={() => handleFinalize()}>
            최종 확정
          </button>
        ) : (
          <button type="button" onClick={handleExport}>
            텍스트로 내보내기
          </button>
        )}
        {paragraphs.length > 0 && (
          <button type="button" disabled={isStartingJobSearch} onClick={handleStartJobSearch}>
            {isStartingJobSearch ? "시작하는 중..." : "이 결과로 취업 정보 검색 시작"}
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
