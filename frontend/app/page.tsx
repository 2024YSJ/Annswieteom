"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { sessionApi, type SessionKind, type SessionRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { sessionStatusLabel } from "@/lib/session-routes";
import { useSessionsList } from "@/lib/use-sessions-list";
import { ExampleDocumentModal } from "@/components/ExampleDocumentModal";
import { ExampleInterviewModal } from "@/components/ExampleInterviewModal";
import { FeedSection } from "@/components/FeedSection";
import { LoadingNotice } from "@/components/LoadingNotice";

/** 메인 화면.
 *
 * 2026-09-09까지 이 페이지는 세션이 하나라도 있는 로그인 사용자를 곧바로 가장
 * 최근 세션으로 리다이렉트했다. 피드(docs/specs/main_page_feed.md)를 붙이면서
 * 그 리다이렉트를 걷어냈다 — 맞춤 공고는 문답이 쌓인 사용자에게만 의미가 있는데,
 * 리다이렉트가 살아 있으면 **정확히 그 사용자만 메인 화면을 못 본다.** 로고를
 * 눌러도 세션으로 되돌아와서 홈이라는 화면 자체가 도달 불가능하기도 했다.
 *
 * 대신 아래 "이어서 하기"가 최근 세션으로 가는 한 번의 클릭을 보장한다.
 */
