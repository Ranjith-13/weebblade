/* Client-safe half of the API layer: types, the base URL, and pure formatting
 * helpers. Kept separate from lib/api.ts because that module imports
 * `cacheLife`, which is server-only - the search UI runs in the browser and
 * importing anything from api.ts there drags the whole server module into the
 * client bundle and fails the build. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://weebblade.duckdns.org";

/** Mirrors backend/app/schemas.py:Anime. Almost everything is nullable because
 *  the sources genuinely disagree on what they provide - Kitsu carries no studios
 *  or source material, MAL no slug, cover art, trailer or streaming link. Coverage
 *  per field is in frontend/CLAUDE.md, "Sparse fields". */
export type Anime = {
  source: string;
  source_id: string;
  mal_id: number | null;
  title_romaji: string | null;
  title_english: string | null;
  title_native: string | null;
  poster_url: string | null;
  synopsis: string | null;
  format: string | null;
  status: string | null;
  season: string | null;
  season_year: number | null;
  episodes: number | null;
  duration_minutes: number | null;
  genres: string[];
  studios: string[];
  source_material: string | null;
  score_100: number | null;
  /** A RANK, not a count: lower is more popular. Never sort this descending. */
  popularity: number | null;
  /** Also a rank, lower is better: 64% of a season, 91% of its TV (2026-09-14). */
  rating_rank: number | null;
  /** The one interest signal on every title (100%), where score_100 covers 44%
   *  of a season and 88% of its TV (2026-09-14). favourites is each source's own
   *  count on its own site, mostly 0, and is never rendered. */
  user_count: number | null;
  favourites: number | null;
  age_rating: string | null;
  /** Sparse enhancements. cover_url is on 32% of a season and trailer_id 56%
   *  (69% and 93% of its TV; 2026-09-14), so neither may be treated as a layout
   *  assumption. */
  cover_url: string | null;
  trailer_id: string | null;
  slug: string | null;
  /** MAL's weekly broadcast slot: a day name and HH:MM in JST. NOT a
   *  next-episode date - MAL has none. Use nextAiring() to project it forward,
   *  and present the result as a slot rather than a confirmed airdate. */
  broadcast_day: string | null;
  broadcast_time: string | null;
  /** Parallel arrays: streaming_services[i] labels streaming_urls[i]. About half
   *  of a season carries at least one (51%; 93% of its TV, 2026-09-14). Junk URLs
   *  are filtered at ingest, so
   *  anything arriving here is a usable absolute http(s) link. */
  streaming_services: string[];
  streaming_urls: string[];
  start_year: number | null;
  start_month: number | null;
  start_day: number | null;
  run_date: string | null;
  /** Stable WeebBlade identity. (source, source_id) is whichever source won this
   *  week's merge and can change; this cannot. Store this, not the source pair,
   *  for anything that has to find the title again. Null only before the
   *  pipeline's first run with identities. */
  wb_id: string | null;
  /** Every source row this title was assembled from, as "source:source_id". */
  source_keys: string[];
  /** The next few episodes from AniList's airing schedule, soonest first. Only
   *  a single title carries them (GET /anime/{wb_id}); lists leave it empty.
   *  Several rather than one so a cached copy can skip those that have aired. */
  upcoming_episodes: AiringEpisode[];
  /** `status` is checked against AniList in the warehouse: where the sources
   *  call a title airing and AniList's daily check says it has finished or not
   *  yet aired, `status` says so. `merged_status` is what the sources said.
   *  The rest is AniList's own answer, for titles the sources call airing and
   *  null otherwise - finished, current, upcoming, or cancelled or hiatus. A
   *  hiatus leaves `status` "current" but means there is no weekly slot. */
  merged_status: string | null;
  anilist_status: string | null;
  anilist_ended_on: string | null;
  anilist_checked_on: string | null;
  /** What its sources have said differently from one fetch to the next, newest
   *  first. Only a single title carries them; lists leave it empty. */
  changes: Change[];
};

/** Mirrors backend/app/schemas.py:Change - something a source reports
 *  differently from its previous fetch. See processing/changes.py. */
