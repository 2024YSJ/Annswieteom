"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { sessionApi } from "@/lib/api-client";
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
  // effects) — this effect has a side effect (session creation) when the user
  // has none yet, same reasoning as InterviewSection's fetchedForRef.
  const hasRedirectedRef = useRef(false);

  useEffect(() => {
    if (isLoading || !user || sessionsLoading || !sessions || hasRedirectedRef.current) return;
    hasRedirectedRef.current = true;

    async function goToSession() {
      try {
        // Sessions come back newest-first (backend orders by created_at desc)
        // — landing here should resume the most recent one, matching the
        // sidebar's own ordering.
        const target = sessions![0] ?? (await sessionApi.create(accessToken!));
        router.replace(`/sessions/${target.id}`);
      } catch (err) {
        hasRedirectedRef.current = false;
        setError(errorMessage(err));
      }
    }
    goToSession();
  }, [isLoading, user, sessionsLoading, sessions, accessToken, router]);

  async function handleGuestStart() {
    setError(null);
    setIsCreating(true);
    try {
      // Only sign in here — creating the first session and navigating is
      // left entirely to the redirect effect above. It previously happened
      // in both places: `guestLogin()` sets `user`, which is exactly the
      // effect's own trigger, so the effect's "sessions is empty → create
      // one" logic and this handler's own sessionApi.create() call ran as
      // an uncoordinated race for the very same brand-new guest, sometimes
      // creating two sessions instead of one (production bug, 2026-09-05).
      // Once `user` is set below, the render logic immediately shows the
      // loading screen instead of this button, so there's no visible gap
      // before the effect's own redirect takes over.
      await guestLogin();
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
