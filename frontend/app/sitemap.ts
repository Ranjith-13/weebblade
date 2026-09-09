import type { MetadataRoute } from "next";
import { getDigestDates, getSeason } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? "https://weebblade.duckdns.org";

/* Every route is real content and none of it is behind auth, so the whole thing
 * is listed. The per-title pages are the long tail worth indexing — 142 of them,
 * each with a synopsis — and they come from the already-cached season rather
 * than from 142 extra upstream requests. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [season, digestDates] = await Promise.all([getSeason(), getDigestDates()]);
  const now = new Date();

  return [
    { url: `${BASE}/`, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${BASE}/browse`, lastModified: now, changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE}/search`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },
    { url: `${BASE}/digest`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    ...digestDates.map((d) => ({
      url: `${BASE}/digest/${d}`,
      lastModified: new Date(`${d}T00:00:00Z`),
      changeFrequency: "never" as const,
      priority: 0.7,
    })),
    ...season.items.map((a) => ({
      url: `${BASE}/anime/${a.source}/${a.source_id}`,
      lastModified: a.run_date ? new Date(`${a.run_date}T00:00:00Z`) : now,
      changeFrequency: "weekly" as const,
      priority: 0.5,
    })),
  ];
}
