"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { sessionApi, type SessionKind } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { useSessionsList } from "@/lib/use-sessions-list";
import { LoadingNotice } from "@/components/LoadingNotice";

export default function Home() {
  const router = useRouter();
  const { user, accessToken, isLoading, guestLogin } = useAuth();
  const { data: sessions, isLoading: sessionsLoading, error: sessionsError, refetch: refetchSessions } = useSessionsList();
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  // Guards against firing the redirect twice (React 19 dev-mode double-invoked
  // effects).
  const hasRedirectedRef = useRef(false);

  useEffect(() => {
    // Only resumes an existing session — creating a brand-new one now always
    // goes through the explicit 공백기 채우기/일자리 찾기 choice below instead
    // of silently defaulting to gap-fill, so a user with zero sessions falls
    // through to the chooser render branch rather than being redirected here.
    if (isLoading || !user || sessionsLoading || !sessions || sessions.length === 0 || hasRedirectedRef.current) return;
    hasRedirectedRef.current = true;
    // Sessions come back newest-first (backend orders by created_at desc) —
    // landing here should resume the most recent one, matching the sidebar's
    // own ordering.
    router.replace(`/sessions/${sessions[0].id}`);
  }, [isLoading, user, sessionsLoading, sessions, router]);

  async function handleGuestStart() {
    setError(null);
    setIsCreating(true);
    try {
      // Only sign in here — picking a flow (and creating the first session)
      // is left entirely to the chooser buttons below, once `user` is set
      // and the render logic shows them. Previously this also auto-created a
      // session, racing the redirect effect for the very same brand-new
      // guest and sometimes creating two sessions instead of one (production
      // bug, 2026-09-05) — removing the auto-create here (and from the
      // effect above) eliminates that race entirely rather than just guarding it.
      await guestLogin();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsCreating(false);
    }
  }

  async function startFlow(kind: SessionKind) {
    setError(null);
    setIsCreating(true);
    try {
      const session = await sessionApi.create(accessToken!, { kind });
      router.replace(`/sessions/${session.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsCreating(false);
    }
  }

  // A logged-in visitor whose session list failed to load (not just still
  // loading) used to fall through to the loading branch below forever — the
  // redirect effect above only ever checks `!sessions`, never the query's
  // error state, so nothing there could break the wait. Handle it explicitly
  // with a retry instead of leaving a dead end with no escape.
  const mainStyle = {
    maxWidth: 480,
    margin: "120px auto",
    padding: "0 16px",
    textAlign: "center" as const,
    display: "flex",
    flexDirection: "column" as const,
    gap: 16,
  };

  if (user && sessionsError) {
    return (
      <main style={mainStyle}>
        <h1>안 쉬었음</h1>
        <p style={{ color: "crimson" }}>{errorMessage(sessionsError)}</p>
        <button type="button" onClick={() => refetchSessions()} style={{ alignSelf: "center" }}>
          다시 시도
        </button>
      </main>
    );
  }

  // 로그인/게스트 로그인 상태고 세션 목록도 다 불러왔는데 세션이 하나도
  // 없으면 — 새 사용자든, 딱 게스트 로그인만 막 한 사람이든 — 여기서
  // 공백기 채우기/일자리 찾기 중 뭘로 시작할지 직접 고르게 한다. 그 외
  // (아직 로딩 중이거나, 이미 세션이 있어 위 effect가 리다이렉트를
  // 처리하는 중)에는 계속 로딩 화면만 보여준다.
  if (user && !sessionsLoading && sessions && sessions.length === 0) {
    return (
      <main style={mainStyle}>
        <h1>안 쉬었음</h1>
        <p>무엇부터 시작할까요?</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <button type="button" onClick={() => startFlow("gap_fill")} disabled={isCreating}>
            {isCreating ? "시작하는 중..." : "공백기 채우기"}
          </button>
          <p style={{ fontSize: 13, color: "var(--muted-text)", margin: 0 }}>
            공백기 활동을 인터뷰로 정리해 근거 있는 STAR 경력기술서를 만들어요.
          </p>
          <button type="button" onClick={() => startFlow("job_search")} disabled={isCreating}>
            {isCreating ? "시작하는 중..." : "일자리 찾기"}
          </button>
          <p style={{ fontSize: 13, color: "var(--muted-text)", margin: 0 }}>
            희망 조건을 알려주시면 채용정보를 찾아 적합도까지 판단해드려요.
          </p>
        </div>
        {error && <p style={{ color: "crimson" }}>{error}</p>}
      </main>
    );
  }

  if (isLoading || user) {
    return (
      <main style={mainStyle}>
        <h1>안 쉬었음</h1>
        <LoadingNotice />
        {error && <p style={{ color: "crimson" }}>{error}</p>}
      </main>
    );
  }

  return (
    <main style={mainStyle}>
      <h1>안 쉬었음</h1>
      <p style={{ fontWeight: 700, fontSize: 18 }}>우리는 쉬지 않았습니다.</p>
      <p>커리어 공백기를 근거 있는 STAR 내러티브로 정리해드려요.</p>

      <p>
        <Link href="/login">로그인</Link> 또는 <Link href="/register">회원가입</Link>으로 시작하세요.
      </p>
      <button type="button" onClick={handleGuestStart} disabled={isCreating} style={{ alignSelf: "center" }}>
        {isCreating ? "시작하는 중..." : "게스트로 시작하기 (1회 체험)"}
      </button>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
    </main>
  );
}
