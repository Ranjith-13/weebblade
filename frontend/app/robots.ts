import type { MetadataRoute } from "next";

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? "https://weebblade.duckdns.org";

/* /search is disallowed rather than indexed: results are generated per query
 * against a rate-limited endpoint (20/min per IP), so letting a crawler walk
 * query strings would spend that budget on pages with no standalone value. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: "/search" }],
    sitemap: `${BASE}/sitemap.xml`,
  };
}
