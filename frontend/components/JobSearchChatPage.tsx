"use client";

import { useEffect, useRef, useState } from "react";
import { jobSearchApi, type JobInfoCategoryResultRead, type JobInfoResultRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { useAuth } from "@/lib/auth-context";
import { ChatBubble } from "@/components/ChatBubble";
import { ChatComposer, type ComposerEvent } from "@/components/ChatComposer";
import { LoadingNotice } from "@/components/LoadingNotice";

interface Turn {
  query: string;
  categories: JobInfoCategoryResultRead[];
  clarificationQuestion: string | null;
  skippedCategoryLabels: string[];
}

/** kind="job_search" 세션 전용 — 취업 정보 종합 검색(devlog 16). 이전
 * 버전(급여/지역/학력/경력을 모아뒀다가 고용24 구인정보 API 하나로 검색)은
 * 그 핵심 API가 개인회원 계정을 차단해서 못 쓴다는 게 확인돼(devlog 15)
 * 걷어냈다 — 대신 개인회원으로도 되는 고용24의 다른 9개 API(채용행사/
 * 공채속보/공채기업정보/직업훈련과정 4종/구직자취업역량강화프로그램/강소기업)
 * 를 자유 텍스트 질문 하나로 넘나드는 대화형 검색으로 바꿨다.
 *
 * 서버에 아무것도 저장하지 않는 무상태 대화라(백엔드가 매 질문마다 그 자리에서
 * 바로 분류+검색해서 응답) 대화 이력은 이 컴포넌트의 로컬 상태로만 누적된다 —
 * 새로고침하면 사라진다(기존 인터뷰 컴포넌트들의 로컬 확인 이력과 같은
 * 트레이드오프).
 *
 * 사이드바 "..." 메뉴의 "취업 정보 검색으로 이관"으로 공백기 채우기 세션에서
 * 만들어진 경우(linkedGapSessionId 있음) 그 세션의 확정된 사실을 요약한 첫
 * 질문 초안을 컴포저에 미리 채워준다(devlog 17). */
export function JobSearchChatPage({
  sessionId,
  linkedGapSessionId,
}: {
  sessionId: string;
  linkedGapSessionId: string | null;
}) {
  const { accessToken } = useAuth();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // 사이드바 "취업 정보 검색으로 이관"으로 막 만들어진 세션이면(linkedGapSessionId
  // 있음) 컴포저에 미리 채울 첫 질문 초안을 한 번 받아온다 — AI가 쓰고
  // 사용자가 확인/수정/그대로 전송하는, 이 앱 전반의 "AI 초안" 원칙 그대로다.
  const [prefillText, setPrefillText] = useState<string | null>(null);
  // 실패한 질문을 붙잡아 둔다 — 시간 초과가 나면 사용자가 질문을 처음부터
  // 다시 타이핑하는 게 아니라 그대로 재시도할 수 있어야 한다.
  const [failedQuery, setFailedQuery] = useState<string | null>(null);
  const hasFetchedDraftRef = useRef(false);
  // 로컬 LLM 분류 호출이 수십 초씩 걸릴 수 있는데(이 프로젝트에서 반복 확인된
  // 제약) 그동안 화면에 아무 표시가 없으면 "사이트가 멈췄다"처럼 보인다 —
  // 방금 보낸 질문을 즉시 오른쪽 말풍선으로 보여주고 그 아래에 로딩 표시를
  // 붙여서, 응답이 오기 전까지도 뭔가 진행 중이라는 걸 알 수 있게 한다.
  const [pendingQuery, setPendingQuery] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, pendingQuery]);

  useEffect(() => {
    if (!linkedGapSessionId || hasFetchedDraftRef.current || !accessToken) return;
    hasFetchedDraftRef.current = true;
    jobSearchApi
      .draftQueryFromGap(sessionId, accessToken)
      .then((res) => {
        if (res.draft_query) setPrefillText(res.draft_query);
      })
      // 실패해도 조용히 넘어간다 — 어차피 사용자가 직접 질문을 타이핑하면
      // 되는, 있으면 편한 정도의 부가 기능이라 에러를 따로 띄우지 않는다.
      .catch(() => {});
  }, [linkedGapSessionId, sessionId, accessToken]);

  async function runQuery(queryText: string) {
    setError(null);
    setPrefillText(null);
    setPendingQuery(queryText);
    setIsSubmitting(true);
    try {
      const result = await jobSearchApi.query(sessionId, queryText, accessToken!);
      setTurns((prev) => [
        ...prev,
        {
          query: queryText,
          categories: result.categories,
          clarificationQuestion: result.clarification_question,
          skippedCategoryLabels: result.skipped_category_labels ?? [],
        },
      ]);
    } catch (err) {
      setError(errorMessage(err));
      setFailedQuery(queryText); // 재시도 버튼이 같은 질문을 다시 보낼 수 있게
    } finally {
      setIsSubmitting(false);
      setPendingQuery(null);
    }
  }

  async function handleSend(event: ComposerEvent) {
    if (event.kind !== "text") return;
    setFailedQuery(null);
    await runQuery(event.value);
  }

  return (
    // 헤더 높이만큼 뺀 높이 — 세션 대화 화면(app/sessions/[id]/page.tsx)과 동일.
    <div style={{ height: "calc(100dvh - var(--header-height))", display: "flex", flexDirection: "column" }}>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <main style={{ maxWidth: 640, margin: "32px auto 24px", padding: "0 16px", display: "flex", flexDirection: "column", gap: 24 }}>
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
                <>
                  {turn.categories.map((category) => (
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
                  ))}

                  {/* 카테고리가 하나도 안 남으면 예전엔 사용자 말풍선만 남고
                      AI 쪽에는 아무것도 안 그려졌다 — 한 턴에 최소 한 개의
                      응답 말풍선은 반드시 나와야 한다(devlog 20). */}
                  {turn.categories.length === 0 && turn.skippedCategoryLabels.length === 0 && (
                    <ChatBubble side="left">
                      조건에 맞는 정보를 찾지 못했어요. 지역이나 직무를 조금 더 구체적으로 적어서 다시 물어봐 주세요.
                    </ChatBubble>
                  )}

                  {turn.skippedCategoryLabels.length > 0 && (
                    <ChatBubble side="left">
                      {turn.skippedCategoryLabels.join(", ")} 정보는 이번에 가져오지 못했어요. 다시 물어보시면 재시도합니다.
                    </ChatBubble>
                  )}
                </>
              )}
            </div>
          ))}

          {pendingQuery && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <ChatBubble side="right">{pendingQuery}</ChatBubble>
              <ChatBubble side="left">
                <LoadingNotice label="관련 정보를 찾고 있어요..." />
              </ChatBubble>
            </div>
          )}

          {error && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              {/* 색은 디자인 시스템 토큰을 쓴다(하드코딩 crimson 아님) — 재시도 버튼은
                  일자리 찾기 쪽에서 추가한 것으로, 조회가 실패했을 때 사용자가 질문을
                  다시 타이핑하지 않아도 되게 한다. */}
              <p style={{ color: "var(--danger)", fontSize: 13, margin: 0 }}>{error}</p>
              {failedQuery && (
                <button type="button" onClick={() => runQuery(failedQuery)} disabled={isSubmitting} style={{ fontSize: 12 }}>
                  다시 시도
                </button>
              )}
            </div>
          )}

          <div ref={bottomRef} />
        </main>
      </div>

      <div style={{ flexShrink: 0, borderTop: "1px solid var(--border)", background: "var(--background)", padding: "12px 16px" }}>
        <div style={{ maxWidth: 640, margin: "0 auto" }}>
          <ChatComposer activeStep="job_preferences" onSend={handleSend} disabled={isSubmitting} prefillText={prefillText} />
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
