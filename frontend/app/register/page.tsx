"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { authApi } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { useAuth } from "@/lib/auth-context";

export default function RegisterPage() {
  const router = useRouter();
  const { accessToken, user, refreshUser } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError("비밀번호는 8자 이상이어야 합니다.");
      return;
    }

    const wasGuest = user?.is_guest ?? false;

    setIsSubmitting(true);
    try {
      await authApi.register({ email, password, nickname }, wasGuest ? accessToken ?? undefined : undefined);
      if (wasGuest) {
        // Same access token, same session(s) — just re-fetch /auth/me so the
        // UI reflects the now-registered identity instead of re-logging-in.
        await refreshUser();
        router.push("/");
      } else {
        router.push("/login");
      }
    } catch (err) {
      setError(errorMessage(err, "회원가입에 실패했습니다. 잠시 후 다시 시도해주세요."));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="card auth-card">
        <h1>회원가입</h1>
        <p className="auth-lede">
          {user?.is_guest
            ? "체험하며 만든 문서를 그대로 가져갑니다."
            : "만든 문서를 저장하고 언제든 다시 열어볼 수 있어요."}
        </p>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <label className="field">
            이메일
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label className="field">
            닉네임
            <input
              type="text"
              required
              autoComplete="nickname"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
            />
          </label>
          <label className="field">
            비밀번호 (8자 이상)
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && <p className="msg-error">{error}</p>}
          <button type="submit" className="btn-primary btn-block" disabled={isSubmitting} style={{ marginTop: 2 }}>
            {isSubmitting ? "가입 중..." : "가입하기"}
          </button>
        </form>
        <p className="auth-foot">
          이미 계정이 있으신가요? <Link href="/login">로그인</Link>
        </p>
      </div>
    </main>
  );
}
