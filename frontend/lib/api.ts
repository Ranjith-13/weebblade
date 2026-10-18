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
  plainPunctuation,
  startedSeason,
  type ChangeFeed,
  type Anime,
  type AnimeListResponse,
  type DailyScores,
  type Digest,
  type Franchise,
  type Schedule,
  type ScheduledEpisode,
  type ScoreSettling,
  type SimilarTitle,
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
 *      `score_100 DESC NULLS LAST`, and in the one-season catalogue this was
 *      measured on, 103 of 142 rows were NULL — so the tie
 *      block has no deterministic order and LIMIT/OFFSET slices a differently
 *      shuffled result each time. Measured: three identical two-page fetches
 *      returned 126, 116 and 122 distinct titles, differing by 30-40 ids. Rows
 *      were served twice while others were never served at all. Every page of
 *      the old /browse was a different random subset of the catalogue.
 *      `sort=title` orders by COALESCE(title_english, title_romaji) and is
 *      stable: 142 rows, 142 distinct ids then, identical across runs. That is why
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

/* THE API AND THIS APP BOTH REDEPLOY ON A PUSH, AND THEY RACE.
 *
 * Render replaces a free container rather than draining it, so for a minute or
 * so around a deploy its proxy answers 502 with nothing behind it. Both this
 * app's CI build and its Vercel build prerender against the live API at exactly
 * that moment, and a single 502 took the whole build down twice in two days -
 * the second time on the commit that caused the deploy it was racing.
 *
 * So a status that means "ask again in a moment" is asked again. 502 and 504
 * are the proxy with no healthy instance behind it. Network-level failures too,
 * which arrive as a thrown TypeError rather than a response.
 *
 * NOT 503, deliberately. From get_db that means the warehouse is not on disk
 * (backend/app/db.py), which does not clear in seconds and is retried where it
 * can actually be fixed - the API re-fetches its own warehouse before serving
 * (backend/app/warehouse.ensure_warehouse). Retrying it here would only make
 * every page slower on the day the API has nothing to serve.
 *
 * The budget is about 23 seconds, which is proportionate rather than arbitrary:
 * this app already waits around 32 seconds for a sleeping container to wake,
 * with no fetch timeout at all. It is not enough to ride out a long outage, and
 * it is not meant to be - a build that waits that long should go red, because a
 * Vercel deploy made at that moment would have failed too.
 *
 * This file is server-only, so none of it runs in a reader's browser. /search
 * does its own fetch from the client (app/search/SearchClient.tsx) and is
 * untouched: it spends the visitor's own rate-limit budget, where a retry would
 * be spending someone else's. */
const RETRY_STATUS = new Set([502, 504]);
const RETRY_BACKOFF_MS = [2_000, 6_000, 15_000];

async function getJson<T>(url: string): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    const last = attempt >= RETRY_BACKOFF_MS.length;
    try {
      // THE _retry PARAMETER IS LOAD-BEARING AND LOOKS LIKE DEBRIS, so: Next
      // memoises fetch by URL within a render pass, and a retry of the exact
      // same URL is answered from that memo without a request leaving the
      // process. Measured against a stub that failed the first three calls -
      // without this the build made ONE request per caller and died; with it,
      // /catalogue was asked at 0s, 2s and 6s and the third answered. `cache:
      // "no-store"` does not defeat the memo; a different URL does. The API
      // ignores unknown query parameters, and seeing _retry=2 in its log is a
      // fair description of what happened.
      const attempted = attempt === 0
        ? url
        : `${url}${url.includes("?") ? "&" : "?"}_retry=${attempt}`;
      const res = await fetch(attempted, { headers: { Accept: "application/json" } });
      if (res.ok) return (await res.json()) as T;
      // Thrown rather than returned so the one exit for a failure is the same
      // whatever went wrong; the catch below decides whether it is final.
      throw new ApiError(res.status, `${res.status} from ${url}`);
    } catch (err) {
      const retryable = err instanceof ApiError ? RETRY_STATUS.has(err.status) : true;
      if (last || !retryable) throw err;
    }
    await new Promise((resolve) => setTimeout(resolve, RETRY_BACKOFF_MS[attempt]));
  }
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
  /** A season the sources already list that has not started yet. The pipeline
   *  fetches the next season months ahead, so the newest season on file is not
   *  the season a reader means by "this season". */
  upcoming: boolean;
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
  seasons: { season: string; season_year: number; count: number; upcoming?: boolean }[];
  /** How often two sources that both scored a title print different numbers.
   *  Absent on a warehouse built before this existed, or one carrying a single
   *  source, which is a state rather than a fault. */
  contested?: { rated_by_two: number; differ: number } | null;
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

