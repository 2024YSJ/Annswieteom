"use client";

import { useQuery } from "@tanstack/react-query";
import { trustApi } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";

function pct(ratio: number | null): string {
  if (ratio === null) return "—";
  return `${Math.round(ratio * 100)}%`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontWeight: 700, fontSize: 16 }}>{value}</div>
      <div style={{ color: "var(--muted-text)", fontSize: 12 }}>{label}</div>
    </div>
  );
}

/** 문서 하나의 정직성 가드레일 준수 지표 — 근거 보유율/정직성 재검증 통과율/
 * AI 초안 수용률을 숫자로 보여준다. DB에만 있던 지표를 화면에 드러내는 것 자체가
 * 목적이라(원티드 챔피언십 심사기준 "AI 활용의 적절성" 대응), 새 계산은 전혀
 * 하지 않고 GET /trust-score 응답을 그대로 카드로 나열한다. */
export function TrustScoreboard({
  sessionId,
  accessToken,
  enabled,
}: {
  sessionId: string;
  accessToken: string;
  enabled: boolean;
}) {
  const { data } = useQuery({
    queryKey: queryKeys.trustScore(sessionId),
    queryFn: () => trustApi.session(sessionId, accessToken),
    enabled,
  });

  if (!enabled || !data) return null;

  return (
    <div
      style={{
        display: "flex",
        gap: 20,
        flexWrap: "wrap",
        padding: 12,
        borderRadius: "var(--radius-md)",
        background: "var(--surface-strong)",
        border: "1px solid var(--border)",
        marginBottom: 16,
      }}
    >
      <Stat label="근거 보유율" value={pct(data.evidence_coverage_ratio)} />
      <Stat label="정직성 재검증 통과율" value={pct(data.consistency_pass_rate)} />
      <Stat label="AI 초안 그대로 채택" value={pct(data.ai_acceptance_rate)} />
      <Stat label="인터뷰 단계 AI 초안 수용률" value={pct(data.interview_ai_acceptance_rate)} />
    </div>
  );
}
