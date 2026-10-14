import type { MetadataRoute } from "next";
import { getChanges, getDigestDates, getSeason } from "@/lib/api";
import { SITE_URL, titleHref } from "@/lib/types";

const BASE = SITE_URL;

/* Every route is real content and none of it is behind auth, so the whole thing
 * is listed. The per-title pages are the long tail worth indexing, each with a
 * synopsis, and they come from the newest season, already cached, rather than
 * from a request per title. Listed at their identity address, the one that does
 * not move when a title's merge winner does.
 *
 * "The whole thing" was not true until now: /schedule and /changes, two of the
 * five sections in the primary nav, had never been listed at all. Both render
 * real public content and both were reachable only by a crawler following a
 * link. The static routes are now in descending priority order so that the list
 * reads as the ranking it is, rather than the order things were added in.
 *
 * changeFrequency is how often each page's content actually turns over, not how
 * often it is visited: /schedule has a daily DAG behind it and a week window
 * that rolls, /browse and /changes move with the weekly run, /search is a form.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [season, digestDates, changes] = await Promise.all([
    getSeason(),
    getDigestDates(),
    /* lastModified for /changes is the newest fetch it compared, not today, and
       that is the one field here a crawler really uses. The page is deliberately
       a fixed week between runs rather than a shrinking one (see lib/api.ts), so
       "modified today" would be false on six days out of seven. Defensive,
       because a throw inside the sitemap is a 500 on /sitemap.xml and this is
       the only entry that would gain an upstream dependency. */
    getChanges().catch(() => null),
  ]);
  const now = new Date();
  const changedOn = changes?.until ? new Date(`${changes.until}T00:00:00Z`) : now;

  return [
    { url: `${BASE}/`, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${BASE}/browse`, lastModified: now, changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE}/schedule`, lastModified: now, changeFrequency: "daily", priority: 0.8 },
    { url: `${BASE}/digest`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    { url: `${BASE}/changes`, lastModified: changedOn, changeFrequency: "weekly", priority: 0.7 },
    { url: `${BASE}/scores`, lastModified: now, changeFrequency: "weekly", priority: 0.7 },
    { url: `${BASE}/search`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },
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
