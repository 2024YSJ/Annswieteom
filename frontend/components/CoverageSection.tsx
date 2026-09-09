"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { coverageApi, type DateRangeRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";

/** "2025-03-01" -> "2025년 3월". 서버가 내려주는 구간 라벨과 같은 표기다
 * (app/services/coverage.py의 _format_range). */
function monthLabel(iso: string): string {
  const [year, month] = iso.split("-");
  return `${year}년 ${Number(month)}월`;
}

function rangeLabel(range: DateRangeRead): string {
  const start = monthLabel(range.start);
  const end = monthLabel(range.end);
  return start === end ? start : `${start} ~ ${end}`;
}

function CoverageBar({ ratio }: { ratio: number }) {
  const percent = Math.round(ratio * 100);
  return (
    <div style={{ marginBottom: 8 }}>
      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="공백기 설명 비율"
        style={{ height: 8, borderRadius: 999, background: "var(--border)", overflow: "hidden" }}
      >
        <div style={{ width: `${percent}%`, height: "100%", background: "var(--accent)" }} />
      </div>
      <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--body-text)" }}>공백기의 약 {percent}%가 설명됐어요.</p>
    </div>
  );
}

/** 공백기 중 아직 이야기가 없는 구간을 보여주고, 그 구간을 인터뷰 대상으로 올린다.
 *
 * 이 화면이 서비스가 대화형 LLM과 갈리는 지점이다 — 채팅창은 사용자가 꺼내지 않은
 * 시기를 스스로 알아차리지 못한다. 여기서는 공백기도 활동도 날짜 구간이므로
 * 덮이지 않은 부분을 뺄셈으로 정확히 지목할 수 있다.
 */
export function CoverageSection({
  sessionId,
  accessToken,
}: {
  sessionId: string;
  accessToken: string;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [fillingRange, setFillingRange] = useState<string | null>(null);

  const { data: coverage } = useQuery({
    queryKey: queryKeys.coverage(sessionId),
    queryFn: () => coverageApi.get(sessionId, accessToken),
    // 공백 기간이 아직 없으면 409가 뜬다 — 재시도할 성질의 오류가 아니다.
    retry: false,
  });

  if (!coverage) return null;

  const unknownCount = coverage.categories_without_period.length;

  async function handleFill(range: DateRangeRead) {
    setError(null);
    setFillingRange(range.start);
    try {
      await coverageApi.fill(sessionId, range.start, range.end, accessToken);
      // 세션 상태와 현재 카테고리가 바뀌므로 세션 컨텍스트까지 새로 받아야
      // 인터뷰 화면이 새 카테고리로 넘어간다.
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.coverage(sessionId) });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setFillingRange(null);
    }
  }

  return (
    <section>
      <ChatBubble side="left" variant="card" label="공백기 채움 현황">
        <CoverageBar ratio={coverage.coverage_ratio} />

        {unknownCount > 0 && (
          <p style={{ margin: "0 0 8px", fontSize: 12, color: "var(--muted-text)" }}>
            기간을 아직 모르는 활동이 {unknownCount}개 있어요 — 실제로는 이보다 더 채워져 있을 수 있습니다.
          </p>
        )}

        {coverage.uncovered_ranges.length === 0 ? (
          <p style={{ margin: 0 }}>아직 이야기가 없는 시기는 없어요.</p>
        ) : (
          <>
            {coverage.suggested_probe_question && (
              <p style={{ margin: "0 0 8px" }}>{coverage.suggested_probe_question}</p>
            )}
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
              {coverage.uncovered_ranges.map((range) => (
                <li
                  key={range.start}
                  style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
                >
                  <span style={{ flex: 1, minWidth: 140 }}>
                    {rangeLabel(range)}{" "}
                    <span style={{ color: "var(--muted-text)", fontSize: 12 }}>({range.days}일)</span>
                  </span>
                  <button
                    type="button"
                    disabled={fillingRange !== null}
                    onClick={() => handleFill(range)}
                  >
                    {fillingRange === range.start ? "여는 중..." : "이 시기 이야기하기"}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {error && <p className="msg-error" style={{ marginTop: 8 }}>{error}</p>}
      </ChatBubble>
    </section>
  );
}
