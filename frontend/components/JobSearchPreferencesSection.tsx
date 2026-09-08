"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { jobSearchApi, type JobPreferencesConfirmInput, type JobPreferencesRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";
import { JobStyleTagEditor } from "@/components/JobStyleTagEditor";
import type { ComposerEvent } from "@/components/ChatComposer";

const QUESTION_TEXT =
  "어떤 조건의 일자리를 찾고 계신가요? 희망 급여, 근무지, 학력/경력, 선호하는 업무 스타일을 자유롭게 말씀해주세요.";

type Draft = JobPreferencesConfirmInput;

const EMPTY_DRAFT: Draft = {
  desired_keyword: null,
  salary_min: null,
  salary_max: null,
  location: null,
  education_level: null,
  career_years: null,
  work_style_tags: [],
};

/** 새로 들어온 값(추출 제안)을 기존 초안 위에 얹는다 — 이번 턴에 언급 안 된
 * 필드(null/undefined)는 기존 값을 그대로 유지해서, 사용자가 여러 턴에 걸쳐
 * 조건을 나눠 말해도 앞서 준 값이 지워지지 않게 한다. work_style_tags는
 * 교체가 아니라 중복 없이 추가한다. */
function mergeDraft(prev: Draft, incoming: Partial<Draft>): Draft {
  return {
    desired_keyword: incoming.desired_keyword ?? prev.desired_keyword,
    salary_min: incoming.salary_min ?? prev.salary_min,
    salary_max: incoming.salary_max ?? prev.salary_max,
    location: incoming.location ?? prev.location,
    education_level: incoming.education_level ?? prev.education_level,
    career_years: incoming.career_years ?? prev.career_years,
    work_style_tags: [
      ...prev.work_style_tags,
      ...(incoming.work_style_tags ?? []).filter((t) => !prev.work_style_tags.includes(t)),
    ],
  };
}

function toDraft(preferences: JobPreferencesRead): Draft {
  return {
    desired_keyword: preferences.desired_keyword,
    salary_min: preferences.salary_min,
    salary_max: preferences.salary_max,
    location: preferences.location,
    education_level: preferences.education_level,
    career_years: preferences.career_years,
    work_style_tags: [...preferences.work_style_tags],
  };
}

function summaryLine(preferences: JobPreferencesRead | null): string[] {
  if (!preferences) return [];
  const lines: string[] = [];
  if (preferences.desired_keyword) lines.push(`찾는 직무/분야: ${preferences.desired_keyword}`);
  if (preferences.salary_min != null || preferences.salary_max != null) {
    lines.push(`희망 급여: ${preferences.salary_min ?? "?"} ~ ${preferences.salary_max ?? "?"}`);
  }
  if (preferences.location) lines.push(`희망 근무지: ${preferences.location}`);
  if (preferences.education_level) lines.push(`학력: ${preferences.education_level}`);
  if (preferences.career_years != null) lines.push(`경력: ${preferences.career_years}년`);
  if (preferences.work_style_tags.length > 0) lines.push(`선호 스타일: ${preferences.work_style_tags.join(", ")}`);
  return lines;
}

/** 최초 1회차 입력(6개 질문을 하나씩 묻는 `JobSearchInterviewSection`)이 끝난
 * 뒤부터만 렌더링된다 — 그래서 이 컴포넌트는 "완료 요약 + 자유롭게 다시
 * 고치기" 역할만 맡는다(처음 입력은 더 이상 이 컴포넌트의 책임이 아니다). */
