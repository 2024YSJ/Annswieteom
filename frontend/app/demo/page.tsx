"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { demoApi } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { errorMessage } from "@/lib/error-messages";
import { ChatBubble } from "@/components/ChatBubble";
import { LoadingNotice } from "@/components/LoadingNotice";
import { ParagraphSection } from "@/components/DocumentView";
import { GlobalTrustScoreboard } from "@/components/TrustScoreboard";

/** 원클릭 데모 — 로그인도, 인터뷰도 거치지 않고 실제로 확정된 결과물 하나를
 * 그대로 보여준다. 온라인 투표(인기상)나 심사 중 낯선 방문자가 "이게 실제로
 * 어떻게 동작하는지"를 30초~3분 안에 볼 수 있어야 한다는 요구에 대응한다.
 *
 * ParagraphSection에 편집 콜백을 하나도 넘기지 않는다 — 그러면 모든 편집
 * 버튼이 자동으로 숨겨진다(DocumentView.tsx 참고). 별도의 read-only 렌더링
 * 로직을 새로 만들지 않고, 실제 결과 화면(ResultSection.tsx)과 배지·근거
 * 표시 로직을 완전히 공유한다.
 */
export default function DemoPage() {
  const { data: document, isLoading, error } = useQuery({
    queryKey: queryKeys.demoDocument(),
    queryFn: () => demoApi.getDocument(),
    retry: false,
  });

  return (
    <main style={{ maxWidth: 760, margin: "40px auto", padding: "0 16px" }}>
      <section style={{ marginBottom: 24, textAlign: "center" }}>
        <span className="hero-eyebrow">로그인 없이 보는 실제 결과물</span>
        <h1 style={{ margin: "8px 0" }}>이렇게 만들어져요</h1>
        <p className="hero-sub">
          아래는 실제로 인터뷰를 마치고 확정(FINAL)된 문서예요 — 문장마다 어떤 근거로
          나왔는지, 근거가 없는 문장은 없는 그대로 표시돼요.
        </p>
      </section>

      <div style={{ marginBottom: 16 }}>
        <GlobalTrustScoreboard />
      </div>

      {isLoading && (
        <ChatBubble side="left" variant="card">
          <LoadingNotice />
        </ChatBubble>
      )}

      {error && !document && (
        <ChatBubble side="left" variant="card">
          <p style={{ color: "var(--danger)", margin: 0 }}>
            지금은 데모를 볼 수 없어요. {errorMessage(error)}
          </p>
        </ChatBubble>
      )}

      {document && (
        <ChatBubble side="left" variant="card" label="완성된 커리어 내러티브 (데모)">
          {document.paragraphs
            .slice()
            .sort((a, b) => a.order_index - b.order_index)
            .map((paragraph, index, all) => (
              <ParagraphSection
                key={paragraph.id}
                paragraph={paragraph}
                isFirst={index === 0}
                isLast={index === all.length - 1}
                disabled
              />
            ))}
        </ChatBubble>
      )}

      <p style={{ textAlign: "center", marginTop: 24 }}>
        <Link href="/">← 내 이야기로 직접 만들어보기</Link>
      </p>
    </main>
  );
}