export type Change = {
  /** status, episodes, score, premiere, season, broadcast, trailer, streaming,
   *  or listed: an entry a source created since its last fetch. */
  field: string;
  old: string | null;
  new: string | null;
  /** The service, for a streaming link; `new` is its URL. */
  label: string | null;
  /** The fetch it was seen in, and the one it was compared with. */
  run_date: string;
  since: string | null;
  /** Every source that reported it, in merge order. */
  sources: string[];
};

/** Mirrors backend/app/schemas.py:AiringEpisode. `airing_at` is ISO 8601 UTC. */
export type AiringEpisode = {
  episode: number | null;
  airing_at: string;
  /** The day AniList's schedule was fetched; it is refetched daily. */
  fetched_on: string | null;
};

/** Mirrors backend/app/schemas.py:ScheduledEpisode. */
export type ScheduledEpisode = {
  /** Null for a show the catalogue does not hold (One Piece, Detective Conan):
   *  it is on the schedule as AniList describes it, and links there. */
  wb_id: string | null;
  anilist_id: number;
  mal_id: number | null;
  title: string | null;
  format: string | null;
  poster_url: string | null;
  score_100: number | null;
  episode: number | null;
  episodes: number | null;
  airing_at: string;
};

export type Schedule = {
  /** Midnight today in Tokyo, as ISO 8601 UTC, and `days` after it. */
  start: string;
  end: string;
  fetched_on: string | null;
  episodes: ScheduledEpisode[];
};

export type AnimeListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: Anime[];
};

export type Digest = { run_date: string; content: string };

export type SearchResult = {
  title: string;
  source: string;
  source_id: string;
  /** Embedding distance - lower is a closer semantic match. Surfaced in the UI
   *  on purpose: it's what distinguishes this from a keyword search. */
  distance: number;
  /* Decoration from the warehouse, so a result can be drawn as a plate without a
     copy of the catalogue to look it up in. Null when the API could not place the
     match - drawn then as a title with no artwork and no score, which is what the
     API knows about it. */
  wb_id?: string | null;
  poster_url?: string | null;
  score_100?: number | null;
  format?: string | null;
  status?: string | null;
};

export type SearchResponse = { query: string; results: SearchResult[] };

/** One title in a franchise, oldest first. `wb_id` is null for an entry older
 *  than the catalogue, which the API describes from MAL's relation data. */
export type FranchiseEntry = {
  mal_id: number;
  wb_id: string | null;
  title: string | null;
  format: string | null;
  /** ISO, possibly partial: "2019", "2019-06", "2019-06-01". */
  start_date: string | null;
  season: string | null;
  season_year: number | null;
  poster_url: string | null;
  score_100: number | null;
  /** How this entry relates to the title asked about, when linked directly. */
  relation: string | null;
  is_this: boolean;
};

export type Franchise = { franchise_id: string | null; entries: FranchiseEntry[] };

/* MAL's relation types, in words. "Parent story" is the far end of both a side
   story and a spin-off; the two character/other links can name a franchise
   member that is also joined some other way, so they get words too. */
const RELATION_LABELS: Record<string, string> = {
  prequel: "Prequel",
  sequel: "Sequel",
  side_story: "Side story",
  parent_story: "Parent story",
  spin_off: "Spin-off",
  summary: "Summary",
  full_story: "Full story",
  alternative_version: "Alternative version",
  alternative_setting: "Alternative setting",
  character: "Shares characters",
  other: "Related",
};

export function relationLabel(relation: string | null): string | null {
  return relation ? (RELATION_LABELS[relation] ?? null) : null;
}

export type AnimeQuery = {
  season?: string;
  season_year?: number;
  genre?: string;
  format?: string;
  min_score?: number;
  sort?: "score_desc" | "popularity_desc" | "title";
  limit?: number;
  offset?: number;
};

/** Distinguishes "upstream said no" from a transport failure, so pages can treat
 *  an expected 503 (search index not built, no digest yet) differently from a
 *  genuine outage. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The shape of a title's own identity, e.g. wb_67666c4a0e. */
export const WB_ID = /^wb_[0-9a-f]{10}$/;

/** A title's address on this site: /anime/{wb_id}, its stable identity.
 *
 *  Addresses used to be /anime/{source}/{source_id}, which named whichever
 *  source won the title's merge that week. When the winner changed, the address
 *  changed with it, and every link made before went to a key the title no longer
 *  answered to. The identity does not move. The source-key form remains only for
 *  a title that has no identity, and proxy.ts turns any such address into the
 *  identity one. */
