import "server-only";
import { cacheLife } from "next/cache";
import {
  API_BASE,
  ApiError,
  dedupeAnime,
  isTv,
  type Anime,
  type AnimeListResponse,
  type Digest,
} from "./types";

/* Server-only data layer. The client-safe pieces (types, API_BASE, pure
 * helpers) live in ./types so the browser bundle never pulls `cacheLife` in.
 * The "server-only" import above turns that mistake into a build error naming
 * this file rather than the confusing Pages-Router error it produces otherwise.
 *
 * WHY THIS FETCHES THE WHOLE SEASON AT ONCE
 * The old shape passed every filter, sort and page straight through to the API.
 * That was one upstream request per distinct view, and it inherited three
 * problems that could not be fixed downstream:
 *
 *   1. PAGINATION IS UNSTABLE under the default sort. `score_desc` orders by
 *      `score_100 DESC NULLS LAST`, and 103 of 142 rows are NULL — so the tie
 *      block has no deterministic order and LIMIT/OFFSET slices a differently
 *      shuffled result each time. Measured: three identical two-page fetches
 *      returned 126, 116 and 122 distinct titles, differing by 30-40 ids. Rows
 *      were served twice while others were never served at all. Every page of
 *      the old /browse was a different random subset of the catalogue.
 *      `sort=title` orders by COALESCE(title_english, title_romaji) and is
 *      stable: 142 rows, 142 distinct ids, identical across runs. That is why
 *      the fetch below pins the sort and reorders locally afterwards.
 *   2. `popularity` is a rank — lower is more popular — and the only sort the
 *      API offers is `popularity_desc`, i.e. least-popular-first.
 *   3. The genre filter list had to be hardcoded, and had drifted: "Sci-Fi"
 *      matched nothing because the real tag is "Science Fiction".
 *
 * The season is 142 titles. Fetching all of it once and deriving
 * every view locally fixes all three, and costs FEWER upstream requests than
 * before (two, per cache period, total) — which matters because the API rate
 * limits per IP and every visitor shares this app's egress addresses.
 */

const PAGE = 100; // API caps `limit` at 100

function buildUrl(path: string, params: Record<string, unknown> = {}): string {
  const url = new URL(path, API_BASE);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new ApiError(res.status, `${res.status} from ${url}`);
  return res.json() as Promise<T>;
}

export type Season = {
  items: Anime[];
  /** Distinct titles after dedupe — the honest count. */
  total: number;
  /** Rows the API returned before dedupe. Surfaced so the UI can be candid
   *  about the discrepancy rather than silently papering over it. */
  rawTotal: number;
  scored: number;
  airing: number;
  withArtwork: number;
  label: string | null;
  /* TV-scoped counts. The site defaults to TV because a fifth of a season is
     music videos that are never scored, so whole-season figures describe the
     ingest rather than the anime. Both are kept: the front page states the full
     catalogue AND what share of it is TV, instead of quietly showing one and
     labelling it the other. */
  tvTotal: number;
  tvScored: number;
  tvAiring: number;
  nonTvTotal: number;
};

/** The whole current season, deduped. Everything else derives from this. */
export async function getSeason(): Promise<Season> {
  "use cache";
  cacheLife("hours");

  // sort=title is load-bearing, not cosmetic: it is the only stable ordering
  // the API offers, and without it paging returns a different subset per call.
  const first = await getJson<AnimeListResponse>(buildUrl("/anime", { limit: PAGE, sort: "title" }));
  const rows = [...first.items];
  for (let offset = PAGE; offset < first.total; offset += PAGE) {
    const next = await getJson<AnimeListResponse>(
      buildUrl("/anime", { limit: PAGE, offset, sort: "title" }),
    );
    rows.push(...next.items);
  }

  const items = dedupeAnime(rows);
  const lead = items.find((a) => a.season && a.season_year);
  const tv = items.filter(isTv);

  return {
    items,
    total: items.length,
    rawTotal: first.total,
    scored: items.filter((a) => a.score_100 !== null).length,
    airing: items.filter((a) => a.status === "current").length,
    withArtwork: items.filter((a) => a.poster_url).length,
    label: lead?.season
      ? `${lead.season.charAt(0)}${lead.season.slice(1).toLowerCase()} ${lead.season_year}`
      : null,
    tvTotal: tv.length,
    tvScored: tv.filter((a) => a.score_100 !== null).length,
    tvAiring: tv.filter((a) => a.status === "current").length,
    nonTvTotal: items.length - tv.length,
  };
}

/** Genre and format facets derived from the data, with real counts. Replaces a
 *  hardcoded list that had drifted out of sync — a chip that returns nothing is
 *  worse than no chip. Only genres with enough titles to be worth a click are
 *  offered; the long tail (98 distinct genres across 142 titles) is not a
 *  usable filter row. */
export async function getFacets(): Promise<{
  genres: { value: string; count: number }[];
  formats: { value: string; count: number }[];
  services: { value: string; count: number }[];
}> {
  "use cache";
  cacheLife("hours");

  const { items } = await getSeason();
  const tally = (values: (string | null)[]) => {
    const map = new Map<string, number>();
    for (const v of values) {
      if (!v) continue;
      map.set(v, (map.get(v) ?? 0) + 1);
    }
    return [...map.entries()]
      .map(([value, count]) => ({ value, count }))
      .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
  };

  return {
    genres: tally(items.flatMap((a) => a.genres)).filter((g) => g.count >= 4),
    formats: tally(items.map((a) => a.format)),
    // "Where can I actually watch this" is the question the old build could not
    // answer at all. Derived like every other facet, so a service that stops
    // appearing upstream stops appearing here rather than becoming a dead chip.
    services: tally(items.flatMap((a) => a.streaming_services ?? [])),
  };
}

export async function getAnime(source: string, sourceId: string): Promise<Anime> {
  "use cache";
  cacheLife("hours");
  return getJson<Anime>(
    buildUrl(`/anime/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`),
  );
}

export async function getLatestDigest(): Promise<Digest | null> {
  "use cache";
  cacheLife("hours");
  try {
    return await getJson<Digest>(buildUrl("/digest/latest"));
  } catch (err) {
    // 503 is the documented "no digest generated yet" state, not a failure —
    // the home page renders an honest empty state rather than an error.
    if (err instanceof ApiError && err.status === 503) return null;
    throw err;
  }
}

export async function getDigestDates(): Promise<string[]> {
  "use cache";
  cacheLife("hours");
  try {
    return await getJson<string[]>(buildUrl("/digest"));
  } catch {
    return [];
  }
}

export async function getDigest(runDate: string): Promise<Digest | null> {
  "use cache";
  cacheLife("hours");
  try {
    return await getJson<Digest>(buildUrl(`/digest/${encodeURIComponent(runDate)}`));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
