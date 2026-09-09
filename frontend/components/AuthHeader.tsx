"use client";

import Image from "next/image";
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

  // 스타일은 전부 globals.css의 .topbar-* 클래스에 있다 — 좁은 화면에서
  // 닉네임을 숨기고 버튼 라벨을 줄이는 등 미디어 쿼리가 필요해서, 인라인
  // 스타일로는 표현할 수 없다.
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="topbar-brand" aria-label="안 쉬었음 홈">
          <Image src="/logo.png" alt="" width={26} height={26} priority />
          <span className="topbar-brand-name">안 쉬었음</span>
        </Link>

        <nav className="topbar-nav">
          {isLoading ? null : user ? (
            <>
              <span className="topbar-user">{user.nickname}님</span>
              {user.is_guest && (
                <Link href="/register" className="btn-primary topbar-btn">
                  {/* 좁은 화면에서는 "회원가입"만 남긴다 */}
                  <span className="wide-only">회원가입하고 저장하기</span>
                  <span className="narrow-only">회원가입</span>
                </Link>
              )}
              <button type="button" className="btn-ghost topbar-btn" onClick={handleLogout}>
                로그아웃
              </button>
            </>
          ) : (
            <>
              <Link href="/login" className="btn-ghost topbar-btn">
                로그인
              </Link>
              <Link href="/register" className="btn-primary topbar-btn">
                시작하기
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