/** The week's changes, as the pipeline recorded them (GET /changes).
 *
 *  One request, already grouped and titled by the API: a change several sources
 *  reported is one entry naming them all. The window ends at the newest fetch
 *  compared rather than today, so between weekly runs this is a fixed week
 *  rather than a shrinking one. */
export async function getChanges(): Promise<ChangeFeed> {
  "use cache";
  cacheLife("hours");
  return getJson<ChangeFeed>(buildUrl("/changes"));
}

/** What a score does over its life (GET /scores/settling).
 *
 *  The one read on this site that is longitudinal rather than cross-sectional,
 *  and the one that could not be derived here at any price: the answer is drawn
 *  from every dated snapshot the warehouse holds - 66,098 rows on 2026-10-14 -
 *  and this app is built never to fetch more than a season. So the API answers
 *  the question, the way /catalogue and studio= do.
 *
 *  One request for the whole page, cached for hours like everything else. It is
 *  the most expensive query the API runs (about 150 ms warm, three passes over
 *  the history), which is another reason not to split it across sections.
 *
 *  null rather than a throw, for two states that are not failures. 503 is the
 *  documented "no warehouse yet". 404 is an API older than this page, and that
 *  one is new: the site and the API became separately deployed artifacts in
 *  October 2026, so a build of this app can reach a container that has not
 *  restarted on the commit that added the endpoint. Throwing took the whole
 *  production build down when /scores was first added, which is a silly way to
 *  lose a deploy over one page. */
export async function getScoreSettling(): Promise<ScoreSettling | null> {
  "use cache";
  cacheLife("hours");
  try {
    return await getJson<ScoreSettling>(buildUrl("/scores/settling"));
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 503)) return null;
    throw err;
  }
}

/** One title's score as asked every morning: GET /scores/daily/{wb_id}.
 *
 *  THE DENSE HALF OF /scores. Everything else here reads a weekly snapshot, so
 *  a score that moves on Tuesday and again on Friday is one move and a score
 *  that moves and moves back is none. The daily AniList status check already
 *  asks about exactly the airing titles, so these readings cost no new fetch.
 *
 *  An endpoint rather than a field on the title, which is the opposite call
 *  from score_history: it reads a dated glob that gains a file every morning,
 *  so attaching it would make every title page pay a growing scan for an
 *  answer only airing titles have. Ask for it where isAiring() is true.
 *
 *  Null rather than a throw on 404 or 503, like getScoreSettling: the site and
 *  the API deploy separately, so a build can reach a container serving a
 *  warehouse published before this existed, and a block is not worth a page.
 */
export async function getDailyScores(wbId: string): Promise<DailyScores | null> {
  "use cache";
  cacheLife("hours");
  try {
    return await getJson<DailyScores>(
      buildUrl(`/scores/daily/${encodeURIComponent(wbId)}`),
    );
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 503)) return null;
    throw err;
  }
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

/** The episode each title has this week, by identity.
 *
 *  Derived from the schedule rather than fetched per title, and that is the
 *  whole reason this is cheap enough to put on a grid. /anime carries an
 *  `upcoming_episodes` field but leaves it empty on list rows - it is filled
 *  only on a single title - so a plate showing an airdate would otherwise mean
 *  an API change and a join across every row of every season. /schedule already
 *  returns the week keyed by wb_id (118 of 124 episodes carry one), costs one
 *  small request, and is cached for hours like everything else here.
 *
 *  The earliest entry per title, which is this week's episode rather than
 *  strictly the next one: the window opens at midnight today in Tokyo, so for a
 *  few hours after a broadcast the episode it names has just aired. Saying "ep
 *  3, 15 Oct" is true either way; it is only the word "next" that would not be,
 *  which is why the plate does not use it. */
export type WeekEpisode = { episode: number | null; airing_at: string };

