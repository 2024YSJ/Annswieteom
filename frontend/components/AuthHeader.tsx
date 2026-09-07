"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export function AuthHeader() {
  const router = useRouter();
  const { user, isLoading, logout } = useAuth();

  async function handleLogout() {
    await logout();
    // logout() only clears auth state — without this, staying on whatever
    // page you were on (e.g. a session's chat screen) left a signed-out
    // visitor stranded on a stale authenticated view instead of returning
    // to the start screen.
    router.push("/");
  }

  return (
    <header
      style={{
        // sticky (not fixed) so it stays in normal document flow — every
        // page's content naturally starts below it instead of needing its
        // own top-padding to avoid being covered (it was `fixed` with no
        // width/background before, so it just floated over whatever content
        // happened to be underneath at scroll position 0, text overlapping
        // text — reported as "메뉴바 형태로 나타나지 않아 글자가 겹침", 2026-09-06).
        position: "sticky",
        top: 0,
        left: 0,
        right: 0,
        width: "100%",
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        fontSize: 14,
        background: "var(--background)",
        borderBottom: "1px solid var(--border)",
        zIndex: 10,
        boxSizing: "border-box",
      }}
    >
      {isLoading ? null : user ? (
        <>
          <span>{user.nickname}님</span>
          {user.is_guest && <Link href="/register">회원가입하고 저장하기</Link>}
          <button type="button" onClick={handleLogout}>
            로그아웃
          </button>
        </>
      ) : (
        <>
          <Link href="/login">로그인</Link>
          <Link href="/register">회원가입</Link>
        </>
      )}
    </header>
  );
}
