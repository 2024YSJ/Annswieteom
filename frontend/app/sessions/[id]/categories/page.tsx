"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type CategoryType } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { CATEGORY_LABELS, pathForStatus } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { useSessionContext } from "@/lib/use-session-context";
import { useAuth } from "@/lib/auth-context";

const ALL_CATEGORIES = Object.keys(CATEGORY_LABELS) as CategoryType[];

export default function CategoriesPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const router = useRouter();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const { data: ctx, isLoading, error: loadError } = useSessionContext(sessionId);

  const [selected, setSelected] = useState<CategoryType[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (ctx && ctx.status !== "CATEGORY_SELECT") {
      router.replace(pathForStatus(sessionId, ctx.status));
    }
  }, [ctx, sessionId, router]);

  function toggle(category: CategoryType) {
    setSelected((prev) =>
      prev.includes(category) ? prev.filter((c) => c !== category) : [...prev, category],
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (selected.length === 0) {
      setError("하나 이상 선택해주세요.");
      return;
    }

    setIsSubmitting(true);
    try {
      await sessionApi.selectCategories(sessionId, selected, accessToken!);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      router.push(`/sessions/${sessionId}/records`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading) return <main style={{ maxWidth: 480, margin: "80px auto" }}>불러오는 중...</main>;
  if (loadError) {
    return (
      <main style={{ maxWidth: 480, margin: "80px auto", padding: "0 16px" }}>
        <p style={{ color: "crimson" }}>{errorMessage(loadError)}</p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 480, margin: "80px auto", padding: "0 16px" }}>
      <h1>어떤 활동을 하셨나요?</h1>
      <p>해당하는 활동을 모두 선택해주세요 (복수 선택 가능).</p>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {ALL_CATEGORIES.map((category) => (
          <label key={category} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={selected.includes(category)}
              onChange={() => toggle(category)}
            />
            {CATEGORY_LABELS[category]}
          </label>
        ))}
        {error && <p style={{ color: "crimson" }}>{error}</p>}
        <button type="submit" disabled={isSubmitting} style={{ marginTop: 12 }}>
          {isSubmitting ? "저장 중..." : "다음"}
        </button>
      </form>
    </main>
  );
}