export default function Home() {
  const router = useRouter();
  const { user, accessToken, isLoading, guestLogin } = useAuth();
  const { data: sessions, error: sessionsError, refetch: refetchSessions } = useSessionsList();
  const [error, setError] = useState<string | null>(null);
  const [pendingKind, setPendingKind] = useState<SessionKind | null>(null);
  const [isExampleOpen, setIsExampleOpen] = useState(false);
  const [isQaExampleOpen, setIsQaExampleOpen] = useState(false);
  // 모달을 닫을 때 포커스를 열었던 버튼으로 되돌리기 위해 붙잡아둔다.
  const exampleTriggerRef = useRef<HTMLButtonElement>(null);
  const qaExampleTriggerRef = useRef<HTMLButtonElement>(null);

  function closeExample() {
    setIsExampleOpen(false);
    exampleTriggerRef.current?.focus();
  }

  function closeQaExample() {
    setIsQaExampleOpen(false);
    qaExampleTriggerRef.current?.focus();
  }

  // 첫 화면에서 곧바로 서비스로 들어가는 경로. 로그인 여부와 무관하게 카드 한
  // 번 누르면 (필요하면 게스트 로그인까지 해서) 세션을 만들고 대화 화면으로
  // 넘어간다.
  //
  // 게스트 로그인과 세션 생성이 한 클릭 안에서 순차로 일어나는 게 핵심이다.
  // 예전에는 "게스트로 시작" 버튼이 로그인만 하고, 세션 생성은 리다이렉트
  // effect가 따로 했는데 — 갓 만들어진 같은 게스트를 두고 둘이 경쟁해 세션이
  // 두 개 생기는 일이 있었다(2026-09-05 프로덕션 버그).
  async function startFlow(kind: SessionKind) {
    if (pendingKind) return;
    setError(null);
    setPendingKind(kind);
    try {
      const token = accessToken ?? (await guestLogin());
      const session = await sessionApi.create(token, { kind });
      // 성공 시엔 pendingKind를 일부러 안 푼다 — 화면이 넘어가는 동안 카드가
      // 계속 비활성으로 남아 중복 클릭을 막는다.
      router.push(`/sessions/${session.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setPendingKind(null);
    }
  }

  // 로그인 상태를 아직 확인 중일 때만 화면 전체를 로딩으로 덮는다. 세션 목록은
  // 늦게 와도 되고 실패해도 되는 정보라(피드와 히어로는 그것 없이 그릴 수 있다)
  // 여기서 기다리지 않는다.
  if (isLoading) {
    return (
      <main style={NOTICE_MAIN_STYLE}>
        <LoadingNotice />
      </main>
    );
  }

  // !!user도 함께 본다 — 로그아웃 직후 세션 목록 캐시가 아직 안 지워진 찰나에도
  // 이전 사용자의 이름·"이어서 하기" 카드가 뜨지 않게 한다(2026-09-12 검증 발견;
  // AuthHeader.handleLogout에서 캐시 자체도 지우므로 이 조건은 이중 방어다).
  const hasSessions = !!user && !!sessions && sessions.length > 0;

  return (
    <main className="landing">
      {hasSessions ? (
        <section className="hero hero-compact">
          <h1>{user?.nickname}님, 이어서 해볼까요?</h1>
          <p className="hero-sub">지난 경험의 불분명한 기억을, 구체적인 커리어 문서로.</p>
        </section>
      ) : (
        <section className="hero">
          <span className="hero-eyebrow">커리어 채우기 · 취업 정보</span>
          <h1>우리는 쉬지 않았습니다</h1>
          <p className="hero-sub">
            지난 경험의 불분명한 기억을, <b>구체적인 커리어 문서</b>로.
          </p>
        </section>
      )}

      {hasSessions && <ResumeSection sessions={sessions} />}

      <section className="flows">
        <div className="flow-grid">
          <div className="flow-wrap">
            {!user && <div className="bubble-tip">가입 없이 바로 체험</div>}
            <button type="button" className="flow" onClick={() => startFlow("gap_fill")} disabled={pendingKind !== null}>
              <span className="flow-icon" aria-hidden>
                ✍️
              </span>
              <span className="flow-title">커리어 채우기</span>
              <span className="flow-desc">
                일했던 기간도, 쉬었던 기간도 모두 괜찮아요. 딱히 떠오르는 게 없어도 AI가 질문을 깊이 이어가며, 이력서에 그대로 쓸 수 있는 구체적인 STAR
                문장으로 정리해요.
              </span>
              <span className="flow-go">
                {pendingKind === "gap_fill" ? "시작하는 중..." : hasSessions ? "새로 시작하기" : "시작하기"}{" "}
                <span aria-hidden>→</span>
              </span>
            </button>
            {/* `.flow` 자체가 button이라 안에 중첩할 수 없다 — .bubble-tip과
             * 같은 방식으로 `.flow-wrap`의 형제로 둔다. */}
            <button
              ref={exampleTriggerRef}
              type="button"
              className="flow-aside-btn"
              onClick={() => setIsExampleOpen(true)}
            >
              결과물 예시 보기
            </button>
            <button
              ref={qaExampleTriggerRef}
              type="button"
              className="flow-aside-btn"
              onClick={() => setIsQaExampleOpen(true)}
            >
              문답 예시 보기
            </button>
            <Link href="/demo" className="flow-aside-btn">
              실제로 만들어진 결과 보기 →
            </Link>
          </div>

          <div className="flow-wrap">
            <button type="button" className="flow" onClick={() => startFlow("job_search")} disabled={pendingKind !== null}>
              <span className="flow-icon" aria-hidden>
                🔎
              </span>
              <span className="flow-title">취업 정보 검색</span>
              <span className="flow-desc">
                커리어 채우기에서 나눈 이야기를 바탕으로, 채용행사·공채 소식·직업훈련과정·강소기업까지 대화로 물어보고 한 번에 찾아요.
              </span>
              <span className="flow-go">
                {pendingKind === "job_search" ? "여는 중..." : "찾아보기"} <span aria-hidden>→</span>
              </span>
            </button>
          </div>
        </div>

        {error && (
          <p className="msg-error" style={{ maxWidth: 760, margin: "16px auto 0" }}>
            {error}
          </p>
        )}

        {!user ? (
          <p className="cta-note">
            가입 전에 먼저 써보세요 · 만든 문서는 <Link href="/register">회원가입</Link> 후 저장할 수 있어요
          </p>
        ) : user.is_guest ? (
          <p className="cta-note">
            체험 중이에요 · 만든 문서를 남기려면 <Link href="/register">회원가입</Link>이 필요해요
          </p>
        ) : null}
      </section>

      {/* 맞춤 공고는 로그인 사용자에게만. 프로필이 없어도 오류가 아니라 최신순 +
       * 안내로 내려오므로(FeedSection 참고) 세션 유무로는 가리지 않는다. */}
      {user ? (
        <FeedSection
          scope="recommended"
          icon="🎯"
          title="맞춤 공고"
          accessToken={accessToken}
          // 정렬이 마음에 안 들 때 바로 고치러 갈 수 있어야 한다 — 헤더 링크만
          // 있으면 "맞춤 정보를 고치는 곳"으로 읽히지 않았다(2026-09-10 피드백).
          // 게스트는 /archive가 회원가입 안내만 보여주므로 그리로 바로 보낸다.
          action={
            user.is_guest ? (
              <Link href="/register" className="section-aside">
                회원가입하고 맞춤 정보 설정하기 →
              </Link>
            ) : (
              <Link href="/archive" className="section-aside">
                맞춤 정보 수정 →
              </Link>
            )
          }
        />
      ) : (
        /* 로그아웃 방문자에게도 이 기능이 있다는 걸 알린다 — 안 보이면
           존재 자체를 모른다. */
        <section className="landing-section">
          <div className="landing-wrap">
            <div className="section-head">
              <h2>
                <span aria-hidden>🎯</span> 맞춤 공고
              </h2>
            </div>
            <p className="feed-notice">
              로그인하고 어떤 일을 찾고 있는지 적어두시면, 그 내용에 맞는 공고를 골라 여기에
              올려드려요. <Link href="/register">회원가입</Link> · <Link href="/login">로그인</Link>
            </p>
          </div>
        </section>
      )}

      {/* 맞춤 정책 — 대화로 알게 된 나이·거주지·학력 등과 정책 자격조건을 필드별로
       * 대조해, 조건이 모두 맞는 정책(교집합)을 먼저 올린다. 게스트도 속성이 쌓이고
       * /archive에서 고칠 수 있으므로 같은 링크를 준다. */}
      {/* 맞춤 직업훈련 — 거주지·희망지역에서 열리는 과정 먼저, 그 안에서 문답
       * 유사도순. 일반 섹션 3개(공고/지원 정책/직업훈련)와 짝을 맞췄다(2026-09-11). */}
      {user && (
        <>
          <FeedSection
            scope="recommended_policies"
            icon="🧩"
            title="맞춤 지원 정책"
            accessToken={accessToken}
            action={
              <Link href="/archive" className="section-aside">
                알게 된 정보 확인 →
              </Link>
            }
          />
          <FeedSection
            scope="recommended_trainings"
            icon="🛠️"
            title="맞춤 직업훈련"
            accessToken={accessToken}
            action={
              <Link href="/archive" className="section-aside">
                알게 된 정보 확인 →
              </Link>
            }
          />
        </>
      )}

      <FeedSection scope="jobs" icon="🧭" title="최신 공고" aside="고용24에서 모아왔어요" accessToken={accessToken} />

      {/* 온통청년 청년정책만. 고용24 훈련과정·구직자 프로그램은 예전엔 여기 섞였는데,
       * 훈련기관 이름만 적힌 카드가 정책 사이에 끼어 무엇인지 알아보기 어려워서
       * 아래 섹션으로 뺐다(2026-09-11). */}
      <FeedSection
        scope="policies"
        icon="🏛️"
        title="청년 지원 정책"
        aside="온통청년 · 최신 등록순"
        accessToken={accessToken}
      />

      <FeedSection
        scope="trainings"
        icon="🛠️"
        title="직업훈련·취업 프로그램"
        aside="고용24에서 모아왔어요"
        accessToken={accessToken}
      />

      {sessionsError && (
        <section className="landing-section">
          <div className="landing-wrap" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <p className="msg-error" style={{ flex: 1, minWidth: 240 }}>
              내 세션 목록을 불러오지 못했어요. {errorMessage(sessionsError)}
            </p>
            <button type="button" onClick={() => refetchSessions()}>
              다시 시도
            </button>
          </div>
        </section>
      )}

      {isExampleOpen && <ExampleDocumentModal onClose={closeExample} />}
      {isQaExampleOpen && <ExampleInterviewModal onClose={closeQaExample} />}
    </main>
  );
}

const RESUME_COLLAPSE_KEY = "feed-section-collapsed:resume";

/** 최근 세션으로 돌아가는 한 번의 클릭. 예전 자동 리다이렉트를 대체한다. */
function ResumeSection({ sessions }: { sessions: SessionRead[] }) {
  // FeedSection의 접기 상태와 같은 방식(브라우저 로컬 저장, 조용히 실패) — 이
  // 컴포넌트는 FeedSection을 안 쓰므로 별도로 둔다.
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(RESUME_COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });

  // 백엔드가 created_at 내림차순으로 주므로 앞에서 3개가 곧 최근 3개다.
  const recent = sessions.slice(0, 3);
  return (
    <section className="landing-section resume-section">
      <div className="landing-wrap">
        <div className="section-head">
          <h2>
            <span aria-hidden>↩️</span> 이어서 하기
          </h2>
          <div className="section-head-actions">
            {sessions.length > recent.length && (
              <span className="section-aside">전체 {sessions.length}개 · 대화 화면 사이드바에서 볼 수 있어요</span>
            )}
            <button
              type="button"
              className="section-collapse-toggle"
              aria-expanded={!collapsed}
              onClick={() => {
                const next = !collapsed;
                setCollapsed(next);
                try {
                  if (next) localStorage.setItem(RESUME_COLLAPSE_KEY, "1");
                  else localStorage.removeItem(RESUME_COLLAPSE_KEY);
                } catch {
                  // 저장 실패는 무시 — 이번 방문 동안만 상태가 안 남는다.
                }
              }}
            >
              {collapsed ? "펼치기 ▾" : "접기 ▴"}
            </button>
          </div>
        </div>
        {!collapsed && (
          <div className="resume-grid">
            {recent.map((session) => (
              <Link key={session.id} className="resume-card" href={`/sessions/${session.id}`}>
                <span className="resume-kind">{session.kind === "job_search" ? "🔎 취업 정보 검색" : "✍️ 커리어 채우기"}</span>
                <span className="resume-title">
                  {session.title ?? new Date(session.created_at).toLocaleDateString("ko-KR")}
                </span>
                <span className="resume-status">{sessionStatusLabel(session)}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

const NOTICE_MAIN_STYLE = {
  maxWidth: 480,
  margin: "120px auto",
  padding: "0 16px",
  textAlign: "center" as const,
  display: "flex",
  flexDirection: "column" as const,
  gap: 16,
};
