"use client";

import { useEffect, useRef, useState } from "react";
import { jobSearchApi, type JobInfoCategoryResultRead, type JobInfoResultRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { useAuth } from "@/lib/auth-context";
import { ChatBubble } from "@/components/ChatBubble";
import { ChatComposer, type ComposerEvent } from "@/components/ChatComposer";

interface Turn {
  query: string;
  categories: JobInfoCategoryResultRead[];
  clarificationQuestion: string | null;
}

/** kind="job_search" 세션 전용 — 취업 정보 종합 검색(devlog 16). 이전
 * 버전(급여/지역/학력/경력을 모아뒀다가 워크넷 구인정보 API 하나로 검색)은
 * 그 핵심 API가 개인회원 계정을 차단해서 못 쓴다는 게 확인돼(devlog 15)
 * 걷어냈다 — 대신 개인회원으로도 되는 워크넷/고용24의 다른 9개 API(채용행사/
 * 공채속보/공채기업정보/직업훈련과정 4종/구직자취업역량강화프로그램/강소기업)
 * 를 자유 텍스트 질문 하나로 넘나드는 대화형 검색으로 바꿨다.
 *
 * 서버에 아무것도 저장하지 않는 무상태 대화라(백엔드가 매 질문마다 그 자리에서
 * 바로 분류+검색해서 응답) 대화 이력은 이 컴포넌트의 로컬 상태로만 누적된다 —
 * 새로고침하면 사라진다(기존 인터뷰 컴포넌트들의 로컬 확인 이력과 같은
 * 트레이드오프). */
export function JobSearchChatPage({ sessionId }: { sessionId: string }) {
  const { accessToken } = useAuth();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length]);

  async function handleSend(event: ComposerEvent) {
    if (event.kind !== "text") return;
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await jobSearchApi.query(sessionId, event.value, accessToken!);
      setTurns((prev) => [
        ...prev,
        { query: event.value, categories: result.categories, clarificationQuestion: result.clarification_question },
      ]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div style={{ height: "100dvh", display: "flex", flexDirection: "column" }}>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <main style={{ maxWidth: 640, margin: "80px auto 24px", padding: "0 16px", display: "flex", flexDirection: "column", gap: 24 }}>
          {turns.length === 0 && (
            <ChatBubble side="left">
              어떤 취업 정보를 찾아드릴까요? 채용행사, 최근 공채 소식, 채용 기업 정보, 직업훈련과정, 취업 지원 프로그램,
              강소기업에 대해 자유롭게 물어보세요.
            </ChatBubble>
          )}

          {turns.map((turn, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <ChatBubble side="right">{turn.query}</ChatBubble>

              {turn.clarificationQuestion ? (
                <ChatBubble side="left">{turn.clarificationQuestion}</ChatBubble>
              ) : (
                turn.categories.map((category) => (
                  <div key={category.category} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--muted-text)" }}>{category.category_label}</div>
                    {category.results.length === 0 ? (
                      <ChatBubble side="left">조건에 맞는 {category.category_label} 정보를 찾지 못했어요.</ChatBubble>
                    ) : (
                      <ChatBubble side="left" variant="card">
                        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                          {category.results.map((r, ri) => (
                            <JobInfoResultCard key={ri} result={r} />
                          ))}
                        </div>
                      </ChatBubble>
                    )}
                  </div>
                ))
              )}
            </div>
          ))}

          {error && <p style={{ color: "crimson", fontSize: 13 }}>{error}</p>}

          <div ref={bottomRef} />
        </main>
      </div>

      <div style={{ flexShrink: 0, borderTop: "1px solid var(--border)", background: "var(--background)", padding: "12px 16px" }}>
        <div style={{ maxWidth: 640, margin: "0 auto" }}>
          <ChatComposer activeStep="job_preferences" onSend={handleSend} disabled={isSubmitting} />
        </div>
      </div>
    </div>
  );
}

function JobInfoResultCard({ result }: { result: JobInfoResultRead }) {
  return (
    <div style={{ borderBottom: "1px solid var(--border)", paddingBottom: 12 }}>
      <div style={{ fontWeight: 600 }}>{result.title}</div>
      {result.subtitle && <div style={{ fontSize: 13, color: "var(--muted-text)" }}>{result.subtitle}</div>}
      {result.meta_lines.map((line, i) => (
        <div key={i} style={{ fontSize: 13, color: "var(--muted-text)" }}>
          {line}
        </div>
      ))}
      {result.detail_url && (
        <a href={result.detail_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 13 }}>
          자세히 보기
        </a>
      )}
    </div>
  );
}
