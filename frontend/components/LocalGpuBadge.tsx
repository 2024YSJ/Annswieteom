import type { GpuGenerationStatsRead } from "@/lib/api-client";

/** "이 답변은 클라우드로 전송되지 않고 우리 팀 GPU에서 처리됨"을 보여주는
 * 작은 배지. generate/regenerate 응답에만 실리는 generation_stats가 있을
 * 때만 렌더된다 — 재조회나 데모(시드 데이터)에는 실시간 계측이 없으니
 * 억지로 값을 흉내 내지 않고 아예 표시하지 않는다. */
export function LocalGpuBadge({ stats }: { stats: GpuGenerationStatsRead | null | undefined }) {
  if (!stats) return null;

  return (
    <span
      title={`모델: ${stats.model} · 호출 ${stats.call_count}회 · 출력 ${stats.total_output_tokens} 토큰`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 11,
        padding: "3px 8px",
        borderRadius: "var(--radius-lg)",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        color: "var(--muted-text)",
      }}
    >
      🖥️ 로컬 GPU에서 처리됨 · {stats.tokens_per_second.toFixed(1)} tok/s
    </span>
  );
}
