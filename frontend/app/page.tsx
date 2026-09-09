"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { sessionApi, type SessionKind } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { useSessionsList } from "@/lib/use-sessions-list";
import { LoadingNotice } from "@/components/LoadingNotice";

export default function Home() {
  const router = useRouter();
  const { user, accessToken, isLoading, guestLogin } = useAuth();
  const { data: sessions, isLoading: sessionsLoading, error: sessionsError, refetch: refetchSessions } = useSessionsList();
  const [error, setError] = useState<string | null>(null);
  const [pendingKind, setPendingKind] = useState<SessionKind | null>(null);
  // Guards against firing the redirect twice (React 19 dev-mode double-invoked
  // effects).
  const hasRedirectedRef = useRef(false);

  useEffect(() => {
    // Only resumes an existing session — creating a brand-new one now always
    // goes through the explicit 공백기 채우기/취업 정보 검색 cards below instead
    // of silently defaulting to gap-fill, so a user with zero sessions falls
    // through to the landing render below rather than being redirected here.
    if (isLoading || !user || sessionsLoading || !sessions || sessions.length === 0 || hasRedirectedRef.current) return;
    hasRedirectedRef.current = true;
    // Sessions come back newest-first (backend orders by created_at desc) —
    // landing here should resume the most recent one, matching the sidebar's
    // own ordering.
    router.replace(`/sessions/${sessions[0].id}`);
  }, [isLoading, user, sessionsLoading, sessions, router]);

  // 첫 화면에서 곧바로 서비스로 들어가는 경로. 로그인 여부와 무관하게 카드 한
  // 번 누르면 (필요하면 게스트 로그인까지 해서) 세션을 만들고 대화 화면으로
  // 넘어간다.
  //
  // 게스트 로그인과 세션 생성이 한 클릭 안에서 순차로 일어나는 게 핵심이다.
  // 예전에는 "게스트로 시작" 버튼이 로그인만 하고, 세션 생성은 위 effect가
  // 따로 했는데 — 갓 만들어진 같은 게스트를 두고 둘이 경쟁해 세션이 두 개
  // 생기는 일이 있었다(2026-09-05 프로덕션 버그). 지금은 effect가 세션을
  // 만들지 않으므로 경쟁할 상대 자체가 없다.
  async function startFlow(kind: SessionKind) {
    if (pendingKind) return;
    setError(null);
    setPendingKind(kind);
    try {
      const token = accessToken ?? (await guestLogin());
      const session = await sessionApi.create(token, { kind });
      // 성공 시엔 pendingKind를 일부러 안 푼다 — 화면이 넘어가는 동안 카드가
      // 계속 비활성으로 남아 중복 클릭을 막는다.
      router.replace(`/sessions/${session.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setPendingKind(null);
    }
  }

  // A logged-in visitor whose session list failed to load (not just still
  // loading) used to fall through to the loading branch below forever — the
  // redirect effect above only ever checks `!sessions`, never the query's
  // error state, so nothing there could break the wait. Handle it explicitly
  // with a retry instead of leaving a dead end with no escape.
  if (user && sessionsError) {
    return (
      <main style={NOTICE_MAIN_STYLE}>
        <p className="msg-error">{errorMessage(sessionsError)}</p>
        <button type="button" onClick={() => refetchSessions()} style={{ alignSelf: "center" }}>
          다시 시도
        </button>
      </main>
    );
  }

  // 아직 로그인 상태를 확인 중이거나, 이미 세션이 있어 위 effect가 리다이렉트를
  // 처리하는 중이면 로딩 화면만 보여준다. 랜딩은 (1) 로그아웃 방문자와
  // (2) 로그인했지만 세션이 하나도 없는 사용자 — 두 경우에만 그린다.
  const showLanding = !isLoading && (!user || (!sessionsLoading && sessions?.length === 0));
  if (!showLanding) {
    return (
      <main style={NOTICE_MAIN_STYLE}>
        <LoadingNotice />
      </main>
    );
  }

  return (
    <main className="landing">
      <section className="hero">
        <span className="hero-eyebrow">공백기 정리 · 취업 정보</span>
        <h1>우리는 쉬지 않았습니다</h1>
        <p className="hero-sub">
          공백기라 불린 시간을, <b>근거 있는 커리어 문서</b>로.
        </p>
      </section>

      <section className="flows">
        <div className="flow-grid">
          <div className="flow-wrap">
            {!user && <div className="bubble-tip">가입 없이 바로 체험</div>}
            <button type="button" className="flow" onClick={() => startFlow("gap_fill")} disabled={pendingKind !== null}>
              <span className="flow-icon" aria-hidden>
                ✍️
              </span>
              <span className="flow-title">공백기 채우기</span>
              <span className="flow-desc">그동안 한 일을 대화로 짚어보고, 이력서에 그대로 쓸 수 있는 STAR 문장으로 정리해요.</span>
              <span className="flow-go">
                {pendingKind === "gap_fill" ? "시작하는 중..." : "시작하기"} <span aria-hidden>→</span>
              </span>
            </button>
          </div>

          <div className="flow-wrap">
            <button type="button" className="flow" onClick={() => startFlow("job_search")} disabled={pendingKind !== null}>
              <span className="flow-icon" aria-hidden>
                🔎
              </span>
              <span className="flow-title">취업 정보 검색</span>
              <span className="flow-desc">채용행사, 공채 소식, 직업훈련과정, 강소기업까지 대화로 물어보고 한 번에 찾아요.</span>
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

      <ExampleDocument />
    </main>
  );
}

/** 결과물이 어떻게 생겼는지 먼저 보여주는 섹션. 실제 생성 문서를 그대로 옮긴 게
 * 아니라 예시 텍스트지만, 구조(STAR 4단락 + 문장별 근거 태그)와 근거 태그의
 * 종류는 실제 confirmed_facts.source_type 세 가지와 일치시켰다. */
function ExampleDocument() {
  return (
    <section className="landing-section">
      <div className="landing-wrap">
        <div className="section-head">
          <h2>
            <span aria-hidden>📄</span> 이렇게 만들어집니다
          </h2>
          <span className="section-aside">모든 문장에 근거가 붙습니다</span>
        </div>

        <article className="doc-preview">
          <div className="doc-bar">
            <span className="doc-bar-title">데이터 분석 직무 경력기술서 — 2025.03 ~ 2025.09</span>
            <span className="doc-bar-meta">TONE: 담백 · v2</span>
          </div>

          <div className="doc-body">
            {EXAMPLE_STAR.map((block) => (
              <div key={block.label} className="doc-star">
                <span className="doc-star-label">{block.label}</span>
                <p>{block.text}</p>
                <div className="doc-evidence">
                  {block.evidence.map((e) => (
                    <span key={e.text} className={e.cited ? "chip chip-cite" : "chip"}>
                      {e.text}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="doc-foot">
            <span aria-hidden>🔒</span>
            <span>
              <b>없는 경력은 만들지 않습니다.</b> 직접 &ldquo;맞다&rdquo;고 확인한 사실에만 문장이 붙습니다.
            </span>
          </div>
        </article>
      </div>
    </section>
  );
}

const EXAMPLE_STAR = [
  {
    label: "Situation",
    text: "퇴사 후 6개월간 데이터 분석 직무로의 전환을 준비하며, 통계와 SQL 기초를 처음부터 다시 쌓아야 하는 상황이었습니다.",
    evidence: [
      { text: "사용자 확인 · 공백기 6개월", cited: false },
      { text: "사용자 확인 · 직무 전환 목표", cited: false },
    ],
  },
  {
    label: "Task",
    text: "실무에서 바로 쓸 수 있는 수준까지 SQL·Python 분석 역량을 끌어올리고, 결과물을 외부에 공개해 검증받는 것을 목표로 삼았습니다.",
    evidence: [{ text: "사용자 확인 · 학습 목표", cited: false }],
  },
  {
    label: "Action",
    text: "매주 공공데이터를 하나씩 골라 분석 노트를 작성해 블로그에 21편을 연재했고, SQLD 자격증을 취득했으며, 스터디 5인의 코드 리뷰를 진행했습니다.",
    evidence: [
      { text: "기록물 인용 · 블로그 21편", cited: true },
      { text: "기록물 인용 · SQLD 합격증", cited: true },
      { text: "사용자 확인 · 스터디 운영", cited: false },
    ],
  },
  {
    label: "Result",
    text: "연재 글의 누적 조회수는 1만 2천 회를 넘었고, 마지막 프로젝트는 실제 지원 포트폴리오로 제출해 서류 전형을 통과했습니다.",
    evidence: [
      { text: "기록물 인용 · 블로그 통계", cited: true },
      { text: "사용자 수정 · 서류 통과", cited: false },
    ],
  },
];

const NOTICE_MAIN_STYLE = {
  maxWidth: 480,
  margin: "120px auto",
  padding: "0 16px",
  textAlign: "center" as const,
  display: "flex",
  flexDirection: "column" as const,
  gap: 16,
};
