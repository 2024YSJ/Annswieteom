"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import { useInfiniteQuery } from "@tanstack/react-query";
import Link from "next/link";
import { feedApi, type FeedItemRead, type FeedRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";

/** 캐시가 비어 서버가 방금 수집을 예약한 상태(`is_warming`)에서만 쓰는 폴링 간격.
 * 수집은 응답 이후 BackgroundTask로 도는 구조라, 최초 1회는 빈 응답이 나온 뒤
 * 잠시 기다렸다 다시 물어보는 것 말고는 방법이 없다. */
const WARMING_POLL_MS = 4000;

/** 섹션 접기/펼치기는 순수 이 브라우저만의 편의 상태라 서버에 저장하지 않는다
 * (다른 기기·다른 사용자에게 영향 없어야 함) — 접근 불가 환경(프라이빗 창 등)에서도
 * 화면이 정상 동작해야 하므로 읽기/쓰기 모두 조용히 실패한다. */
function readCollapsed(scope: FeedScope): boolean {
  try {
    return localStorage.getItem(`feed-section-collapsed:${scope}`) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(scope: FeedScope, collapsed: boolean): void {
  try {
    if (collapsed) localStorage.setItem(`feed-section-collapsed:${scope}`, "1");
    else localStorage.removeItem(`feed-section-collapsed:${scope}`);
  } catch {
    // 저장 실패는 무시 — 이번 방문 동안만 상태가 안 남을 뿐 기능은 그대로 동작한다.
  }
}

export type FeedScope =
  | "policies"
  | "trainings"
  | "jobs"
  | "recommended"
  | "recommended_policies"
  | "recommended_trainings";

const PERSONALIZED_SCOPES: ReadonlySet<FeedScope> = new Set([
  "recommended",
  "recommended_policies",
  "recommended_trainings",
]);

/** `fallback_reason`별 안내. 셋을 하나로 뭉치면 안 되는 이유는 서버 스키마 주석에
 * 적힌 그대로다 — 문답을 처음 남긴 사용자는 `preparing`을 반드시 한 번 지나가므로
 * 거기에 고장 안내를 띄우면 정상 동작에 오경보를 내는 셈이 된다. */
function fallbackNotice(feed: FeedRead): { text: string; tone: "info" | "warn" } | null {
  switch (feed.fallback_reason) {
    case "no_profile":
      return {
        text: "커리어 채우기로 문답을 남기면, 그 내용에 맞는 공고를 골라 여기에 올려드려요. 아래 최신 공고부터 둘러보셔도 좋아요.",
        tone: "info",
      };
    case "preparing":
      return {
        text: "맞춤 순서를 준비하고 있어요. 잠시 후 다시 오시면 문답에 맞춰 골라드릴게요. 그동안은 아래 최신 공고를 보실 수 있어요.",
        tone: "info",
      };
    case "ai_unavailable":
      return { text: "AI 서버가 수리 중이라 맞춤 정렬을 못 하고 있어요. 아래 최신 공고는 그대로 보실 수 있어요.", tone: "warn" };
    case "no_attributes":
      return {
        text: "대화에서 나이·사는 곳·희망 지역 같은 정보를 알게 되면, 나에게 맞는 것부터 골라드려요. 맞춤 정보 화면에서 직접 적어두셔도 돼요.",
        tone: "info",
      };
    default:
      return null;
  }
}

/** 맞춤 정책 카드의 조건 일치 표시. "왜 이게 위에 있지?"에 답하는 자리다 —
 * 교집합(all)과 합집합(some)을 구분해 보여주지 않으면 사용자는 순서의 의미를 모른다.
 * 공고·훈련은 "티어"(all/some) 개념이 없어(match_tier가 항상 "none") 카운트
 * pill 대신, 계산된 각 근거(matched_labels)를 라벨별로 개별 pill로 보여준다 —
 * 정책과 똑같이 눈에 띄지만, "N개 중 일치"가 아니라 "왜 관련 있는지"를 그대로
 * 나열하는 것이라 표현 방식이 다르다.*/
function MatchBadge({ item }: { item: FeedItemRead }) {
  const matched = item.matched_labels ?? [];
  if (item.match_tier === "all") {
    return <span className="feed-match">조건 {matched.length}개 모두 일치</span>;
  }
  if (item.match_tier === "some") {
    return <span className="feed-match feed-match-some">조건 {matched.length}개 일치</span>;
  }
  if (matched.length > 0) {
    return (
      <>
        {matched.map((label) => (
          <span key={label} className="feed-match feed-match-signal">
            {label}
          </span>
        ))}
      </>
    );
  }
  return null;
}

function FeedCard({ item }: { item: FeedItemRead }) {
  // detail_url이 없는 카테고리가 실제로 있다(고용24 일부). 그럴 땐 링크가 아니라
  // 평범한 카드로 그린다 — 눌리는 것처럼 보이는데 아무 일도 없으면 안 된다.
  const matched = item.matched_labels ?? [];
  const unmet = item.unmet_labels ?? [];
  const body = (
    <>
      <div className="feed-card-tags">
        <MatchBadge item={item} />
        <span className="feed-tag">{item.category_label}</span>
        <span className="feed-tag feed-tag-muted">{item.source_label}</span>
      </div>
      <span className="feed-card-title">{item.title}</span>
      {item.subtitle && <span className="feed-card-subtitle">{item.subtitle}</span>}
      {/* 정책만 평문으로도 다시 나열한다 — "조건 N개 일치" 카운트 pill 옆에 실제
          어떤 조건인지 풀어써야 의미가 있다. 공고·훈련은 이제 위 태그 줄의
          개별 pill이 이미 같은 정보를 보여주므로 평문을 중복해서 안 그린다. */}
      {item.match_tier !== "none" && matched.length > 0 && (
        <span className="feed-card-match">✓ {matched.join(" · ")}</span>
      )}
      {item.match_tier === "some" && unmet.length > 0 && (
        <span className="feed-card-unmet">확인 필요: {unmet.slice(0, 2).join(" · ")}</span>
      )}
      {item.meta_lines.length > 0 && (
        <span className="feed-card-meta">{item.meta_lines.join(" · ")}</span>
      )}
    </>
  );

  if (!item.detail_url) {
    return <div className="feed-card">{body}</div>;
  }
  return (
    <a className="feed-card feed-card-link" href={item.detail_url} target="_blank" rel="noopener noreferrer">
      {body}
      <span className="feed-card-go" aria-hidden>
        자세히 보기 ↗
      </span>
    </a>
  );
}

export function FeedSection({
  scope,
  title,
  icon,
  aside,
  accessToken,
  action,
  limit = 6,
}: {
  scope: FeedScope;
  title: string;
  icon: string;
  aside?: string;
  /** 섹션 헤더 오른쪽 액션(예: "맞춤 정보 수정"). aside 대신 쓰인다. */
  action?: ReactNode;
  /** `recommended`·`recommended_policies`는 로그인 필수. 나머지는 없어도 되고, 있으면 그대로 실어 보낸다. */
  accessToken: string | null;
  limit?: number;
}) {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(scope));

  const { data, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: queryKeys.feed(scope),
    queryFn: ({ pageParam }) => {
      const options = { limit, offset: pageParam };
      if (scope === "policies") return feedApi.policies(options, accessToken);
      if (scope === "trainings") return feedApi.trainings(options, accessToken);
      if (scope === "jobs") return feedApi.jobs(options, accessToken);
      if (scope === "recommended_policies") return feedApi.recommendedPolicies(options, accessToken!);
      if (scope === "recommended_trainings") return feedApi.recommendedTrainings(options, accessToken!);
      return feedApi.recommendedJobs(options, accessToken!);
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const seen = lastPage.offset + lastPage.items.length;
      // `total`은 서버가 이 정렬로 실제 도달 가능한 행 수를 준다(개인화면
      // 임베딩이 있는 행만). 그래서 여기서 그냥 믿어도 된다.
      return seen < lastPage.total ? seen : undefined;
    },
    enabled: !PERSONALIZED_SCOPES.has(scope) || !!accessToken,
    // 캐시가 데워지는 동안에만 폴링한다. 다 차면 refetchInterval이 false가 되어
    // 멈추므로, 메인 화면을 열어둔 채로 계속 요청이 나가지 않는다.
    refetchInterval: (query) => (query.state.data?.pages[0]?.is_warming ? WARMING_POLL_MS : false),
    retry: false,
  });

  // 상태(is_warming/personalized/fallback_reason)는 첫 페이지 기준으로 읽는다 —
  // 뒤 페이지는 같은 목록의 이어지는 조각일 뿐이다.
  const feed = data?.pages[0];
  const items = data?.pages.flatMap((page) => page.items) ?? [];
  const notice = feed ? fallbackNotice(feed) : null;
  // 맞춤 공고가 개인화되지 않았을 때는 목록을 아예 안 그린다. 그 응답은 바로
  // 아래 "최신 공고"와 **글자 그대로 같은 목록**이라, 그리면 같은 카드가 화면에
  // 두 번 나온다. 이 자리에는 왜 아직 맞춤이 아닌지와 다음에 뭘 하면 되는지만
  // 남긴다.
  // 맞춤 정책도 같다 — 속성이 없으면 아래 "청년 지원 정책"과 같은 최신순 목록이다.
  const suppressed = PERSONALIZED_SCOPES.has(scope) && !!feed && !feed.personalized;

  return (
    <section className="landing-section">
      <div className="landing-wrap">
        <div className="section-head">
          <h2>
            <span aria-hidden>{icon}</span> {title}
            {feed?.personalized && <span className="feed-badge">맞춤</span>}
          </h2>
          <div className="section-head-actions">
            {action ?? (aside && <span className="section-aside">{aside}</span>)}
            <button
              type="button"
              className="section-collapse-toggle"
              aria-expanded={!collapsed}
              onClick={() => {
                const next = !collapsed;
                setCollapsed(next);
                writeCollapsed(scope, next);
              }}
            >
              {collapsed ? "펼치기 ▾" : "접기 ▴"}
            </button>
          </div>
        </div>

        {!collapsed && (
          <>
            {notice && !suppressed && (
              <p className={notice.tone === "warn" ? "msg-error feed-notice" : "feed-notice"}>{notice.text}</p>
            )}

            {error ? (
              <p className="msg-error">{errorMessage(error)}</p>
            ) : isLoading ? (
              <p className="feed-empty">불러오는 중...</p>
            ) : suppressed && notice ? (
              <p className={notice.tone === "warn" ? "msg-error" : "feed-callout"}>{notice.text}</p>
            ) : items.length > 0 ? (
              <>
                <div className="feed-grid">
                  {items.map((item) => (
                    <FeedCard key={item.id} item={item} />
                  ))}
                </div>
                {hasNextPage && (
                  <div className="feed-more">
                    <button type="button" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
                      {isFetchingNextPage ? "불러오는 중..." : "더보기"}
                    </button>
                  </div>
                )}
              </>
            ) : feed?.is_warming ? (
              <p className="feed-empty">최신 정보를 모으고 있어요. 잠시만 기다려주세요...</p>
            ) : (
              <p className="feed-empty">
                지금은 보여드릴 항목이 없어요. 대화로 직접 찾아보시려면{" "}
                <Link href="/">취업 정보 검색</Link>을 이용해보세요.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}