export function titleHref(a: { wb_id?: string | null; source: string; source_id: string }): string {
  return a.wb_id
    ? `/anime/${a.wb_id}`
    : `/anime/${encodeURIComponent(a.source)}/${encodeURIComponent(a.source_id)}`;
}

/** Best title to show, in the order a mostly-English-reading audience wants it.
 *  Every title field is independently nullable, hence the fallback chain. */
export function displayTitle(
  a: Pick<Anime, "title_english" | "title_romaji" | "title_native">,
) {
  return a.title_english || a.title_romaji || a.title_native || "Untitled";
}

/** Secondary title, only when it actually differs from the primary one -
 *  otherwise the detail page shows the same string twice. */
export function secondaryTitle(a: Anime): string | null {
  const primary = displayTitle(a);
  const alt = a.title_romaji && a.title_romaji !== primary ? a.title_romaji : null;
  return alt ?? (a.title_native && a.title_native !== primary ? a.title_native : null);
}

export function formatAirDate(a: Anime): string | null {
  if (!a.start_year) return null;
  if (!a.start_month) return String(a.start_year);
  const date = new Date(Date.UTC(a.start_year, a.start_month - 1, a.start_day ?? 1));
  return date.toLocaleDateString("en-GB", {
    day: a.start_day ? "numeric" : undefined,
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/* ---------------------------------------------------------------------------
 * Corrections for what the API actually returns. Each of these is a measured
 * problem, not a defensive guess — see DESIGN.md §"What the data actually is".
 * ------------------------------------------------------------------------ */

/** Kept as a cheap guard, not because the warehouse is wrong. Apparent
 *  duplicates in a paged fetch turned out to be an unstable ORDER BY, not bad
 *  data — see the note in lib/api.ts. With a stable sort the one-season
 *  catalogue came back as 142 rows and 142 distinct ids. This stays so that a
 *  future change of sort, or a
 *  second ingestion source coming back online with an overlapping id, cannot
 *  produce duplicate React keys. */
export function dedupeAnime(items: Anime[]): Anime[] {
  const seen = new Set<string>();
  const out: Anime[] = [];
  for (const a of items) {
    const key = `${a.source}:${a.source_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(a);
  }
  return out;
}

/** `popularity` is a RANK, not a count: lower means MORE popular. Verified
 *  against the live data — the lowest values are Saga of Tanya the Evil II and
 *  Mushoku Tensei S3, the highest are titles with no score and zero favourites.
 *  The API's only popularity sort is `popularity_desc`, which therefore returns
 *  the LEAST popular first. We sort locally instead of using it. */
export function byPopularity(a: Anime, b: Anime): number {
  const x = a.popularity ?? Number.POSITIVE_INFINITY;
  const y = b.popularity ?? Number.POSITIVE_INFINITY;
  return x - y;
}

/** Not every title has a score - 88% of a season's TV, under half of its other
 *  formats (2026-09-14), 39 of 142 titles when this was written - so ordering
 *  on score alone would leave the rest in no order at all. Scored titles come
 *  first, ordered by score; everything else falls back to popularity rank. */
export function byScoreThenPopularity(a: Anime, b: Anime): number {
  const as = a.score_100;
  const bs = b.score_100;
  if (as !== null && bs !== null) return bs - as;
  if (as !== null) return -1;
  if (bs !== null) return 1;
  return byPopularity(a, b);
}

export function byTitle(a: Anime, b: Anime): number {
  return displayTitle(a).localeCompare(displayTitle(b));
}

/** The single predicate the whole visual system keys off: colour, the score tab
 *  and the halftone treatment are all downstream of this one boolean. */
/* Scores are displayed out of 10, not out of the 100 they are stored as.
 *
 * The column is score_100 because that is Kitsu's native scale and what the
 * warehouse holds; MAL's 0-10 is converted up at ingest so the two are
 * comparable. Storage and presentation are separate questions, and readers
 * expect a decimal out of 10 - it is what MAL, AniList's user-facing display and
 * every ratings site outside Kitsu use, and "8.6" carries the same information as
 * "85.6" while reading as a score rather than a percentage.
 *
 * One place, three call sites: the browse plate, the detail page and the search
 * result plate all render this. Dividing by 10 at each of them is how they drift.
 */
export const SCORE_MAX = 10;

export function scoreOutOfTen(score100: number | null | undefined): string | null {
  if (score100 === null || score100 === undefined) return null;
  return (score100 / 10).toFixed(1);
}

export function isKnown(a: Anime): boolean {
  return a.score_100 !== null;
}

export type SortKey = "score" | "popularity" | "title";

export const SORTS: { key: SortKey; label: string; hint: string }[] = [
  { key: "score", label: "Rated first", hint: "Scored titles first, then by popularity" },
  { key: "popularity", label: "Most popular", hint: "By popularity rank, most popular first" },
  { key: "title", label: "A–Z", hint: "Alphabetical" },
];

export function sortAnime(items: Anime[], key: SortKey): Anime[] {
  const cmp =
    key === "popularity" ? byPopularity : key === "title" ? byTitle : byScoreThenPopularity;
  return [...items].sort(cmp);
}

/** Formats as the sources spell them, mapped to something readable. Kitsu mixes
 *  casing ("TV" but "movie"), which showed up in the old filter row as a
 *  visibly inconsistent list. */
export function formatLabel(format: string | null): string {
  if (!format) return "Unknown";
  const map: Record<string, string> = {
    tv: "TV",
    ona: "ONA",
    ova: "OVA",
    movie: "Film",
    music: "Music video",
    special: "Special",
  };
  return map[format.toLowerCase()] ?? format;
}


/** Pair up the parallel streaming arrays for rendering. Defensive about length
 *  mismatch: the arrays are written together at ingest, but a carried-over row
 *  from an older snapshot can have one and not the other. */
export function streamingLinks(a: Anime): { service: string; url: string }[] {
  return (a.streaming_urls ?? []).map((url, i) => ({
    service: a.streaming_services?.[i] ?? "Watch",
    url,
  }));
}

/* The four sources the pipeline is wired for, and how to name them in prose.
 *
 * The count is a fact about the pipeline, so it is stated here; WHICH of them are
 * live is a fact about the data, so it is derived (`getSources()`). Both were
 * hardcoded before, and both were wrong: the footer said "Assembled weekly from
 * Kitsu" and the masthead said "1 of 3 sources live" long after MAL had joined
 * and become the only source of studios, source material and broadcast slots.
 *
 * A UI that misreports its own provenance is worse than one that says nothing,
 * and this is a project whose entire point is reconciling several sources.
 */
export const ALL_SOURCES = ["anilist", "jikan", "kitsu", "mal"] as const;

const SOURCE_LABELS: Record<string, string> = {
  anilist: "AniList",
  jikan: "Jikan",
  kitsu: "Kitsu",
  mal: "MyAnimeList",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/** "Kitsu and MyAnimeList" — an Oxford-free list, because it reads as prose. */
export function joinSources(sources: string[]): string {
  const names = sources.map(sourceLabel);
  if (names.length === 0) return "no sources";
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/* Where a reader can go to verify or track this title upstream.
 *
 * A list rather than one URL, because after the cross-source merge a row can
 * carry both a Kitsu slug and a MAL id, and they are genuinely different
 * destinations - Kitsu for the artwork and streaming links this site already
 * shows, MAL for the list and forum most readers actually use.
 *
 * Kitsu leads, matching the source priority everywhere else. Only Kitsu ever
 * emits a slug, so its presence is enough to identify the destination.
 *
 * AniList is read from the title's source keys, since it contributes no column
 * of its own that names it. It is also what keeps every title reachable: when
 * AniList joined (2026-09-14) it brought 50 titles with neither a Kitsu slug nor
 * a MAL id. Measured over all 6,148: 3,881 have a slug, 5,551 a mal_id, 2,119 an
 * AniList key, and none have none of the three.
 */
export function sourceLinks(a: Anime): { label: string; href: string }[] {
  const links: { label: string; href: string }[] = [];
  if (a.slug) links.push({ label: "View on Kitsu", href: `https://kitsu.app/anime/${a.slug}` });
  if (a.mal_id)
    links.push({
      label: "View on MyAnimeList",
      href: `https://myanimelist.net/anime/${a.mal_id}`,
    });
  const anilist = a.source_keys.find((key) => key.startsWith("anilist:"));
  if (anilist)
    links.push({
      label: "View on AniList",
      href: `https://anilist.co/anime/${anilist.slice("anilist:".length)}`,
    });
  return links;
}


/* ---------------------------------------------------------------------------
 * Format defaulting.
 *
 * In the one-season catalogue this was written against, 27 of 142 entries were
 * music videos and none was scored; another 29 were ONAs (13% scored) and 11
 * films (9%), against 66 TV series at 48%. So the headline "73% of the season
 * has no score" was mostly measuring music videos rather than saying anything
 * about anime. It still would: in Summer 2026, 65 of 74 TV series are scored,
 * against 17 of 62 ONAs and 8 of 59 music videos (measured 2026-09-14).
 *
 * Defaulting to TV is what LiveChart and AniChart both do, for the same reason.
 * Nothing is hidden: FORMAT_ALL is one click away and every format keeps its own
 * chip, so the long tail is reachable and still counted honestly on the front
 * page.
 * ------------------------------------------------------------------------ */

/** Sentinel for "do not filter by format". A real value rather than `undefined`
 *  because undefined now means "use the default", which is TV. */
export const FORMAT_ALL = "all";

export const DEFAULT_FORMAT = "TV";

/** The season index popover (components/SeasonIndex.tsx). One index, opened by
 *  anything carrying popoverTarget={SEASON_INDEX_ID}: the header's Seasons
 *  button, the catalogue heading, the front page's masthead. */
export const SEASON_INDEX_ID = "season-index";

export function isTv(a: Anime): boolean {
  return (a.format ?? "").toLowerCase() === "tv";
}

/** Resolve the format filter from a URL param. Absent means the TV default;
 *  FORMAT_ALL means no filtering at all. */
export function resolveFormat(param: string | undefined): string | null {
  if (param === FORMAT_ALL) return null;
  return param ?? DEFAULT_FORMAT;
}

/* ---------------------------------------------------------------------------
 * Broadcast slot -> next airing.
 *
 * MAL has no next-episode date. What it has is the weekly slot the show occupies
 * ("saturday", "23:00", JST), so the next airing is DERIVED here rather than
 * stored. That is deliberate: the pipeline runs weekly, so a date computed at
 * ingest would be wrong within days, while a slot holds for a whole cour.
 *
 * It also means the result is a prediction, not a fact. A broadcast can slip,
 * and MAL's slot will not know. Callers must present it as the regular slot,
 * never as a confirmed airdate.
 * ------------------------------------------------------------------------ */

const JST_OFFSET_MS = 9 * 60 * 60 * 1000;
const WEEKDAYS = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
];

/** The next instant the show's slot comes round, or null if the slot is
 *  unparseable. Japan does not observe DST, so a fixed +09:00 is exact. */
export function nextAiring(
  broadcastDay: string | null,
  broadcastTime: string | null,
  now: Date = new Date(),
): Date | null {
  if (!broadcastDay || !broadcastTime) return null;

  const targetDay = WEEKDAYS.indexOf(broadcastDay.trim().toLowerCase());
  if (targetDay < 0) return null;

  const [hours, minutes] = broadcastTime.split(":").map(Number);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null;

  // Shift into JST so UTC getters read as Japanese wall-clock time, do the
  // weekday arithmetic there, then shift back. Doing it this way avoids relying
  // on the server's or the viewer's own timezone, which differ.
  const jstNow = new Date(now.getTime() + JST_OFFSET_MS);
  const daysAhead = (targetDay - jstNow.getUTCDay() + 7) % 7;

  const slot = new Date(jstNow);
  slot.setUTCDate(slot.getUTCDate() + daysAhead);
  slot.setUTCHours(hours, minutes, 0, 0);

  // Same weekday but the slot has already passed today: it is next week's.
  if (slot.getTime() <= jstNow.getTime()) slot.setUTCDate(slot.getUTCDate() + 7);

  return new Date(slot.getTime() - JST_OFFSET_MS);
}

/* ---------------------------------------------------------------------------
 * Airdates, from AniList's schedule.
 *
 * Written out by hand rather than with Intl, because these render on the server
 * AND hydrate in the browser, and the two do not agree: Node's ICU and a
 * browser's abbreviate September differently ("Sept" against "Sep"), which is a
 * hydration mismatch waiting on the calendar. Fixed names cannot drift.
 *
 * Japan's times, because that is the calendar broadcasts keep. The reader's own
 * time is added in the browser, where their timezone is known.
 * ------------------------------------------------------------------------ */

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** The instant shifted so its UTC fields read as the wall clock in Tokyo. */
function inJapan(iso: string): Date {
  return new Date(Date.parse(iso) + JST_OFFSET_MS);
}

/** "2026-09-14": the day in Tokyo an instant falls on. */
export function jstDayKey(iso: string): string {
  return inJapan(iso).toISOString().slice(0, 10);
}

/** "22:30" in Tokyo. */
export function jstClock(iso: string): string {
  return inJapan(iso).toISOString().slice(11, 16);
}

/** "Monday 14 September, 20:57 JST". */
export function jstAirdate(iso: string): string {
  const d = inJapan(iso);
  return `${DAY_NAMES[d.getUTCDay()]} ${d.getUTCDate()} ${MONTH_NAMES[d.getUTCMonth()]}, ${jstClock(iso)} JST`;
}

/** A day key as a schedule column is headed: weekday, and "14 Sep". */
export function dayKeyLabel(key: string): { weekday: string; date: string } {
  const d = new Date(`${key}T00:00:00Z`);
  return {
    weekday: DAY_NAMES[d.getUTCDay()],
    date: `${d.getUTCDate()} ${MONTH_NAMES[d.getUTCMonth()].slice(0, 3)}`,
  };
}

/** "14 September", for a YYYY-MM-DD date. */
export function calendarDate(key: string): string {
  const d = new Date(`${key}T00:00:00Z`);
  return `${d.getUTCDate()} ${MONTH_NAMES[d.getUTCMonth()]}`;
}

/** How long until an episode airs. Minute resolution: nothing here is shown
 *  finer, and a per-second tick would re-render for nothing. `short` is for
 *  the schedule's rows, where a hundred of them sit side by side. */
export function countdown(ms: number, short = false): string {
  const minutes = Math.max(0, Math.floor(ms / 60_000));
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const unit = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (short) {
    if (days >= 1) return `${days}d ${hours % 24}h`;
    if (hours >= 1) return `${hours}h ${minutes % 60}m`;
    return `${minutes}m`;
  }
  if (days >= 1) return hours % 24 ? `${unit(days, "day")} ${unit(hours % 24, "hour")}` : unit(days, "day");
  if (hours >= 1) return minutes % 60 ? `${unit(hours, "hour")} ${unit(minutes % 60, "minute")}` : unit(hours, "hour");
  return minutes >= 1 ? unit(minutes, "minute") : "under a minute";
}

/* Whether a title is airing, and how to say so.
 *
 * `status` already carries AniList's word where it overrules the sources - the
 * warehouse applies it (processing/duckdb_catalog._status_corrected) - so a
 * finished show reads "finished" in every list. What is left here is the case
 * the shared vocabulary cannot say: a show on hiatus is still "current", but
 * it is not airing this week, and no weekly slot should be offered for it. */
const STOPPED: Record<string, string> = {
  finished: "Finished",
  cancelled: "Cancelled",
  hiatus: "On hiatus",
  upcoming: "Not yet aired",
};

export function isAiring(a: Anime): boolean {
  return a.status === "current" && (!a.anilist_status || a.anilist_status === "current");
}

/** The Status fact. Where AniList overrules the sources it says so, because
 *  every other field on the page still comes from the sources that disagree.
 *  AniList is only asked about titles the sources call airing, so any other
 *  answer from it is an overruling. */
export function statusLabel(a: Anime): string {
  const said = a.anilist_status;
  if (said && said !== "current" && STOPPED[said]) return `${STOPPED[said]}, per AniList`;
  if (a.status === "current") return "Airing now";
  if (a.status === "finished") return "Finished";
  // upcoming, unreleased, tba: not aired yet, whatever each source calls it.
  return a.status ? "Not yet aired" : "Unknown";
}

const CHANGE_STATUS: Record<string, string> = {
  current: "airing",
  finished: "finished",
  upcoming: "not yet aired",
};

/** "2026", "October 2026" or "4 October 2026", from the change log's ISO-ish
 *  value. By hand, not Intl: Node and browsers disagree on short month names. */
function premiereWords(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!month) return String(year);
  return `${day ? `${day} ` : ""}${MONTH_NAMES[month - 1]} ${year}`;
}

function seasonWords(value: string): string {
  const [season, year] = value.split(" ");
  return `${season.charAt(0)}${season.slice(1).toLowerCase()} ${year ?? ""}`.trim();
}

/** One change as a sentence: "Now finished, was airing", "Score 7.2 to 7.4". */
export function changeSentence(c: Change): string {
  const was = c.old;
  const now = c.new ?? "";
  switch (c.field) {
    case "status": {
      const word = (s: string) => CHANGE_STATUS[s] ?? s;
      return was ? `Now ${word(now)}, was ${word(was)}` : `Now ${word(now)}`;
    }
    case "episodes":
      return was ? `Episode count changed from ${was} to ${now}` : `Episode count announced: ${now}`;
    case "score":
      return was ? `Score ${was} to ${now}` : `First scored: ${now}`;
    case "premiere":
      return was
        ? `Premiere moved from ${premiereWords(was)} to ${premiereWords(now)}`
        : `Premiere date set: ${premiereWords(now)}`;
    case "season":
      return was ? `Moved from ${seasonWords(was)} to ${seasonWords(now)}` : `Filed under ${seasonWords(now)}`;
    case "broadcast": {
      const [day, time] = now.split(" ");
      return `Broadcast slot now ${broadcastSlotLabel(day, time) ?? now}`;
    }
    case "trailer":
      return was ? "New trailer" : "Trailer added";
    case "streaming":
      return `Now on ${c.label ?? now}`;
    case "listed":
      return "Newly listed";
    default:
      return `${c.field} changed`;
  }
}

/** "13 September", with the year only where it is not the newest change's. */
export function changeDate(runDate: string, newest: string): string {
  const year = runDate.slice(0, 4);
  return year === newest.slice(0, 4) ? calendarDate(runDate) : `${calendarDate(runDate)} ${year}`;
}

/** "Saturdays 23:00 JST" - the slot itself, which is what we actually know. */
export function broadcastSlotLabel(
  broadcastDay: string | null,
  broadcastTime: string | null,
): string | null {
  if (!broadcastDay || !broadcastTime) return null;
  const day = broadcastDay.trim().toLowerCase();
  if (!WEEKDAYS.includes(day)) return null;
  const name = day.charAt(0).toUpperCase() + day.slice(1);
  return `${name}s ${broadcastTime} JST`;
}


/** MAL reports source material as a snake_case token ("light_novel",
 *  "4_koma_manga"). Rendered as-is it looks like a database field, which on a
 *  page whose whole argument is legibility is the wrong impression. */
/* Age ratings, where the two sources use different vocabularies AND different
 * scales. Kitsu says G / PG / R; MAL says g / pg / pg_13 / r / r+ / rx. The
 * transform reconciles format and status to Kitsu's words, but it cannot do that
 * here without lying: MAL's pg_13 is a real rating with no Kitsu equivalent, and
 * flattening it to PG would claim something milder than the source said.
 *
 * So this normalises presentation only, never meaning. Left alone, 258 of 480
 * live titles rendered the literal string "pg_13" as their rating.
 */
const AGE_RATINGS: Record<string, string> = {
  g: "G",
  pg: "PG",
  pg_13: "PG-13",
  r: "R",
  "r+": "R+",
  rx: "Rx",
  r18: "R18",
};

export function ageRatingLabel(value: string | null): string | null {
  if (!value) return null;
  const key = value.trim().toLowerCase();
  // An unseen value is still tidied rather than shown raw, so it degrades to
  // "PG-13" shape instead of "pg_13".
  return AGE_RATINGS[key] ?? key.toUpperCase().replace(/_/g, "-");
}

export function sourceMaterialLabel(value: string | null): string | null {
  if (!value) return null;
  const words = value.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
