"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  jobSearchApi,
  type JobPreferencesSuggestionRead,
  type JobSearchQuestionRead,
  type JobSearchTurnConfirmInput,
} from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";
import { JobStyleTagEditor } from "@/components/JobStyleTagEditor";
import type { ComposerEvent } from "@/components/ChatComposer";

/** 필드마다 값의 "모양"이 달라서(문자열 하나/숫자 하나/숫자 둘/태그 배열)
 * 하나의 후보 UI로 억지로 통일하지 않는다 — 대신 이 태그드 유니언으로
 * 필드별 위젯을 분기한다. */
type TurnValue =
  | { field: "keyword" | "location" | "education"; value: string }
  | { field: "salary"; min: number | null; max: number | null }
  | { field: "career"; value: number | null }
  | { field: "work_style"; tags: string[] };

function candidateFromSuggestion(field: string, s: JobPreferencesSuggestionRead): TurnValue {
  switch (field) {
    case "keyword":
      return { field, value: s.desired_keyword ?? "" };
    case "location":
      return { field, value: s.location ?? "" };
    case "education":
      return { field: "education", value: s.education_level ?? "" };
    case "salary":
      return { field: "salary", min: s.salary_min, max: s.salary_max };
    case "career":
      return { field: "career", value: s.career_years };
    default:
      return { field: "work_style", tags: s.work_style_tags };
  }
}

function emptyValue(field: string): TurnValue {
  switch (field) {
    case "keyword":
      return { field: "keyword", value: "" };
    case "location":
      return { field: "location", value: "" };
    case "education":
      return { field: "education", value: "" };
    case "salary":
      return { field: "salary", min: null, max: null };
    case "career":
      return { field: "career", value: null };
    default:
      return { field: "work_style", tags: [] };
  }
}

function toConfirmPayload(v: TurnValue): JobSearchTurnConfirmInput {
  switch (v.field) {
    case "keyword":
      return { desired_keyword: v.value.trim() || null };
    case "location":
      return { location: v.value.trim() || null };
    case "education":
      return { education_level: v.value.trim() || null };
    case "salary":
      return { salary_min: v.min, salary_max: v.max };
    case "career":
      return { career_years: v.value };
    case "work_style":
      return { work_style_tags: v.tags };
  }
}

function summarize(v: TurnValue): string {
  switch (v.field) {
    case "keyword":
    case "location":
    case "education":
      return v.value.trim() || "특별히 없음";
    case "salary":
      return v.min != null || v.max != null ? `${v.min ?? "?"} ~ ${v.max ?? "?"}` : "특별히 없음";
    case "career":
      return v.value != null ? `${v.value}년` : "특별히 없음";
    case "work_style":
      return v.tags.length > 0 ? v.tags.join(", ") : "특별히 없음";
  }
}

/** 자유 텍스트에서 이번 턴의 필드에 해당하는 값을 하나도 못 뽑은 경우 —
 * "특별히 없어요" 버튼으로 명시적으로 건너뛴 것과 구분해야 한다(그건 이미
 * 의도된 스킵). 이 경우는 사용자가 뭔가 답했는데 API가 쓸 수 있는 형태로
 * 못 알아들은 것이므로, 조용히 빈 값으로 넘기지 않고 예시를 보여주며
 * 다시 답해달라고 해야 워크넷 검색 파라미터가 무의미한 값으로 채워지지
 * 않는다. */
function isEmptyCandidate(v: TurnValue): boolean {
  switch (v.field) {
    case "keyword":
    case "location":
    case "education":
      return v.value.trim() === "";
    case "salary":
      return v.min == null && v.max == null;
    case "career":
      return v.value == null;
    case "work_style":
      return v.tags.length === 0;
  }
}

