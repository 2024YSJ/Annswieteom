"use client";

import { useQuery } from "@tanstack/react-query";
import { trustApi, type TrustScoreRead } from "@/lib/api-client";
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

/** 스코어보드의 실제 표시부 — 세션 단위(TrustScoreboard)와 전역(GlobalTrustScoreboard)이
 * 같은 지표를 같은 모양으로 보여줘야 두 화면(실제 결과/원클릭 데모)이 갈라지지 않는다. */
export function TrustStatsRow({ data }: { data: TrustScoreRead }) {
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
      }}
    >
      <Stat label="근거 보유율" value={pct(data.evidence_coverage_ratio)} />
      <Stat label="정직성 재검증 통과율" value={pct(data.consistency_pass_rate)} />
      <Stat label="AI 초안 그대로 채택" value={pct(data.ai_acceptance_rate)} />
      <Stat label="인터뷰 단계 AI 초안 수용률" value={pct(data.interview_ai_acceptance_rate)} />
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
    <div style={{ marginBottom: 16 }}>
      <TrustStatsRow data={data} />
    </div>
  );
}

/** 전역(FINAL 문서 전체) 지표 — 완전 무인증. 원클릭 데모 페이지에서 "이 서비스
 * 전체가 얼마나 근거 있는 문서를 만드는지"를 보여주는 용도. */
export function GlobalTrustScoreboard() {
  const { data } = useQuery({
    queryKey: queryKeys.globalTrustScore(),
    queryFn: () => trustApi.global(),
  });

  if (!data) return null;
  return <TrustStatsRow data={data} />;
}
