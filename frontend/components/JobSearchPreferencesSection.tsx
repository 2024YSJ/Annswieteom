"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { jobSearchApi, type JobPreferencesConfirmInput, type JobPreferencesRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";
import type { ComposerEvent } from "@/components/ChatComposer";

const QUESTION_TEXT =
  "어떤 조건의 일자리를 찾고 계신가요? 희망 급여, 근무지, 학력/경력, 선호하는 업무 스타일을 자유롭게 말씀해주세요.";

type Draft = JobPreferencesConfirmInput;

const EMPTY_DRAFT: Draft = {
  salary_min: null,
  salary_max: null,
  location: null,
  education_level: null,
  career_years: null,
  work_style_tags: [],
};

/** 새로 들어온 값(추출 제안이든 연동 시드든)을 기존 초안 위에 얹는다 — 이번
 * 턴에 언급 안 된 필드(null/undefined)는 기존 값을 그대로 유지해서, 사용자가
 * 여러 턴에 걸쳐 조건을 나눠 말해도 앞서 준 값이 지워지지 않게 한다.
 * work_style_tags는 교체가 아니라 중복 없이 추가한다. */
function mergeDraft(prev: Draft, incoming: Partial<Draft>): Draft {
  return {
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
  if (preferences.salary_min != null || preferences.salary_max != null) {
    lines.push(`희망 급여: ${preferences.salary_min ?? "?"} ~ ${preferences.salary_max ?? "?"}`);
  }
  if (preferences.location) lines.push(`희망 근무지: ${preferences.location}`);
  if (preferences.education_level) lines.push(`학력: ${preferences.education_level}`);
  if (preferences.career_years != null) lines.push(`경력: ${preferences.career_years}년`);
  if (preferences.work_style_tags.length > 0) lines.push(`선호 스타일: ${preferences.work_style_tags.join(", ")}`);
  return lines;
}

export function JobSearchPreferencesSection({
  sessionId,
  accessToken,
  mode,
  linkedGapSessionId,
  preferences,
  composerEvent,
}: {
  sessionId: string;
  accessToken: string;
  mode: "completed" | "active";
  linkedGapSessionId: string | null;
  preferences: JobPreferencesRead | null;
  composerEvent: ComposerEvent | null;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => (preferences ? toDraft(preferences) : EMPTY_DRAFT));
  const [newTag, setNewTag] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const answeredNonceRef = useRef<number | null>(null);
  const seedFiredRef = useRef(false);
  // 확정(mode="completed")된 뒤에도 사용자가 이 값을 다시 대화로 고칠 수 있게
  // 하는 로컬 재편집 상태 — mode prop 자체는 "한 번이라도 확정됐는가"만
  // 나타내고 더 이상 바뀌지 않으므로(JOB_PREFERENCES_INPUT을 벗어나면 세션
  // 상태가 되돌아가지 않음), "지금 폼을 보여줄지"는 이 상태가 따로 결정한다.
  const [isReopened, setIsReopened] = useState(false);
  const showForm = mode === "active" || isReopened;

  // 연동된 공백기 세션이 있으면 처음 진입 시 자동으로 시드 제안을 받아 태그를
  // 미리 채운다 — 급여/근무지는 seed 응답 자체에 없으므로(STAR 사실만으로는
  // 유추 불가) 항상 사용자가 직접 채운다.
  useEffect(() => {
    if (!showForm || !linkedGapSessionId || seedFiredRef.current) return;
    seedFiredRef.current = true;
    async function run() {
      try {
        const seed = await jobSearchApi.seedFromGap(sessionId, accessToken);
        setDraft((prev) => mergeDraft(prev, { work_style_tags: seed.work_style_tags }));
      } catch {
        // 연동 실패는 조용히 무시 — 사용자는 여전히 직접 입력할 수 있다.
      }
    }
    run();
  }, [showForm, linkedGapSessionId, sessionId, accessToken]);

  useEffect(() => {
    if (!composerEvent || composerEvent.kind !== "text" || composerEvent.forStep !== "job_preferences") return;
    if (answeredNonceRef.current === composerEvent.nonce) return;
    answeredNonceRef.current = composerEvent.nonce;

    // 완료 요약만 보이던 중에 새 메시지가 오면, 그 자체가 "다시 고치겠다"는
    // 의사표시다 — 폼을 다시 연다(이미 열려 있었으면 기존 draft 위에 얹기만).
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

  function updateTag(index: number, value: string) {
    setDraft((prev) => ({ ...prev, work_style_tags: prev.work_style_tags.map((t, i) => (i === index ? value : t)) }));
  }

  function removeTag(index: number) {
    setDraft((prev) => ({ ...prev, work_style_tags: prev.work_style_tags.filter((_, i) => i !== index) }));
  }

  function addTag() {
    const trimmed = newTag.trim();
    if (!trimmed) return;
    setDraft((prev) => ({ ...prev, work_style_tags: [...prev.work_style_tags, trimmed] }));
    setNewTag("");
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

  if (!showForm) {
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
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {draft.work_style_tags.map((tag, i) => (
                <div
                  key={i}
                  style={{ display: "flex", alignItems: "center", gap: 4, background: "var(--hover-surface)", padding: "4px 8px", borderRadius: 999 }}
                >
                  <input
                    value={tag}
                    onChange={(e) => updateTag(i, e.target.value)}
                    aria-label="업무 스타일 태그"
                    style={{ border: "none", background: "transparent", width: `${Math.max(tag.length, 3)}ch`, fontSize: 13 }}
                  />
                  <button type="button" onClick={() => removeTag(i)} aria-label="태그 삭제" title="삭제" style={{ fontSize: 11 }}>
                    ✕
                  </button>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <input
                type="text"
                value={newTag}
                placeholder="새 태그"
                onChange={(e) => setNewTag(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addTag();
                  }
                }}
                style={{ fontSize: 13 }}
              />
              <button type="button" onClick={addTag} style={{ fontSize: 13 }}>
                + 태그 추가
              </button>
            </div>
          </div>
          {error && <p style={{ color: "crimson", fontSize: 13 }}>{error}</p>}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={handleConfirm} disabled={isSubmitting} style={{ alignSelf: "flex-start" }}>
              {isSubmitting ? "저장 중..." : "확인"}
            </button>
            {/* mode==="completed"일 때만(=이미 한 번 확정된 값을 다시 여는
             * 경우만) 보여준다 — 최초 1회차는 아직 확정된 값 자체가 없어
             * "취소"가 되돌아갈 곳이 없다. */}
            {mode === "completed" && (
              <button type="button" onClick={handleCancelReopen} disabled={isSubmitting} style={{ alignSelf: "flex-start" }}>
                취소
              </button>
            )}
          </div>
        </div>
      </ChatBubble>
    </>
  );
}
