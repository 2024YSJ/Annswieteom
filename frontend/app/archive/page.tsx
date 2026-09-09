"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { profileApi, type ArchivedAnswer } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/lib/auth-context";
import { LoadingNotice } from "@/components/LoadingNotice";

/** 계정에 쌓인 문답 기록.
 *
 * 왜 이 화면이 있는가: 인터뷰에서 사용자가 실제로 타이핑한 답변 원문은 2026-09-09
 * 전까지 어디에도 저장되지 않았다 — 요약된 사실 문장만 confirmed_facts에 남고
 * 원문은 사라졌으며, 그 사실마저 세션을 지우면 함께 사라졌다. 이제 문답은
 * 계정에 남는다. 남는 이상 열람과 삭제 수단도 같이 있어야 한다.
 */
function AnswerCard({
  answer,
  onDelete,
  busy,
}: {
  answer: ArchivedAnswer;
  onDelete: () => void;
  busy: boolean;
}) {
  return (
    <li className="card" style={{ padding: 18, listStyle: "none" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap", marginBottom: 8 }}>
        <strong>{answer.category_label}</strong>
        <span style={{ fontSize: 12, color: "var(--muted-text)" }}>
          {new Date(answer.created_at).toLocaleDateString("ko-KR")}
        </span>
        {answer.session_id === null && (
          <span style={{ fontSize: 12, color: "var(--muted-text)" }}>· 삭제된 세션</span>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            if (window.confirm("이 문답 기록을 지울까요? 되돌릴 수 없습니다.")) onDelete();
          }}
          className="btn-ghost"
          style={{ marginLeft: "auto", fontSize: 12, color: "var(--danger)" }}
        >
          삭제
        </button>
      </div>

      <p style={{ margin: "0 0 4px", fontSize: 13, color: "var(--muted-text)" }}>Q. {answer.question_text}</p>
      <p style={{ margin: "0 0 8px", whiteSpace: "pre-wrap" }}>{answer.answer_text}</p>

      {answer.confirmed_facts.length > 0 ? (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "var(--body-text)" }}>
          {answer.confirmed_facts.map((fact, index) => (
            <li key={index}>{fact.content}</li>
          ))}
        </ul>
      ) : (
        <p style={{ margin: 0, fontSize: 12, color: "var(--muted-text)" }}>확정된 사실 없음 (확인 단계 전에 그만둔 답변)</p>
      )}
    </li>
  );
}

export default function ArchivePage() {
  const { accessToken, user, isLoading: authLoading } = useAuth();
  const queryClient = useQueryClient();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const enabled = !authLoading && !!accessToken && user?.is_guest === false;

  const { data: answers, isLoading, error: loadError } = useQuery({
    queryKey: queryKeys.archive(),
    queryFn: () => profileApi.listAnswers(accessToken!),
    enabled,
    retry: false,
  });

  const { data: summary } = useQuery({
    queryKey: [...queryKeys.archive(), "summary"],
    queryFn: () => profileApi.summary(accessToken!),
    enabled,
    retry: false,
  });

  async function handleDelete(answerId: string) {
    setError(null);
    setDeletingId(answerId);
    try {
      await profileApi.deleteAnswer(answerId, accessToken!);
      await queryClient.invalidateQueries({ queryKey: queryKeys.archive() });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDeletingId(null);
    }
  }

  if (authLoading) {
    return (
      <main style={PAGE_STYLE}>
        <LoadingNotice />
      </main>
    );
  }

  if (!user) {
    return (
      <main style={PAGE_STYLE}>
        <h1>내 문답 기록</h1>
        <p style={{ color: "var(--body-text)" }}>
          로그인하면 지금까지의 문답 기록을 볼 수 있어요. <Link href="/login">로그인하기</Link>
        </p>
      </main>
    );
  }

  if (user.is_guest) {
    return (
      <main style={PAGE_STYLE}>
        <h1>내 문답 기록</h1>
        <p style={{ color: "var(--body-text)" }}>
          문답 기록은 이메일로 회원가입한 계정에 쌓여요. 지금 가입하면 비회원으로 남긴 답변도
          그대로 이어집니다. <Link href="/register">회원가입하기</Link>
        </p>
      </main>
    );
  }

  return (
    <main style={PAGE_STYLE}>
      <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1>내 문답 기록</h1>
        <p style={{ color: "var(--body-text)" }}>
          인터뷰에서 직접 쓴 답변이 계정에 남아 있어요. 세션을 지워도 이 기록은 남습니다.
        </p>
        {summary && (
          <p style={{ fontSize: 13, color: "var(--muted-text)" }}>
            문답 {summary.total_answers}개 · 확정된 사실 {summary.total_confirmed_facts}개
          </p>
        )}
      </header>

      {error && <p className="msg-error" style={{ marginTop: 12 }}>{error}</p>}
      {loadError && <p className="msg-error" style={{ marginTop: 12 }}>{errorMessage(loadError)}</p>}

      {isLoading ? (
        <LoadingNotice />
      ) : answers && answers.length > 0 ? (
        <ul style={{ margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 12 }}>
          {answers.map((answer) => (
            <AnswerCard
              key={answer.id}
              answer={answer}
              busy={deletingId !== null}
              onDelete={() => handleDelete(answer.id)}
            />
          ))}
        </ul>
      ) : (
        !loadError && (
          <p className="feed-callout">아직 기록된 문답이 없어요. 공백기 채우기를 진행하면 여기에 쌓입니다.</p>
        )
      )}
    </main>
  );
}

const PAGE_STYLE = {
  flex: 1,
  width: "100%",
  maxWidth: 720,
  margin: "48px auto 96px",
  padding: "0 16px",
  display: "flex",
  flexDirection: "column" as const,
  gap: 20,
};
