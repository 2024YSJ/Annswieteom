"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionApi, type SessionKind, type SessionRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/lib/auth-context";
import { useSessionsList } from "@/lib/use-sessions-list";
import { GAP_FILL_STATUS_LABELS, JOB_SEARCH_STATUS_LABELS } from "@/lib/session-routes";

function statusLabel(session: SessionRead): string {
  const labels = session.kind === "job_search" ? JOB_SEARCH_STATUS_LABELS : GAP_FILL_STATUS_LABELS;
  return labels[session.status] ?? session.status;
}

function SessionRow({ session, isActive, accessToken }: { session: SessionRead; isActive: boolean; accessToken: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState(session.title ?? "");
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isMigrating, setIsMigrating] = useState(false);
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
    setIsMenuOpen(false);
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

  // 공백기 채우기 인터뷰로 확정한 사실을 취업 정보 검색으로 넘긴다 — 새
  // job_search 세션을 만들어 연결해두면, 그 세션의 첫 진입 시 AI가 확정된
  // 사실을 요약한 질문 초안을 컴포저에 미리 채워준다(JobSearchChatPage 참고).
  async function handleMigrateToJobSearch() {
    setIsMenuOpen(false);
    setError(null);
    setIsMigrating(true);
    try {
      const jobSession = await sessionApi.create(accessToken, { kind: "job_search", linked_gap_session_id: session.id });
      await queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      router.push(`/sessions/${jobSession.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setIsMigrating(false);
    }
  }

  return (
    <li style={{ position: "relative" }}>
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
            <div style={{ color: "var(--muted-text)" }}>{isMigrating ? "이관하는 중..." : statusLabel(session)}</div>
          </Link>
        )}
        {!isEditing && (
          <button
            type="button"
            onClick={() => setIsMenuOpen((v) => !v)}
            title="더보기"
            aria-label="더보기"
            aria-haspopup="menu"
            aria-expanded={isMenuOpen}
            disabled={isMigrating}
            style={{ flexShrink: 0, fontSize: 14, lineHeight: 1 }}
          >
            ⋯
          </button>
        )}
      </div>

      {isMenuOpen && (
        <>
          {/* 바깥을 클릭하면 메뉴를 닫는 투명 오버레이 — 모달 라이브러리 없이
           * 클릭 아웃사이드를 처리하는 가장 단순한 방법. */}
          <div
            onClick={() => setIsMenuOpen(false)}
            style={{ position: "fixed", inset: 0, zIndex: 10 }}
          />
          <div
            role="menu"
            style={{
              position: "absolute",
              right: 0,
              top: "100%",
              zIndex: 11,
              minWidth: 160,
              background: "var(--surface)",
              color: "var(--surface-text)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
              display: "flex",
              flexDirection: "column",
              padding: 4,
            }}
          >
            {session.kind !== "job_search" && (
              <button
                type="button"
                role="menuitem"
                onClick={handleMigrateToJobSearch}
                style={{ textAlign: "left", fontSize: 13, padding: "8px 10px", background: "transparent", border: "none" }}
              >
                취업 정보 검색으로 이관
              </button>
            )}
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setIsMenuOpen(false);
                setIsEditing(true);
              }}
              style={{ textAlign: "left", fontSize: 13, padding: "8px 10px", background: "transparent", border: "none" }}
            >
              이름 변경
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={handleDelete}
              style={{ textAlign: "left", fontSize: 13, padding: "8px 10px", background: "transparent", border: "none", color: "crimson" }}
            >
              삭제
            </button>
          </div>
        </>
      )}

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

  async function handleNewSession(kind: SessionKind) {
    if (!accessToken) return;
    setCreateError(null);
    setIsCreating(true);
    try {
      const session = await sessionApi.create(accessToken, { kind });
      await queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      router.push(`/sessions/${session.id}`);
    } catch (err) {
      setCreateError(errorMessage(err));
    } finally {
      setIsCreating(false);
    }
  }

  const gapFillSessions = sessions?.filter((s) => s.kind !== "job_search") ?? [];
  const jobSearchSessions = sessions?.filter((s) => s.kind === "job_search") ?? [];

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
        {createError && <p style={{ color: "crimson", fontSize: 11, marginBottom: 8 }}>{createError}</p>}

        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <SessionGroup
            title="공백기 채우기"
            newLabel="+ 공백기 채우기"
            onNew={() => handleNewSession("gap_fill")}
            isCreating={isCreating}
            sessions={gapFillSessions}
            activeId={params.id}
            accessToken={accessToken}
          />
          <SessionGroup
            title="취업 정보 검색"
            newLabel="+ 취업 정보 검색"
            onNew={() => handleNewSession("job_search")}
            isCreating={isCreating}
            sessions={jobSearchSessions}
            activeId={params.id}
            accessToken={accessToken}
          />
        </div>
      </aside>
    </div>
  );
}

function SessionGroup({
  title,
  newLabel,
  onNew,
  isCreating,
  sessions,
  activeId,
  accessToken,
}: {
  title: string;
  newLabel: string;
  onNew: () => void;
  isCreating: boolean;
  sessions: SessionRead[];
  activeId: string | undefined;
  accessToken: string | null;
}) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h2 style={{ fontSize: 14, color: "var(--muted-text)", margin: 0 }}>{title}</h2>
        <button type="button" onClick={onNew} disabled={isCreating} title={newLabel} style={{ fontSize: 12 }}>
          {isCreating ? "..." : newLabel}
        </button>
      </div>
      {sessions.length === 0 ? (
        <p style={{ fontSize: 13, color: "var(--muted-text)" }}>세션이 없습니다.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
          {sessions.map((session) =>
            accessToken ? (
              <SessionRow key={session.id} session={session} isActive={session.id === activeId} accessToken={accessToken} />
            ) : null,
          )}
        </ul>
      )}
    </div>
  );
}
