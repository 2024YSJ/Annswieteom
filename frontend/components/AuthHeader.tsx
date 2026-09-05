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
        position: "fixed",
        top: 0,
        left: 0,
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        fontSize: 14,
        zIndex: 10,
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
