"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { queryKeys } from "@/lib/query-keys";

export function AuthHeader() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, isLoading, logout } = useAuth();

  async function handleLogout() {
    await logout();
    // queryKeys.sessions()는 사용자별이 아니라 전역 키다 — 지우지 않으면 로그아웃
    // 후에도 이전 사용자의 세션 목록이 캐시에 남아, 랜딩이 "OO님, 이어서
    // 해볼까요?"와 남의 "이어서 하기" 카드를 계속 보여준다(2026-09-12 검증 발견).
    queryClient.removeQueries({ queryKey: queryKeys.sessions() });
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
              {/* 게스트에게는 숨긴다 — 이메일 계정 전용이라 눌러봐야
               * "회원가입하세요" 안내밖에 나오지 않는다.
               * 이름이 "내 문답 기록"이었을 때는 맞춤 정보를 고치러 가는
               * 곳으로 읽히지 않았다(2026-09-10 피드백). 이 페이지가 이제
               * 희망사항 편집까지 겸하므로 이름을 바꿨다. */}
              {!user.is_guest && (
                <Link href="/archive" className="btn-ghost topbar-btn">
                  맞춤 정보
                </Link>
              )}
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