function exampleHint(field: string): string {
  switch (field) {
    case "keyword":
      return "답변에서 직무/분야를 이해하지 못했어요. \"백엔드 개발\", \"마케팅\", \"물류\"처럼 구체적으로 다시 말씀해주세요.";
    case "location":
      return "답변에서 근무지를 이해하지 못했어요. \"서울\", \"부산\", \"재택\"처럼 답하거나, 상관없으면 \"상관없음\"이라고 말씀해주세요.";
    case "salary":
      return "답변에서 급여 조건을 이해하지 못했어요. \"3000만원 이상\", \"3000에서 4000만원\"처럼 숫자를 포함해서 다시 말씀해주세요.";
    case "education":
      return "답변에서 학력 조건을 이해하지 못했어요. \"고졸 이상\", \"대졸\", \"학력무관\"처럼 다시 말씀해주세요.";
    case "career":
      return "답변에서 경력을 이해하지 못했어요. \"3년\", \"신입\"처럼 숫자로 다시 답해주세요.";
    default:
      return "답변에서 선호하는 업무 스타일을 이해하지 못했어요. \"재택 가능\", \"유연근무\", \"야근 없음\"처럼 다시 말씀해주세요.";
  }
}

interface AnsweredTurn {
  questionText: string;
  summaryText: string;
}

/** 최초 1회차 입력 전용 — 공백기 채우기 인터뷰와 같은 원리로 질문을 하나씩
 * 묻고, 답을 확인/수정한 뒤 다음 질문으로 넘어간다. 6개를 다 답하면
 * `JobSearchChatPage`가 이 컴포넌트 대신 `JobSearchPreferencesSection`(완료
 * 요약 + 자유 재편집)을 렌더링하도록 부모의 쿼리를 무효화해준다. */
