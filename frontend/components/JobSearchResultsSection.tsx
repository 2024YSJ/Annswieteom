"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { jobSearchApi, type JobPostingRead, type SessionStatus } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { ChatBubble } from "@/components/ChatBubble";
import { LoadingNotice } from "@/components/LoadingNotice";

export function JobSearchResultsSection({
  sessionId,
  accessToken,
  status,
  results,
  lastSearchedAt,
}: {
  sessionId: string;
  accessToken: string;
  status: SessionStatus;
  results: JobPostingRead[];
  lastSearchedAt: string | null;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  // 워크넷 조회 + 최대 15건 judge_job_fit 병렬 호출이라 로컬 Ollama에서는
  // 수 초~수십 초 걸릴 수 있다 — status가 JOB_SEARCHING으로 들어오면 한 번만
  // 자동으로 트리거한다(ResultSection의 generateFiredRef와 동일 패턴).
  const searchFiredRef = useRef(false);

  useEffect(() => {
    if (status !== "JOB_SEARCHING" || searchFiredRef.current) return;
    searchFiredRef.current = true;
    setIsSearching(true);
    jobSearchApi
      .search(sessionId, accessToken)
      .then((state) => {
        queryClient.setQueryData(queryKeys.jobSearch(sessionId), state);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setIsSearching(false));
  }, [status, sessionId, accessToken, queryClient]);

  async function handleResearch() {
    setError(null);
    setIsSearching(true);
    try {
      const state = await jobSearchApi.search(sessionId, accessToken);
      queryClient.setQueryData(queryKeys.jobSearch(sessionId), state);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSearching(false);
    }
  }

  if (status === "JOB_SEARCHING" && results.length === 0) {
    return (
      <ChatBubble side="left">
        <LoadingNotice label="조건에 맞는 채용정보를 찾고 있어요..." />
      </ChatBubble>
    );
  }

  return (
    <ChatBubble side="left" variant="card">
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 13, color: "var(--muted-text)" }}>
            {lastSearchedAt ? `${new Date(lastSearchedAt).toLocaleString("ko-KR")} 기준` : "검색 결과"}
          </div>
          <button type="button" onClick={handleResearch} disabled={isSearching}>
            {isSearching ? "찾는 중..." : "다시 찾기"}
          </button>
        </div>

        {error && <p style={{ color: "crimson", fontSize: 13 }}>{error}</p>}

        {results.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--muted-text)" }}>
            조건에 맞는 공고를 찾지 못했어요. 조건을 조금 넓혀보세요.
          </p>
        ) : (
          results.map((posting) => (
            <JobPostingCard key={`${posting.source}-${posting.external_id}`} posting={posting} />
          ))
        )}
      </div>
    </ChatBubble>
  );
}

function JobPostingCard({ posting }: { posting: JobPostingRead }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div>
          <div style={{ fontWeight: 700 }}>{posting.title}</div>
          <div style={{ fontSize: 13, color: "var(--muted-text)" }}>{posting.company}</div>
        </div>
        <span
          style={{
            fontSize: 12,
            padding: "2px 8px",
            borderRadius: 999,
            background: posting.fit ? "#e3f0dc" : "#f5e6e0",
            color: posting.fit ? "#4a6b2a" : "#9a4a2a",
            flexShrink: 0,
            whiteSpace: "nowrap",
          }}
        >
          {posting.fit ? "적합" : "조건 다름"}
        </span>
      </div>
      <div style={{ fontSize: 13 }}>{posting.reason}</div>
      <div style={{ fontSize: 12, color: "var(--muted-text)" }}>
        {[posting.salary_text, posting.location, posting.education_requirement, posting.career_requirement, posting.work_type]
          .filter(Boolean)
          .join(" · ")}
      </div>
      {posting.url && (
        <a href={posting.url} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>
          공고 보러가기 ↗
        </a>
      )}
    </div>
  );
}
