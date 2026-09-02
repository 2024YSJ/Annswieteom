"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { sessionApi } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";

export default function Home() {
  const router = useRouter();
  const { user, accessToken, isLoading, logout } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  async function handleStart() {
    setError(null);
    setIsCreating(true);
    try {
      const session = await sessionApi.create(accessToken!);
      router.push(`/sessions/${session.id}/period`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <main style={{ maxWidth: 480, margin: "120px auto", padding: "0 16px", textAlign: "center" }}>
      <h1>안 쉬었음</h1>
      <p>커리어 공백기를 근거 있는 STAR 내러티브로 정리해드려요.</p>

      {isLoading ? (
        <p>불러오는 중...</p>
      ) : user ? (
        <>
          <p>{user.nickname}님, 환영합니다.</p>
          <button type="button" onClick={handleStart} disabled={isCreating}>
            {isCreating ? "시작하는 중..." : "새로 시작하기"}
          </button>
          {error && <p style={{ color: "crimson" }}>{error}</p>}
          <p>
            <button type="button" onClick={() => logout()} style={{ marginTop: 24 }}>
              로그아웃
            </button>
          </p>
        </>
      ) : (
        <p>
          <Link href="/login">로그인</Link> 또는 <Link href="/register">회원가입</Link>으로 시작하세요.
        </p>
      )}
    </main>
  );
}
