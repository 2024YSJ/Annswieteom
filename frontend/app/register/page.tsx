"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { authApi, ApiError } from "@/lib/api-client";

export default function RegisterPage() {
  const router = useRouter();
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

    setIsSubmitting(true);
    try {
      await authApi.register({ email, password, nickname });
      router.push("/login");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("이미 가입된 이메일입니다.");
      } else {
        setError("회원가입에 실패했습니다. 잠시 후 다시 시도해주세요.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main style={{ maxWidth: 360, margin: "80px auto", padding: "0 16px" }}>
      <h1>회원가입</h1>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          이메일
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          닉네임
          <input
            type="text"
            required
            autoComplete="nickname"
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
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
        {error && <p style={{ color: "crimson" }}>{error}</p>}
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "가입 중..." : "가입하기"}
        </button>
      </form>
      <p>
        이미 계정이 있으신가요? <Link href="/login">로그인</Link>
      </p>
    </main>
  );
}
