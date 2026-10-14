import type { MetadataRoute } from "next";
import { getDigestDates, getSeason } from "@/lib/api";
import { SITE_URL, titleHref } from "@/lib/types";

const BASE = SITE_URL;

/* Every route is real content and none of it is behind auth, so the whole thing
 * is listed. The per-title pages are the long tail worth indexing, each with a
 * synopsis, and they come from the newest season, already cached, rather than
 * from a request per title. Listed at their identity address, the one that does
 * not move when a title's merge winner does. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [season, digestDates] = await Promise.all([getSeason(), getDigestDates()]);
  const now = new Date();

  return [
    { url: `${BASE}/`, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${BASE}/browse`, lastModified: now, changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE}/search`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },
    { url: `${BASE}/scores`, lastModified: now, changeFrequency: "weekly", priority: 0.7 },
    { url: `${BASE}/digest`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    ...digestDates.map((d) => ({
      url: `${BASE}/digest/${d}`,
      lastModified: new Date(`${d}T00:00:00Z`),
      changeFrequency: "never" as const,
      priority: 0.7,
    })),
    ...season.items.map((a) => ({
      url: `${BASE}${titleHref(a)}`,
      lastModified: a.run_date ? new Date(`${a.run_date}T00:00:00Z`) : now,
      changeFrequency: "weekly" as const,
      priority: 0.5,
    })),
  ];
}
