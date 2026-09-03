"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";
import { RecordUploadPanel } from "@/components/RecordUploadPanel";

export function RecordsSection({
  sessionId,
  accessToken,
  mode,
}: {
  sessionId: string;
  accessToken: string;
  mode: "completed" | "active";
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [isSkipping, setIsSkipping] = useState(false);
  const [recordCount, setRecordCount] = useState(0);

  if (mode === "completed") {
    return <ChatBubble side="right">기록물 업로드를 완료했어요.</ChatBubble>;
  }

  async function handleAdvance() {
    setError(null);
    setIsSkipping(true);
    try {
      await sessionApi.skipRecords(sessionId, accessToken);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSkipping(false);
    }
  }

  return (
    <ChatBubble side="left">
      <div aria-live="polite">
        <p style={{ margin: "0 0 4px", fontWeight: "bold" }}>참고할 기록물이 있나요?</p>
        <p style={{ margin: "0 0 12px", color: "#666" }}>
          블로그 글, 자격증 이미지, 또는 직접 적은 메모를 등록하면 더 구체적인 초안을 만들어드려요. 없어도 괜찮아요.
        </p>
      </div>

      <RecordUploadPanel sessionId={sessionId} accessToken={accessToken} onRecordsChange={setRecordCount} />

      {error && <p style={{ color: "crimson" }}>{error}</p>}
      <button type="button" onClick={handleAdvance} disabled={isSkipping} style={{ marginTop: 16 }}>
        {isSkipping ? "진행 중..." : recordCount > 0 ? "다음으로" : "기록물 없이 넘어가기"}
      </button>
    </ChatBubble>
  );
}
