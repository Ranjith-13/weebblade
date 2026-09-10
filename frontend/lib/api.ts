import "server-only";
import { cacheLife } from "next/cache";
import {
  ALL_SOURCES,
  API_BASE,
  ApiError,
  dedupeAnime,
  hasBroadcastSlot,
  isTv,
  SCHEDULE_DAYS,
  slotMinutes,
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

/** Quarterly order, not alphabetical - FALL sorts last in the year, not first. */
const SEASON_ORDER = ["WINTER", "SPRING", "SUMMER", "FALL"];

/* A season we offer must be a season we actually ingested.
 *
 * The list is derived from the data, which is right, but the data can hold
 * seasons that were never fetched as seasons: MAL's season endpoint returns
 * long-running shows still on air, each tagged to its debut, so one Summer 2026
 * fetch deposited single titles under Fall 1969, Winter 1995 and 28 others. The
 * switcher offered all 30 - entries no one wants, listing one title each,
 * crowding out the two real seasons.
 *
 * Fixed at the source too (MAL rows that start elsewhere are no longer ingested);
 * this is the guard that keeps a switcher built from data honest if another
 * source does the same thing. The threshold has a wide margin in both directions:
 * real seasons measured 119 and 227 titles, the largest artifact was 3. */
const MIN_SEASON_TITLES = 10;

export function seasonKey(season: string, year: number): string {
  return `${year}-${season}`;
}

export function seasonLabel(season: string, year: number): string {
  return `${season.charAt(0)}${season.slice(1).toLowerCase()} ${year}`;
}

export type SeasonRef = {
  key: string;
  season: string;
  year: number;
  label: string;
  count: number;
};

export type Season = {
  items: Anime[];
  /** Which season this is, and its key for links. Null only if nothing is tagged. */
  key: string | null;
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

/** Every title the warehouse holds, across every season. One fetch, cached, and
 *  the per-season views are derived from it: the whole catalogue is a few
 *  hundred rows, so slicing locally is cheaper than a request per season. */
export async function getCatalogue(): Promise<Anime[]> {
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
  return dedupeAnime(rows);
}

export type ScheduleDay = { day: string; items: Anime[] };

/** The week's broadcast schedule, grouped by the day it airs in Japan.
 *
 *  Only titles that are airing AND carry a slot. A schedule of finished shows is
 *  not a schedule, and 40% of the airing titles have no slot at all — the page
 *  says so rather than quietly showing a shorter week than the season has.
 *
 *  Grouped by JST, deliberately, and this is the load-bearing decision. The slot
 *  is a fact that is the same for everyone; the day it lands on is not, because
 *  most of these broadcast after midnight Tokyo time and that is the previous
 *  evening across the Americas. Grouping by the viewer's day would mean the
 *  server cannot render the page at all. So the columns are Japan's, stated as
 *  such, and each row carries the viewer's own time beside it (`LocalSlot`) —
 *  the same split `NextAiring` already uses. */
export async function getSchedule(seasonKeyParam?: string): Promise<{
  days: ScheduleDay[];
  slotted: number;
  airingWithoutSlot: number;
}> {
  "use cache";
  cacheLife("hours");

  const { items } = await getSeason(seasonKeyParam);
  const airing = items.filter((a) => a.status === "current");
  const slotted = airing.filter(hasBroadcastSlot);

  const days = SCHEDULE_DAYS.map((day) => ({
    day,
    items: slotted
      .filter((a) => a.broadcast_day?.trim().toLowerCase() === day)
      .sort((a, b) => (slotMinutes(a) ?? 0) - (slotMinutes(b) ?? 0)),
  }));

  return { days, slotted: slotted.length, airingWithoutSlot: airing.length - slotted.length };
}

/** Which sources actually reached the warehouse, and how many the pipeline runs.
 *
 *  Derived rather than stated, for the same reason the genre facets are: a
 *  hardcoded answer drifts silently. AniList and Jikan have been down upstream
 *  for this project's whole life and MAL joined later, so any number written into
 *  the copy was wrong within weeks — and was, in two places, for days. */
export async function getSources(): Promise<{ live: string[]; configured: number }> {
  "use cache";
  cacheLife("hours");

  const items = await getCatalogue();
  const live = [...new Set(items.map((a) => a.source))].sort();
  return { live, configured: ALL_SOURCES.length };
}

/** Seasons present in the warehouse, newest first. Derived, so a backfill of an
 *  older season appears here without any config change. */
export async function getSeasons(): Promise<SeasonRef[]> {
  "use cache";
  cacheLife("hours");

  const items = await getCatalogue();
  const byKey = new Map<string, SeasonRef>();
  for (const a of items) {
    if (!a.season || !a.season_year) continue;
    const key = seasonKey(a.season, a.season_year);
    const existing = byKey.get(key);
    if (existing) existing.count += 1;
    else
      byKey.set(key, {
        key,
        season: a.season,
        year: a.season_year,
        label: seasonLabel(a.season, a.season_year),
        count: 1,
      });
  }
  // Newest first: by year, then by the industry's quarterly order rather than
  // alphabetically, which would put FALL before SPRING before SUMMER.
  return [...byKey.values()]
    .filter((s) => s.count >= MIN_SEASON_TITLES)
    .sort(
      (a, b) => b.year - a.year || SEASON_ORDER.indexOf(b.season) - SEASON_ORDER.indexOf(a.season),
    );
}

/** One season, deduped, with its counts. Defaults to the newest season present.
 *  Everything the season pages render derives from this. */
export async function getSeason(key?: string): Promise<Season> {
  "use cache";
  cacheLife("hours");

  const all = await getCatalogue();
  const seasons = await getSeasons();
  const target = seasons.find((s) => s.key === key) ?? seasons[0];
  const items = target
    ? all.filter(
        (a) => a.season === target.season && a.season_year === target.year,
      )
    : all;
  const tv = items.filter(isTv);

  return {
    items,
    total: items.length,
    rawTotal: all.length,
    scored: items.filter((a) => a.score_100 !== null).length,
    airing: items.filter((a) => a.status === "current").length,
    withArtwork: items.filter((a) => a.poster_url).length,
    label: target?.label ?? null,
    key: target?.key ?? null,
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
export async function getFacets(seasonKeyParam?: string): Promise<{
  genres: { value: string; count: number }[];
  formats: { value: string; count: number }[];
  services: { value: string; count: number }[];
  materials: { value: string; count: number }[];
}> {
  "use cache";
  cacheLife("hours");

  // Facets are per-season: offering a genre chip that matches nothing in the
  // season you are looking at is the same dead-control bug as the old hardcoded
  // "Sci-Fi", just arrived at from a different direction.
  const { items } = await getSeason(seasonKeyParam);
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
    /* What a title was adapted from, which MAL supplies and Kitsu does not. It
       makes a good facet where studios do not: 11 values spread across the
       season (61 original, 35 manga, 27 light novel) against 135 distinct
       studios of which exactly two have four titles. Studio is a filter reached
       from a title, not a row of chips — see the `studio` param in /browse. */
    materials: tally(items.map((a) => a.source_material)),
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
