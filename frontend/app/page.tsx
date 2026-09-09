"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { sessionApi, type SessionKind, type SessionRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { sessionStatusLabel } from "@/lib/session-routes";
import { useSessionsList } from "@/lib/use-sessions-list";
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
  const { data: sessions, isLoading: sessionsLoading, error: sessionsError, refetch: refetchSessions } = useSessionsList();
  const [error, setError] = useState<string | null>(null);
  const [pendingKind, setPendingKind] = useState<SessionKind | null>(null);

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

  const hasSessions = !!sessions && sessions.length > 0;

  return (
    <main className="landing">
      {hasSessions ? (
        <section className="hero hero-compact">
          <h1>{user?.nickname}님, 이어서 해볼까요?</h1>
          <p className="hero-sub">공백기라 불린 시간을, 근거 있는 커리어 문서로.</p>
        </section>
      ) : (
        <section className="hero">
          <span className="hero-eyebrow">공백기 정리 · 취업 정보</span>
          <h1>우리는 쉬지 않았습니다</h1>
          <p className="hero-sub">
            공백기라 불린 시간을, <b>근거 있는 커리어 문서</b>로.
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
              <span className="flow-title">공백기 채우기</span>
              <span className="flow-desc">그동안 한 일을 대화로 짚어보고, 이력서에 그대로 쓸 수 있는 STAR 문장으로 정리해요.</span>
              <span className="flow-go">
                {pendingKind === "gap_fill" ? "시작하는 중..." : hasSessions ? "새로 시작하기" : "시작하기"}{" "}
                <span aria-hidden>→</span>
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

      {/* 맞춤 공고는 로그인 사용자에게만. 프로필이 없어도 오류가 아니라 최신순 +
       * 안내로 내려오므로(FeedSection 참고) 세션 유무로는 가리지 않는다. */}
      {user && (
        <FeedSection
          scope="recommended"
          icon="🎯"
          title="맞춤 공고"
          aside="문답 기록에 맞춰 정렬해요"
          accessToken={accessToken}
        />
      )}

      <FeedSection scope="jobs" icon="🧭" title="최신 공고" aside="워크넷에서 모아왔어요" accessToken={accessToken} />

      <FeedSection
        scope="policies"
        icon="🏛️"
        title="청년 지원 정책"
        aside="최신 등록순"
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

      {/* 결과물이 뭔지 아직 모르는 사람에게만 보여준다. 이미 세션이 있는
       * 사용자에게는 자기 문서가 있으므로 예시가 자리만 차지한다. */}
      {!hasSessions && !sessionsLoading && <ExampleDocument />}
    </main>
  );
}

/** 최근 세션으로 돌아가는 한 번의 클릭. 예전 자동 리다이렉트를 대체한다. */
function ResumeSection({ sessions }: { sessions: SessionRead[] }) {
  // 백엔드가 created_at 내림차순으로 주므로 앞에서 3개가 곧 최근 3개다.
  const recent = sessions.slice(0, 3);
  return (
    <section className="landing-section resume-section">
      <div className="landing-wrap">
        <div className="section-head">
          <h2>
            <span aria-hidden>↩️</span> 이어서 하기
          </h2>
          {sessions.length > recent.length && (
            <span className="section-aside">전체 {sessions.length}개 · 대화 화면 사이드바에서 볼 수 있어요</span>
          )}
        </div>
        <div className="resume-grid">
          {recent.map((session) => (
            <Link key={session.id} className="resume-card" href={`/sessions/${session.id}`}>
              <span className="resume-kind">{session.kind === "job_search" ? "🔎 취업 정보 검색" : "✍️ 공백기 채우기"}</span>
              <span className="resume-title">
                {session.title ?? new Date(session.created_at).toLocaleDateString("ko-KR")}
              </span>
              <span className="resume-status">{sessionStatusLabel(session)}</span>
            </Link>
          ))}
        </div>
      </div>
    </section>
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
