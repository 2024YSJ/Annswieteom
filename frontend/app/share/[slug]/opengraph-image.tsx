import { ImageResponse } from "next/og";

export const alt = "안 쉬었음 - 근거 있는 경력 문서";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface SharePreview {
  tone: string;
  representative_sentences: string[];
  evidence_grade_summary: Record<string, number>;
}

// next/og(Satori)의 기본 내장 폰트는 한글 글리프가 없다 — 한글을 그대로
// 넘기면 빈 사각형(tofu)으로 나온다. Noto Sans KR을 런타임에 한 번 받아
// 모듈 스코프에 캐시해 재사용한다(요청마다 다시 받지 않음). 네트워크가 막힌
// 배포 환경 등에서 이 요청이 실패해도 카드 자체는 계속 나가야 하므로(한글은
// 깨져 보이더라도) 실패를 삼킨다 — 카드 하나 못 예쁘게 그린다고 og:image
// 라우트 자체가 500이 되면 안 된다.
let notoSansKrPromise: Promise<ArrayBuffer | null> | null = null;

function loadNotoSansKR(): Promise<ArrayBuffer | null> {
  if (!notoSansKrPromise) {
    notoSansKrPromise = (async () => {
      try {
        const cssRes = await fetch("https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@700", {
          // 최신 브라우저 UA로 요청하면 Satori가 지원하지 않는 woff2만 내려온다 —
          // 구버전 UA로 위장해야 truetype 링크를 받는다(next/og 커뮤니티에 널리
          // 알려진 우회법).
          headers: { "User-Agent": "Mozilla/5.0 (Windows NT 6.1)" },
        });
        const css = await cssRes.text();
        const match = css.match(/src: url\(([^)]+)\) format\('(?:truetype|opentype)'\)/);
        if (!match) return null;
        const fontRes = await fetch(match[1]);
        return await fontRes.arrayBuffer();
      } catch {
        return null;
      }
    })();
  }
  return notoSansKrPromise;
}

export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;

  let preview: SharePreview | null = null;
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/share/${slug}`);
    if (res.ok) preview = await res.json();
  } catch {
    preview = null;
  }

  const fontData = await loadNotoSansKR();
  const headline = preview?.representative_sentences[0] ?? "근거 있는 경력 문서, 안 쉬었음";
  const recordBacked = preview?.evidence_grade_summary.record_backed ?? 0;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 64,
          background: "#fff5f5",
          fontFamily: fontData ? "Noto Sans KR" : undefined,
        }}
      >
        <div style={{ display: "flex", fontSize: 32, color: "#c53030", fontWeight: 700 }}>안 쉬었음</div>
        <div style={{ display: "flex", fontSize: 48, fontWeight: 700, color: "#1a1a1a", lineHeight: 1.4 }}>
          {headline}
        </div>
        <div style={{ display: "flex", fontSize: 28, color: "#4a5568" }}>
          🔗 기록물로 뒷받침된 문장 {recordBacked}개 · 근거 기반 경력 문서
        </div>
      </div>
    ),
    {
      ...size,
      fonts: fontData ? [{ name: "Noto Sans KR", data: fontData, style: "normal", weight: 700 }] : [],
    },
  );
}
