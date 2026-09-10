"use client";

import type { ReactNode } from "react";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { feedApi, type FeedItemRead, type FeedRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";

/** 캐시가 비어 서버가 방금 수집을 예약한 상태(`is_warming`)에서만 쓰는 폴링 간격.
 * 수집은 응답 이후 BackgroundTask로 도는 구조라, 최초 1회는 빈 응답이 나온 뒤
 * 잠시 기다렸다 다시 물어보는 것 말고는 방법이 없다. */
const WARMING_POLL_MS = 4000;

export type FeedScope = "policies" | "jobs" | "recommended";

/** `fallback_reason`별 안내. 셋을 하나로 뭉치면 안 되는 이유는 서버 스키마 주석에
 * 적힌 그대로다 — 문답을 처음 남긴 사용자는 `preparing`을 반드시 한 번 지나가므로
 * 거기에 고장 안내를 띄우면 정상 동작에 오경보를 내는 셈이 된다. */
function fallbackNotice(feed: FeedRead): { text: string; tone: "info" | "warn" } | null {
  switch (feed.fallback_reason) {
    case "no_profile":
      return {
        text: "공백기 채우기로 문답을 남기면, 그 내용에 맞는 공고를 골라 여기에 올려드려요. 아래 최신 공고부터 둘러보셔도 좋아요.",
        tone: "info",
      };
    case "preparing":
      return {
        text: "맞춤 순서를 준비하고 있어요. 잠시 후 다시 오시면 문답에 맞춰 골라드릴게요. 그동안은 아래 최신 공고를 보실 수 있어요.",
        tone: "info",
      };
    case "ai_unavailable":
      return { text: "AI 서버가 수리 중이라 맞춤 정렬을 못 하고 있어요. 아래 최신 공고는 그대로 보실 수 있어요.", tone: "warn" };
    default:
      return null;
  }
}

function FeedCard({ item }: { item: FeedItemRead }) {
  // detail_url이 없는 카테고리가 실제로 있다(워크넷 일부). 그럴 땐 링크가 아니라
  // 평범한 카드로 그린다 — 눌리는 것처럼 보이는데 아무 일도 없으면 안 된다.
  const body = (
    <>
      <div className="feed-card-tags">
        <span className="feed-tag">{item.category_label}</span>
        <span className="feed-tag feed-tag-muted">{item.source_label}</span>
      </div>
      <span className="feed-card-title">{item.title}</span>
      {item.subtitle && <span className="feed-card-subtitle">{item.subtitle}</span>}
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
  /** `recommended`는 로그인 필수. 나머지는 없어도 되고, 있으면 그대로 실어 보낸다. */
  accessToken: string | null;
  limit?: number;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.feed(scope),
    queryFn: () => {
      if (scope === "policies") return feedApi.policies({ limit }, accessToken);
      if (scope === "jobs") return feedApi.jobs({ limit }, accessToken);
      return feedApi.recommendedJobs({ limit }, accessToken!);
    },
    enabled: scope !== "recommended" || !!accessToken,
    // 캐시가 데워지는 동안에만 폴링한다. 다 차면 refetchInterval이 false가 되어
    // 멈추므로, 메인 화면을 열어둔 채로 계속 요청이 나가지 않는다.
    refetchInterval: (query) => (query.state.data?.is_warming ? WARMING_POLL_MS : false),
    retry: false,
  });

  const notice = data ? fallbackNotice(data) : null;
  // 맞춤 공고가 개인화되지 않았을 때는 목록을 아예 안 그린다. 그 응답은 바로
  // 아래 "최신 공고"와 **글자 그대로 같은 목록**이라, 그리면 같은 카드가 화면에
  // 두 번 나온다. 이 자리에는 왜 아직 맞춤이 아닌지와 다음에 뭘 하면 되는지만
  // 남긴다.
  const suppressed = scope === "recommended" && !!data && !data.personalized;

  return (
    <section className="landing-section">
      <div className="landing-wrap">
        <div className="section-head">
          <h2>
            <span aria-hidden>{icon}</span> {title}
            {data?.personalized && <span className="feed-badge">맞춤</span>}
          </h2>
          {action ?? (aside && <span className="section-aside">{aside}</span>)}
        </div>

        {notice && !suppressed && (
          <p className={notice.tone === "warn" ? "msg-error feed-notice" : "feed-notice"}>{notice.text}</p>
        )}

        {error ? (
          <p className="msg-error">{errorMessage(error)}</p>
        ) : isLoading ? (
          <p className="feed-empty">불러오는 중...</p>
        ) : suppressed && notice ? (
          <p className={notice.tone === "warn" ? "msg-error" : "feed-callout"}>{notice.text}</p>
        ) : data && data.items.length > 0 ? (
          <div className="feed-grid">
            {data.items.map((item) => (
              <FeedCard key={item.id} item={item} />
            ))}
          </div>
        ) : data?.is_warming ? (
          <p className="feed-empty">최신 정보를 모으고 있어요. 잠시만 기다려주세요...</p>
        ) : (
          <p className="feed-empty">
            지금은 보여드릴 항목이 없어요. 대화로 직접 찾아보시려면{" "}
            <Link href="/">취업 정보 검색</Link>을 이용해보세요.
          </p>
        )}
      </div>
    </section>
  );
}
