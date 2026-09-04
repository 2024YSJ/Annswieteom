import type { MetadataRoute } from "next";

const SITE_URL = "https://annswieteom.com";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/login`, changeFrequency: "monthly", priority: 0.5 },
    { url: `${SITE_URL}/register`, changeFrequency: "monthly", priority: 0.5 },
  ];
}
