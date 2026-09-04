"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type SessionRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/lib/auth-context";
import { useSessionsList } from "@/lib/use-sessions-list";

const STATUS_LABELS: Record<string, string> = {
  PERIOD_INPUT: "기간 입력",
  CATEGORY_SELECT: "카테고리 선택",
  RECORD_UPLOAD: "기록물 업로드",
  INTERVIEWING: "인터뷰 중",
  RESULT_GENERATE: "결과 생성 중",
  RESULT_REVIEW: "결과 확인",
};

function SessionRow({ session, isActive, accessToken }: { session: SessionRead; isActive: boolean; accessToken: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState(session.title ?? "");
  const [error, setError] = useState<string | null>(null);

  async function saveTitle() {
    setIsEditing(false);
    if (titleDraft === (session.title ?? "")) return; // no change
    setError(null);
    try {
      await sessionApi.rename(session.id, titleDraft, accessToken);
      await queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function handleDelete() {
    if (!window.confirm("이 세션을 삭제할까요? 되돌릴 수 없습니다.")) return;
    setError(null);
    try {
      await sessionApi.remove(session.id, accessToken);
      await queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      if (isActive) router.push("/");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <li>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {isEditing ? (
          <input
            type="text"
            autoFocus
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={saveTitle}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur(); // triggers saveTitle via onBlur
              if (e.key === "Escape") {
                setTitleDraft(session.title ?? "");
                setIsEditing(false);
              }
            }}
            style={{ flex: 1, minWidth: 0, fontSize: 13, padding: "8px 10px" }}
          />
        ) : (
          <Link
            href={`/sessions/${session.id}`}
            style={{
              flex: 1,
              minWidth: 0,
              display: "block",
              padding: "8px 10px",
              borderRadius: 6,
              fontSize: 13,
              textDecoration: "none",
              background: isActive ? "var(--hover-surface)" : "transparent",
              color: isActive ? "var(--hover-surface-text)" : "inherit",
            }}
          >
            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {session.title ?? new Date(session.created_at).toLocaleDateString("ko-KR")}
            </div>
            <div style={{ color: "var(--muted-text)" }}>{STATUS_LABELS[session.status] ?? session.status}</div>
          </Link>
        )}
        {!isEditing && (
          <>
            <button
              type="button"
              onClick={() => setIsEditing(true)}
              title="이름 변경"
              aria-label="이름 변경"
              style={{ flexShrink: 0, fontSize: 12 }}
            >
              ✏️
            </button>
            <button
              type="button"
              onClick={handleDelete}
              title="삭제"
              aria-label="삭제"
              style={{ flexShrink: 0, fontSize: 12 }}
            >
              🗑
            </button>
          </>
        )}
      </div>
      {error && <p style={{ color: "crimson", fontSize: 11, margin: "2px 0 0" }}>{error}</p>}
    </li>
  );
}

export default function SessionsLayout({ children }: LayoutProps<"/sessions">) {
  const params = useParams<{ id?: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const { accessToken } = useAuth();
  const { data: sessions } = useSessionsList();
  const queryClient = useQueryClient();
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // Navigating to a different session closes the mobile drawer — "adjust
  // state during render" instead of an effect (desktop has no drawer, so
  // this has no visible effect there).
  const [lastPathname, setLastPathname] = useState(pathname);
  if (pathname !== lastPathname) {
    setLastPathname(pathname);
    setIsSidebarOpen(false);
  }

  useEffect(() => {
    // A step page completing (e.g. period -> categories) changes this
    // session's status server-side; refresh the sidebar so it reflects
    // the new step instead of the one the user just left.
    queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
  }, [pathname, queryClient]);

  async function handleNewSession() {
    if (!accessToken) return;
    setCreateError(null);
    setIsCreating(true);
    try {
      const session = await sessionApi.create(accessToken);
      await queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      router.push(`/sessions/${session.id}`);
    } catch (err) {
      setCreateError(errorMessage(err));
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <div className="app-shell">
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>

      <button
        type="button"
        className="sidebar-toggle"
        onClick={() => setIsSidebarOpen((v) => !v)}
        title="내 세션 목록"
        aria-label="내 세션 목록 열기"
      >
        ☰
      </button>
      <div className={`sidebar-backdrop ${isSidebarOpen ? "is-open" : ""}`} onClick={() => setIsSidebarOpen(false)} />

      <aside className={`app-sidebar ${isSidebarOpen ? "is-open" : ""}`}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h2 style={{ fontSize: 14, color: "var(--muted-text)", margin: 0 }}>내 세션</h2>
          <button type="button" onClick={handleNewSession} disabled={isCreating} title="새 세션 시작" style={{ fontSize: 12 }}>
            {isCreating ? "..." : "+ 새 세션"}
          </button>
        </div>
        {createError && <p style={{ color: "crimson", fontSize: 11, marginBottom: 8 }}>{createError}</p>}
        {!sessions || sessions.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--muted-text)" }}>세션이 없습니다.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            {sessions.map((session) =>
              accessToken ? (
                <SessionRow key={session.id} session={session} isActive={session.id === params.id} accessToken={accessToken} />
              ) : null,
            )}
          </ul>
        )}
      </aside>
    </div>
  );
}
