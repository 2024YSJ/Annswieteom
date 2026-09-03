"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { pathForStatus } from "@/lib/session-routes";
import { queryKeys } from "@/lib/query-keys";
import { useSessionsList } from "@/lib/use-sessions-list";

const STATUS_LABELS: Record<string, string> = {
  PERIOD_INPUT: "기간 입력",
  CATEGORY_SELECT: "카테고리 선택",
  RECORD_UPLOAD: "기록물 업로드",
  FREQ_DRAFT: "인터뷰 중",
  FREQ_CONFIRM: "인터뷰 중",
  TASK_DRAFT: "인터뷰 중",
  TASK_CONFIRM: "인터뷰 중",
  ACHIEVEMENT_DRAFT: "인터뷰 중",
  ACHIEVEMENT_CONFIRM: "인터뷰 중",
  RESULT_GENERATE: "결과 생성 중",
  RESULT_REVIEW: "결과 확인",
};

export default function SessionsLayout({ children }: LayoutProps<"/sessions">) {
  const params = useParams<{ id?: string }>();
  const pathname = usePathname();
  const { data: sessions } = useSessionsList();
  const queryClient = useQueryClient();

  useEffect(() => {
    // A step page completing (e.g. period -> categories) changes this
    // session's status server-side; refresh the sidebar so it reflects
    // the new step instead of the one the user just left.
    queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
  }, [pathname, queryClient]);

  return (
    <div style={{ display: "flex" }}>
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
      <aside
        style={{
          width: 220,
          flexShrink: 0,
          borderLeft: "1px solid #eee",
          padding: "80px 16px 16px",
          minHeight: "100vh",
          boxSizing: "border-box",
        }}
      >
        <h2 style={{ fontSize: 14, color: "#888", marginBottom: 12 }}>내 세션</h2>
        {!sessions || sessions.length === 0 ? (
          <p style={{ fontSize: 13, color: "#aaa" }}>세션이 없습니다.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            {sessions.map((session) => (
              <li key={session.id}>
                <Link
                  href={pathForStatus(session.id, session.status)}
                  style={{
                    display: "block",
                    padding: "8px 10px",
                    borderRadius: 6,
                    fontSize: 13,
                    textDecoration: "none",
                    background: session.id === params.id ? "#f0f0f0" : "transparent",
                  }}
                >
                  <div>{new Date(session.created_at).toLocaleDateString("ko-KR")}</div>
                  <div style={{ color: "#888" }}>{STATUS_LABELS[session.status] ?? session.status}</div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
