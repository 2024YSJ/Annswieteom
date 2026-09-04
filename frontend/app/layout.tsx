import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AuthHeader } from "@/components/AuthHeader";
import { AuthProvider } from "@/lib/auth-context";
import { QueryProvider } from "@/lib/query-provider";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
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
    <html lang="ko" className={`${geistSans.variable} ${geistMono.variable}`}>
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