export function JobSearchInterviewSection({
  sessionId,
  accessToken,
  composerEvent,
  onPrefillChange,
  onSubmittingChange,
}: {
  sessionId: string;
  accessToken: string;
  composerEvent: ComposerEvent | null;
  onPrefillChange: (text: string | null) => void;
  onSubmittingChange?: (isSubmitting: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState<JobSearchQuestionRead | null>(null);
  const [answered, setAnswered] = useState<AnsweredTurn[]>([]);
  const [turnValue, setTurnValue] = useState<TurnValue | null>(null);
  const [parseHint, setParseHint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmittingState] = useState(false);
  function setIsSubmitting(value: boolean) {
    setIsSubmittingState(value);
    onSubmittingChange?.(value);
  }
  const hasAskedRef = useRef(false);
  // JobSearchPreferencesSection과 같은 이유로 마운트 시점의 nonce를 이미
  // 처리된 것으로 시드한다 — 이 컴포넌트가 재마운트되는 경로는 지금 없지만
  // (JobSearchPreferencesSection에서 실제로 겪은 버그와 원인이 같으므로)
  // 방어적으로 맞춰둔다.
  const answeredNonceRef = useRef<number | null>(composerEvent?.nonce ?? null);

  async function fetchNextQuestion() {
    try {
      const q = await jobSearchApi.askPreferenceQuestion(sessionId, accessToken);
      setQuestion(q);
      setTurnValue(null);
      setParseHint(null);
      onPrefillChange(q.draft_answer || null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  useEffect(() => {
    if (hasAskedRef.current) return;
    hasAskedRef.current = true;
    fetchNextQuestion();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!composerEvent || composerEvent.kind !== "text" || composerEvent.forStep !== "job_preferences") return;
    if (!question || turnValue !== null) return; // 후보가 이미 나온 뒤엔 답변 입력을 더 안 받는다(gap-fill 인터뷰와 동일 원칙)
    if (answeredNonceRef.current === composerEvent.nonce) return;
    answeredNonceRef.current = composerEvent.nonce;

    onPrefillChange(null);
    setError(null);
    setIsSubmitting(true);
    async function run() {
      try {
        const suggestion = await jobSearchApi.extractPreferences(sessionId, composerEvent!.value, accessToken);
        const candidate = candidateFromSuggestion(question!.field!, suggestion);
        if (isEmptyCandidate(candidate)) {
          // 뭔가 답하긴 했는데 이번 필드에 쓸 값을 하나도 못 뽑았다 — "특별히
          // 없어요"로 명시적으로 건너뛴 것과 달리, 조용히 빈 값으로 넘어가면
          // 워크넷 검색 파라미터가 의미 없는 값으로 채워질 수 있으므로 후보
          // 카드로 넘어가지 않고 예시를 보여주며 다시 답해달라고 한다.
          setParseHint(exampleHint(question!.field!));
        } else {
          setParseHint(null);
          setTurnValue(candidate);
        }
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setIsSubmitting(false);
      }
    }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerEvent?.nonce]);

  function handleSkip() {
    if (!question?.field) return;
    setParseHint(null);
    setTurnValue(emptyValue(question.field));
  }

  async function handleNext() {
    if (!question?.field || !turnValue) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await jobSearchApi.confirmPreferenceTurn(sessionId, toConfirmPayload(turnValue), accessToken);
      setAnswered((prev) => [...prev, { questionText: question.question_text ?? "", summaryText: summarize(turnValue) }]);
      if (result.done) {
        // 부모가 completed_fields/status를 다시 읽어 JobSearchPreferencesSection으로
        // 전환하도록 상태 쿼리를 무효화한다.
        await queryClient.invalidateQueries({ queryKey: queryKeys.jobSearch(sessionId) });
        setQuestion(null);
        setTurnValue(null);
        onPrefillChange(null);
      } else {
        await fetchNextQuestion();
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {answered.map((a, i) => (
        <div key={i} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <ChatBubble side="left">{a.questionText}</ChatBubble>
          <ChatBubble side="right" label="확인됨">
            {a.summaryText}
          </ChatBubble>
        </div>
      ))}

      {question?.question_text && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }} aria-live="polite">
          <ChatBubble side="left">{question.question_text}</ChatBubble>

          {turnValue === null ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start" }}>
              {parseHint && (
                <ChatBubble side="left" variant="card">
                  <p style={{ margin: 0, fontSize: 13 }}>{parseHint}</p>
                </ChatBubble>
              )}
              {error && <p style={{ color: "crimson", fontSize: 13, margin: 0 }}>{error}</p>}
              <button type="button" onClick={handleSkip} disabled={isSubmitting} style={{ fontSize: 13 }}>
                특별히 없어요 / 건너뛰기
              </button>
            </div>
          ) : (
            <ChatBubble side="left" variant="card">
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {(turnValue.field === "keyword" || turnValue.field === "location" || turnValue.field === "education") && (
                  <input
                    type="text"
                    value={turnValue.value}
                    onChange={(e) => setTurnValue({ ...turnValue, value: e.target.value })}
                    aria-label="답변 수정"
                    style={{ width: "100%" }}
                  />
                )}
                {turnValue.field === "salary" && (
                  <div style={{ display: "flex", gap: 8 }}>
                    <label style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
                      최소(만원)
                      <input
                        type="number"
                        value={turnValue.min ?? ""}
                        onChange={(e) => setTurnValue({ ...turnValue, min: e.target.value ? Number(e.target.value) : null })}
                      />
                    </label>
                    <label style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
                      최대(만원)
                      <input
                        type="number"
                        value={turnValue.max ?? ""}
                        onChange={(e) => setTurnValue({ ...turnValue, max: e.target.value ? Number(e.target.value) : null })}
                      />
                    </label>
                  </div>
                )}
                {turnValue.field === "career" && (
                  <input
                    type="number"
                    value={turnValue.value ?? ""}
                    onChange={(e) => setTurnValue({ ...turnValue, value: e.target.value ? Number(e.target.value) : null })}
                    aria-label="답변 수정"
                  />
                )}
                {turnValue.field === "work_style" && (
                  <JobStyleTagEditor tags={turnValue.tags} onChange={(tags) => setTurnValue({ ...turnValue, tags })} />
                )}

                {error && <p style={{ color: "crimson", fontSize: 13 }}>{error}</p>}
                <button type="button" onClick={handleNext} disabled={isSubmitting} style={{ alignSelf: "flex-start" }}>
                  {isSubmitting ? "저장 중..." : "다음"}
                </button>
              </div>
            </ChatBubble>
          )}
        </div>
      )}

      {error && !question && <p style={{ color: "crimson", fontSize: 13 }}>{error}</p>}
    </div>
  );
}
