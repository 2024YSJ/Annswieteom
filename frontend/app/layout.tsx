import type { Metadata } from "next";
import { IBM_Plex_Mono, Noto_Sans_KR } from "next/font/google";
import { AuthHeader } from "@/components/AuthHeader";
import { AuthProvider } from "@/lib/auth-context";
import { QueryProvider } from "@/lib/query-provider";
import "./globals.css";

// 사무적이되 딱딱하지 않은 톤 — 본문/제목은 Noto Sans KR, 상태값·날짜 같은 라벨은
// IBM Plex Mono. 둘 다 SIL Open Font License 1.1로, 상업적 이용·재배포·웹임베딩에
// 제약이 없다(폰트 파일 자체를 단독 상품으로 되파는 것만 금지 — 웹폰트로 쓰는 이
// 서비스와는 무관).
const fontSans = Noto_Sans_KR({
  variable: "--font-sans",
  weight: ["400", "500", "700", "900"],
  subsets: ["latin"],
});

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
    card: "summary",
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${fontSans.variable} ${fontMono.variable}`}>
      <body>
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
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