export function JobSearchPreferencesSection({
  sessionId,
  accessToken,
  preferences,
  composerEvent,
}: {
  sessionId: string;
  accessToken: string;
  preferences: JobPreferencesRead | null;
  composerEvent: ComposerEvent | null;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => (preferences ? toDraft(preferences) : EMPTY_DRAFT));
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // JobSearchInterviewSection이 끝나자마자 이 컴포넌트가 그 자리에 새로
  // 마운트되는데, 이때 부모의 composerEvent는 인터뷰 마지막 질문에 답할 때
  // 쓴 메시지가 그대로 남아있다(같은 상태를 공유). 초기값을 null로 두면 그
  // 이미 소비된 메시지를 "새 메시지"로 오인해 곧장 재편집 폼을 열어버리므로
  // (요약 화면이 안 보이는 버그), 마운트 시점의 nonce를 "이미 처리됨"으로
  // 시드해서 진짜 새 메시지만 반응하게 한다.
  const answeredNonceRef = useRef<number | null>(composerEvent?.nonce ?? null);
  // 완료 요약이 기본값이고, 사용자가 "조건 수정하기"를 누르거나 composer로
  // 새 메시지를 보내면 그 순간에만 폼을 다시 연다.
  const [isReopened, setIsReopened] = useState(false);

  useEffect(() => {
    if (!composerEvent || composerEvent.kind !== "text" || composerEvent.forStep !== "job_preferences") return;
    if (answeredNonceRef.current === composerEvent.nonce) return;
    answeredNonceRef.current = composerEvent.nonce;

    setIsReopened(true);
    setError(null);
    async function run() {
      try {
        const suggestion = await jobSearchApi.extractPreferences(sessionId, composerEvent!.value, accessToken);
        setDraft((prev) => mergeDraft(prev, suggestion));
      } catch (err) {
        setError(errorMessage(err));
      }
    }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerEvent?.nonce]);

  function handleReopen() {
    if (preferences) setDraft(toDraft(preferences));
    setIsReopened(true);
  }

  function handleCancelReopen() {
    setIsReopened(false);
  }

  async function handleConfirm() {
    setError(null);
    setIsSubmitting(true);
    try {
      await jobSearchApi.confirmPreferences(sessionId, draft, accessToken);
      await queryClient.invalidateQueries({ queryKey: queryKeys.jobSearch(sessionId) });
      setIsReopened(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!isReopened) {
    const lines = summaryLine(preferences);
    return (
      <>
        <ChatBubble side="left">{QUESTION_TEXT}</ChatBubble>
        <ChatBubble side="right">
          {lines.length > 0 ? lines.map((line) => <div key={line}>{line}</div>) : "조건 없음"}
        </ChatBubble>
        <button type="button" onClick={handleReopen} style={{ alignSelf: "flex-end", fontSize: 12 }}>
          조건 수정하기
        </button>
      </>
    );
  }

  return (
    <>
      <ChatBubble side="left">
        <span aria-live="polite">{QUESTION_TEXT}</span>
      </ChatBubble>
      <ChatBubble side="left" variant="card">
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            찾는 직무/분야
            <input
              type="text"
              value={draft.desired_keyword ?? ""}
              onChange={(e) => setDraft((p) => ({ ...p, desired_keyword: e.target.value || null }))}
            />
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <label style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
              희망 급여(최소, 만원)
              <input
                type="number"
                value={draft.salary_min ?? ""}
                onChange={(e) => setDraft((p) => ({ ...p, salary_min: e.target.value ? Number(e.target.value) : null }))}
              />
            </label>
            <label style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
              희망 급여(최대, 만원)
              <input
                type="number"
                value={draft.salary_max ?? ""}
                onChange={(e) => setDraft((p) => ({ ...p, salary_max: e.target.value ? Number(e.target.value) : null }))}
              />
            </label>
          </div>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            희망 근무지
            <input
              type="text"
              value={draft.location ?? ""}
              onChange={(e) => setDraft((p) => ({ ...p, location: e.target.value || null }))}
            />
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <label style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
              학력
              <input
                type="text"
                value={draft.education_level ?? ""}
                onChange={(e) => setDraft((p) => ({ ...p, education_level: e.target.value || null }))}
              />
            </label>
            <label style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
              경력(년)
              <input
                type="number"
                value={draft.career_years ?? ""}
                onChange={(e) => setDraft((p) => ({ ...p, career_years: e.target.value ? Number(e.target.value) : null }))}
              />
            </label>
          </div>
          <div>
            <div style={{ fontSize: 13, marginBottom: 4, color: "var(--muted-text)" }}>선호하는 업무 스타일</div>
            <JobStyleTagEditor
              tags={draft.work_style_tags}
              onChange={(work_style_tags) => setDraft((p) => ({ ...p, work_style_tags }))}
            />
          </div>
          {error && <p style={{ color: "crimson", fontSize: 13 }}>{error}</p>}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={handleConfirm} disabled={isSubmitting} style={{ alignSelf: "flex-start" }}>
              {isSubmitting ? "저장 중..." : "확인"}
            </button>
            <button type="button" onClick={handleCancelReopen} disabled={isSubmitting} style={{ alignSelf: "flex-start" }}>
              취소
            </button>
          </div>
        </div>
      </ChatBubble>
    </>
  );
}
