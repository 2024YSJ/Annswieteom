import type { Metadata } from "next";
import { IBM_Plex_Mono } from "next/font/google";
import { AuthHeader } from "@/components/AuthHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { AuthProvider } from "@/lib/auth-context";
import { QueryProvider } from "@/lib/query-provider";
import "./globals.css";

// 본문/제목은 Pretendard Variable, 상태값·날짜 같은 라벨은 IBM Plex Mono.
// 둘 다 SIL Open Font License 1.1로, 상업적 이용·재배포·웹임베딩에 제약이 없다
// (폰트 파일 자체를 단독 상품으로 되파는 것만 금지 — 웹폰트로 쓰는 이 서비스와는
// 무관).
//
// Pretendard는 구글 폰트에 없어서 next/font로 못 받고, jsDelivr의 동적 서브셋
// CSS를 <link>로 붙인다(아래 RootLayout). 한글 웹폰트를 통째로 받는 대신 실제
// 쓰인 글자만 잘라 받는 빌드라, Noto Sans KR 4종(수백 KB)을 next/font로 받던
// 이전보다 오히려 가볍다. CDN이 죽으면 Malgun Gothic(윈도우 기본)으로 떨어진다.
const PRETENDARD_CSS =
  "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css";

const fontMono = IBM_Plex_Mono({
  variable: "--font-mono",
  weight: ["500", "600"],
  subsets: ["latin"],
});

const SITE_URL = "https://annswieteom.com";
const SITE_NAME = "안 쉬었음";
const SITE_DESCRIPTION =
  "공백기 동안의 활동을 AI와의 대화로 정리해서, 사용자가 직접 확인한 사실만으로 커리어 내러티브 문서를 만들어주는 서비스.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: SITE_NAME,
    template: `%s | ${SITE_NAME}`,
  },
  description: SITE_DESCRIPTION,
  keywords: ["안 쉬었음", "공백기", "커리어 내러티브", "이력서", "경력기술서", "구직"],
  alternates: {
    canonical: SITE_URL,
  },
  openGraph: {
    type: "website",
    locale: "ko_KR",
    url: SITE_URL,
    siteName: SITE_NAME,
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
  },
  twitter: {
    // opengraph-image.png(1200x630)이 생기면서 정사각 썸네일을 쓰는 "summary"는
    // 카드를 잘라 보여준다 — 가로형 이미지에 맞는 큰 카드로 바꾼다.
    card: "summary_large_image",
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={fontMono.variable}>
      <body>
        {/* React 19의 스타일시트 지원 — precedence를 주면 트리 어디에 있든
         * <head>로 끌어올려지고, 로드될 때까지 렌더를 막아 폰트 깜빡임이 없다
         * (docs/01-app/01-getting-started/11-css.md). Metadata API로는 못 넣는
         * 태그라서 이렇게 직접 렌더한다. */}
        <link rel="stylesheet" href={PRETENDARD_CSS} precedence="default" />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "WebSite",
              name: SITE_NAME,
              url: SITE_URL,
              description: SITE_DESCRIPTION,
              inLanguage: "ko",
            }),
          }}
        />
        <QueryProvider>
          <AuthProvider>
            <AuthHeader />
            {children}
            <SiteFooter />
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
