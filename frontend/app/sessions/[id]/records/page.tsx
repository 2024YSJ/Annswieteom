"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { pathForStatus } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { useSessionContext } from "@/lib/use-session-context";
import { useAuth } from "@/lib/auth-context";
import { RecordUploadPanel } from "@/components/RecordUploadPanel";

export default function RecordsPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const router = useRouter();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const { data: ctx, isLoading, error: loadError } = useSessionContext(sessionId);

  const [error, setError] = useState<string | null>(null);
  const [isSkipping, setIsSkipping] = useState(false);

  useEffect(() => {
    if (ctx && ctx.status !== "RECORD_UPLOAD") {
      router.replace(pathForStatus(sessionId, ctx.status));
    }
  }, [ctx, sessionId, router]);

  async function handleSkip() {
    setError(null);
    setIsSkipping(true);
    try {
      await sessionApi.skipRecords(sessionId, accessToken!);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      router.push(`/sessions/${sessionId}/interview`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSkipping(false);
    }
  }

  if (isLoading) return <main style={{ maxWidth: 640, margin: "80px auto" }}>불러오는 중...</main>;
  if (loadError) {
    return (
      <main style={{ maxWidth: 640, margin: "80px auto", padding: "0 16px" }}>
        <p style={{ color: "crimson" }}>{errorMessage(loadError)}</p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 640, margin: "80px auto", padding: "0 16px" }}>
      <h1>참고할 기록물이 있나요?</h1>
      <p>블로그 글, 자격증 이미지, 또는 직접 적은 메모를 등록하면 더 구체적인 초안을 만들어드려요. 없어도 괜찮아요.</p>

      <RecordUploadPanel sessionId={sessionId} accessToken={accessToken!} />

      {error && <p style={{ color: "crimson" }}>{error}</p>}
      <button type="button" onClick={handleSkip} disabled={isSkipping} style={{ marginTop: 24 }}>
        {isSkipping ? "진행 중..." : "기록물 없이 넘어가기"}
      </button>
    </main>
  );
}