export async function getWeekEpisodes(): Promise<Record<string, WeekEpisode>> {
  "use cache";
  cacheLife("hours");

  const { days } = await getSchedule();
  const out: Record<string, WeekEpisode> = {};
  for (const day of days) {
    for (const episode of day.items) {
      if (!episode.wb_id || episode.episode === null) continue;
      const held = out[episode.wb_id];
      if (!held || episode.airing_at < held.airing_at) {
        out[episode.wb_id] = { episode: episode.episode, airing_at: episode.airing_at };
      }
    }
  }
  return out;
}

/** Which sources actually reached the warehouse, and how many the pipeline runs.
 *
 *  Derived rather than stated, for the same reason the genre facets are: a
 *  hardcoded answer drifts silently. AniList was down upstream for most of this
 *  project's life, MAL joined later, and Jikan stopped existing - its public API
 *  was discontinued on 1 October 2026 - so any number written into the copy was
 *  wrong within weeks, and was, in two places, for days. */
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
      upcoming: s.upcoming ?? false,
    }))
    .filter((s) => s.count >= MIN_SEASON_TITLES)
    .sort(
      (a, b) => b.year - a.year || SEASON_ORDER.indexOf(b.season) - SEASON_ORDER.indexOf(a.season),
    );
}

/** One season, deduped, with its counts. Everything the season pages render
 *  derives from this.
 *
 *  Defaults to the newest season that has STARTED, not the newest on file. The
 *  pipeline fetches the next season as soon as the sources list it, months
 *  ahead, and defaulting to that would put a season with nothing aired and
 *  almost nothing scored on the front page and in every bare /browse. An asked
 *  for season is served whether it has started or not - that is the point of
 *  having it. */
export async function getSeason(key?: string): Promise<Season> {
  "use cache";
  cacheLife("hours");

  const seasons = await getSeasons();
  const started = startedSeason(seasons);
  const target = seasons.find((s) => s.key === key) ?? started;
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
 *  offered; the long tail (131 distinct genres in Summer 2026, 218 across the
 *  catalogue, as of 2026-09-14) is not a usable filter row. */
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

/** Titles nearest this one by what they are about (GET /anime/{wb_id}/similar).
 *
 *  A second request for a title page, like the franchise, and for the same
 *  reason: it is a block at the bottom that the page is complete without, so it
 *  streams in its own boundary rather than holding up the title.
 *
 *  Cheap at the far end - the neighbours are computed when the warehouse is
 *  built and stored as rows, so the API joins rather than scanning 6,359
 *  vectors (47 ms measured). Empty is an ordinary answer: a title with no
 *  synopsis has no neighbours by design. */
export async function getSimilar(wbId: string): Promise<SimilarTitle[]> {
  "use cache";
  cacheLife("hours");
  const body = await getJson<{ results: SimilarTitle[] }>(
    buildUrl(`/anime/${encodeURIComponent(wbId)}/similar`),
  );
  return body.results;
}

/** A title's franchise, oldest first: see GET /anime/{wb_id}/franchise. Empty
 *  for a title in no franchise, which is most one-offs and every music video. */
export async function getFranchise(wbId: string): Promise<Franchise> {
  "use cache";
  cacheLife("hours");
  return getJson<Franchise>(buildUrl(`/anime/${encodeURIComponent(wbId)}/franchise`));
}

/* THE DIGEST IS REPUNCTUATED ON THE WAY OUT, in both getters, which is the only
 * place it passes through. See plainPunctuation in ./types: it is the one block
 * of text on this site nobody wrote, and the run of 2026-10-12 carried five
 * em-dashes, 26 non-breaking hyphens and 13 narrow no-break spaces - against a
 * design rule that bans the first by name. Punctuation only, never words, so
 * "written by an LLM from this week's ingested data" stays true.
 *
 * Here rather than at the two <Markdown> call sites because the home page
 * splits the content into paragraphs before rendering it, so a fix at the
 * component would have to be applied twice and would miss the next consumer. */
export async function getLatestDigest(): Promise<Digest | null> {
  "use cache";
  cacheLife("hours");
  try {
    return readable(await getJson<Digest>(buildUrl("/digest/latest")));
  } catch (err) {
    // 503 is the documented "no digest generated yet" state, not a failure —
    // the home page renders an honest empty state rather than an error.
    if (err instanceof ApiError && err.status === 503) return null;
    throw err;
  }
}

function readable(digest: Digest): Digest {
  return { ...digest, content: plainPunctuation(digest.content) };
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
    return readable(await getJson<Digest>(buildUrl(`/digest/${encodeURIComponent(runDate)}`)));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
