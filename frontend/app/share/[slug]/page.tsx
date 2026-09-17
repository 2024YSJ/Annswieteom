"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { shareApi } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { errorMessage } from "@/lib/error-messages";
import { ChatBubble } from "@/components/ChatBubble";
import { LoadingNotice } from "@/components/LoadingNotice";

const EVIDENCE_GRADE_LABELS: Record<string, string> = {
  record_backed: "🔗 기록물로 뒷받침됨",
  self_reported: "· 본인 진술",
  unsupported: "· 인용된 근거 없음",
};

/** 공유 링크로 들어온 방문자가 보는 공개 페이지 — 로그인 없이, 세션 소유자가
 * 아니어도 볼 수 있다. 백엔드 SharePreviewRead가 애초에 대표 문장 1~2개와
 * 근거 등급 개수만 주므로, 여기서 원문·근거 링크·개인정보를 보여줄 방법
 * 자체가 없다. */
export default function SharePage() {
  const { slug } = useParams<{ slug: string }>();
  const { data: preview, isLoading, error } = useQuery({
    queryKey: queryKeys.sharePreview(slug),
    queryFn: () => shareApi.getPublic(slug),
    retry: false,
  });

  return (
    <main style={{ maxWidth: 640, margin: "40px auto", padding: "0 16px" }}>
      <section style={{ marginBottom: 24, textAlign: "center" }}>
        <span className="hero-eyebrow">누군가 공유한 경력 문서 미리보기</span>
        <h1 style={{ margin: "8px 0" }}>안 쉬었음</h1>
        <p className="hero-sub">문장마다 근거를 확인하며 만든 경력기술서예요.</p>
      </section>

      {isLoading && (
        <ChatBubble side="left" variant="card">
          <LoadingNotice />
        </ChatBubble>
      )}

      {error && !preview && (
        <ChatBubble side="left" variant="card">
          <p style={{ color: "var(--danger)", margin: 0 }}>
            이 공유 링크를 찾을 수 없어요. {errorMessage(error)}
          </p>
        </ChatBubble>
      )}

      {preview && (
        <ChatBubble side="left" variant="card" label={`톤: ${preview.tone}`}>
          {preview.representative_sentences.map((text, i) => (
            <p key={i} style={{ fontSize: 16 }}>
              {text}
            </p>
          ))}

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 12, fontSize: 12, color: "var(--muted-text)" }}>
            {Object.entries(preview.evidence_grade_summary)
              .filter(([, count]) => count > 0)
              .map(([grade, count]) => (
                <span key={grade}>
                  {EVIDENCE_GRADE_LABELS[grade] ?? grade} × {count}
                </span>
              ))}
          </div>
        </ChatBubble>
      )}

      <p style={{ textAlign: "center", marginTop: 24 }}>
        <Link href="/">나도 근거 있는 경력 문서 만들어보기 →</Link>
      </p>
    </main>
  );
}
