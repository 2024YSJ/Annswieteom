import type { MetadataRoute } from "next";

const SITE_URL = "https://annswieteom.com";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // 로그인 후에만 의미 있는 세션 상세 페이지는 검색엔진이 굳이 색인할 필요가 없다.
        disallow: ["/sessions/"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
