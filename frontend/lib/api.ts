import "server-only";
import { cacheLife } from "next/cache";
import {
  ALL_SOURCES,
  API_BASE,
  ApiError,
  dedupeAnime,
  isAiring,
  isTv,
  jstDayKey,
  type Anime,
  type AnimeListResponse,
  type Digest,
  type Franchise,
  type Schedule,
  type ScheduledEpisode,
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
 * A season is two to four hundred titles. Fetching all of it once and deriving
 * every view locally fixes all three, and costs FEWER upstream requests than
 * passing views through — which matters because the API rate limits per IP and
 * every visitor shares this app's egress addresses.
 *
 * ONE SEASON, NEVER THE CATALOGUE
 * This used to fetch the whole catalogue and slice seasons out of it locally.
 * Fine at 481 titles (5 requests); at 2,755 after the backfill it was 28
 * requests and a 6.6s cold render, and five years of history would have gone
 * over the API's 60 a minute and taken the site down. Three things needed the
 * catalogue, and none now does:
 *   - the season list and the sources come from /catalogue, one small request;
 *   - a studio's other titles, the one question that spans seasons, is asked of
 *     the API directly (getStudio);
 *   - search results arrive with their own artwork and score.
 * So a page costs the season it shows (a request per 100 titles) plus the
 * summary, however many seasons the warehouse holds.
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

/** Every row an /anime query matches, all pages of it.
 *
 *  sort=title is load-bearing, not cosmetic: it is the only stable ordering the
 *  API offers, and without it paging returns a different subset per call. The
 *  first page says how many there are; the rest are fetched together, so a
 *  300-title season is two round trips rather than three in a row. */
async function fetchAll(filter: Record<string, unknown>): Promise<Anime[]> {
  const page = (offset: number) =>
    getJson<AnimeListResponse>(buildUrl("/anime", { ...filter, limit: PAGE, offset, sort: "title" }));
  const first = await page(0);
  const offsets: number[] = [];
  for (let offset = PAGE; offset < first.total; offset += PAGE) offsets.push(offset);
  const rest = await Promise.all(offsets.map(page));
  return [first, ...rest].flatMap((r) => r.items);
}

export type CatalogueSummary = {
  total: number;
  sources: string[];
  seasons: { season: string; season_year: number; count: number }[];
};

/** The catalogue's shape - its seasons, sources and size - without its titles.
 *  One small request; see GET /catalogue. */
export async function getCatalogueSummary(): Promise<CatalogueSummary> {
  "use cache";
  cacheLife("hours");
  return getJson<CatalogueSummary>(buildUrl("/catalogue"));
}

/** One season's rows. Keyed by the resolved season, so the bare URL and the
 *  newest season's own key share a single cache entry and a single fetch. */
async function getSeasonRows(season: string, year: number): Promise<Anime[]> {
  "use cache";
  cacheLife("hours");
  return fetchAll({ season, season_year: year });
}

/** Every title a studio worked on, in every season.
 *
 *  The one catalogue-wide question the site asks. Anime studios are long-tail -
 *  most make one show a season - so "what else did they make" answered within a
 *  season says "nothing" far too often; across the catalogue TMS Entertainment
 *  goes from 5 titles to 11. It used to be answered from a local copy of the
 *  whole catalogue; now the API filters. */
export async function getStudio(name: string): Promise<Anime[]> {
  "use cache";
  cacheLife("hours");
  return dedupeAnime(await fetchAll({ studio: name }));
}

export type ScheduleDay = { key: string; items: ScheduledEpisode[] };

/** The coming week's episodes, grouped by the day they air in Japan.
 *
 *  From AniList's airing schedule (GET /schedule), which is dated episode by
 *  episode. It replaced a schedule projected from MAL's weekly slots, which could
 *  only say when a show usually airs, never whether this week's episode does,
 *  and knew nothing of a show filed under an earlier season.
 *
 *  Grouped by Japan's calendar, deliberately, and this is the load-bearing
 *  decision. The airdate is a fact that is the same for everyone; the day it
 *  lands on is not, because many of these broadcast late at night Tokyo time and
 *  that is the previous evening across the Americas. Grouping by the reader's
 *  day would mean the server cannot render the page at all. So the columns are
 *  Japan's, stated as such, and each row carries the reader's own time beside
 *  it, added in the browser.
 *
 *  A calendar day, too: a 00:26 broadcast opens its day rather than closing the
 *  previous one. Japanese listings often bill that as the previous evening's
 *  late-night block, but the schedule reports a calendar day and re-mapping it
 *  here would be this site inventing a convention the data never stated.
 *
 *  The API starts the week at midnight today in Tokyo, so the day in progress is
 *  whole: this morning's episodes are still today's, marked as aired. */
export async function getSchedule(): Promise<{
  days: ScheduleDay[];
  episodes: number;
  shows: number;
  fetchedOn: string | null;
}> {
  "use cache";
  cacheLife("hours");

  const schedule = await getJson<Schedule>(buildUrl("/schedule", { days: 7 }));
  const first = Date.parse(schedule.start);
  const days = Array.from({ length: 7 }, (_, i) => {
    const key = jstDayKey(new Date(first + i * 86_400_000).toISOString());
    return { key, items: schedule.episodes.filter((e) => jstDayKey(e.airing_at) === key) };
  });
  const shows = new Set(schedule.episodes.map((e) => e.wb_id ?? `anilist:${e.anilist_id}`)).size;
  return { days, episodes: schedule.episodes.length, shows, fetchedOn: schedule.fetched_on };
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

  // Every source with a row in the catalogue, including one that never wins a
  // merge: MAL's studios and source material are on titles Kitsu wins.
  const { sources } = await getCatalogueSummary();
  return { live: [...sources].sort(), configured: ALL_SOURCES.length };
}

/** Seasons present in the warehouse, newest first. Derived, so a backfill of an
 *  older season appears here without any config change. */
export async function getSeasons(): Promise<SeasonRef[]> {
  "use cache";
  cacheLife("hours");

  const { seasons } = await getCatalogueSummary();
  // Newest first: by year, then by the industry's quarterly order rather than
  // alphabetically, which would put FALL before SPRING before SUMMER. The API
  // already orders them so; sorting again keeps that a guarantee of this
  // function rather than an assumption about another service.
  return seasons
    .map((s) => ({
      key: seasonKey(s.season, s.season_year),
      season: s.season,
      year: s.season_year,
      label: seasonLabel(s.season, s.season_year),
      count: s.count,
    }))
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

  const seasons = await getSeasons();
  const target = seasons.find((s) => s.key === key) ?? seasons[0];
  const rows = target ? await getSeasonRows(target.season, target.year) : [];
  const items = dedupeAnime(rows);
  const tv = items.filter(isTv);

  return {
    items,
    total: items.length,
    rawTotal: rows.length,
    scored: items.filter((a) => a.score_100 !== null).length,
    airing: items.filter(isAiring).length,
    withArtwork: items.filter((a) => a.poster_url).length,
    label: target?.label ?? null,
    key: target?.key ?? null,
    tvTotal: tv.length,
    tvScored: tv.filter((a) => a.score_100 !== null).length,
    tvAiring: tv.filter(isAiring).length,
    nonTvTotal: items.length - tv.length,
  };
}

/** Genre and format facets derived from the data, with real counts. Replaces a
 *  hardcoded list that had drifted out of sync — a chip that returns nothing is
 *  worse than no chip. Only genres with enough titles to be worth a click are
 *  offered; the long tail (98 distinct genres across 142 titles) is not a
 *  usable filter row. */
export type Facets = {
  genres: { value: string; count: number }[];
  formats: { value: string; count: number }[];
  services: { value: string; count: number }[];
  materials: { value: string; count: number }[];
};

export async function getFacets(seasonKeyParam?: string): Promise<Facets> {
  "use cache";
  cacheLife("hours");

  // Facets are per-season: offering a genre chip that matches nothing in the
  // season you are looking at is the same dead-control bug as the old hardcoded
  // "Sci-Fi", just arrived at from a different direction.
  const { items } = await getSeason(seasonKeyParam);
  return facetsOf(items);
}

/** The facets of whatever is being browsed: a season, or a studio's titles
 *  across every season. Chips have to describe what is on screen. */
export function facetsOf(items: Anime[]): Facets {
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

/** A title by its stable identity, or null if there is none. The API follows an
 *  identity that has since merged into another, so the title that comes back
 *  may carry a different wb_id from the one asked for - the page redirects to it.
 *
 *  A missing title is returned, not thrown. An error leaving a "use cache"
 *  function does not reliably arrive as the same class, so a thrown 404 was
 *  recognised on one render pass and not on another: the page showed the 404
 *  while its metadata took the error for a failure and served "Title" without a
 *  noindex. null is an ordinary cached value and means the same everywhere. */
export async function getTitle(wbId: string): Promise<Anime | null> {
  "use cache";
  cacheLife("hours");
  try {
    return await getJson<Anime>(buildUrl(`/anime/${encodeURIComponent(wbId)}`));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

/** A title's franchise, oldest first: see GET /anime/{wb_id}/franchise. Empty
 *  for a title in no franchise, which is most one-offs and every music video. */
export async function getFranchise(wbId: string): Promise<Franchise> {
  "use cache";
  cacheLife("hours");
  return getJson<Franchise>(buildUrl(`/anime/${encodeURIComponent(wbId)}/franchise`));
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
