/* Client-safe half of the API layer: types, the base URL, and pure formatting
 * helpers. Kept separate from lib/api.ts because that module imports
 * `cacheLife`, which is server-only - the search UI runs in the browser and
 * importing anything from api.ts there drags the whole server module into the
 * client bundle and fails the build. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://weebblade.duckdns.org";

/** Mirrors backend/app/schemas.py:Anime. Almost everything is nullable because
 *  the three upstream sources genuinely disagree on what they provide - Kitsu
 *  (currently the only one up) has no studios, mal_id or source_material at all. */
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
  /** Also a rank. No denser than score_100 (both ~29% of the season). */
  rating_rank: number | null;
  /** The only dense interest signal: present for ~100% of the season, where
   *  score_100 covers 29% and favourites tops out around 25. */
  user_count: number | null;
  favourites: number | null;
  age_rating: string | null;
  /** Sparse enhancements. cover_url is on ~17% of titles and trailer_id ~57%,
   *  so neither may be treated as a layout assumption. */
  cover_url: string | null;
  trailer_id: string | null;
  slug: string | null;
  /** MAL's weekly broadcast slot: a day name and HH:MM in JST. NOT a
   *  next-episode date - MAL has none. Use nextAiring() to project it forward,
   *  and present the result as a slot rather than a confirmed airdate. */
  broadcast_day: string | null;
  broadcast_time: string | null;
  /** Parallel arrays: streaming_services[i] labels streaming_urls[i]. ~59% of
   *  the season carries at least one. Junk URLs are filtered at ingest, so
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
 *  data — see the note in lib/api.ts. With a stable sort the API returns 142
 *  rows and 142 distinct ids. This stays so that a future change of sort, or a
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

/** Scores exist for only 39 of 142 titles, so score-first ordering ranks on
 *  data three quarters of the catalogue lacks. Scored titles come first, ordered by
 *  score; everything else falls back to popularity rank rather than to nothing. */
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
 * Kitsu leads, matching the source priority everywhere else. Measured over 480
 * live titles: 260 have a slug, 405 have a mal_id, 185 have both, and none have
 * neither - so every title gets at least one working link. Only Kitsu ever emits
 * a slug, so its presence is enough to identify the destination.
 */
export function sourceLinks(a: Anime): { label: string; href: string }[] {
  const links: { label: string; href: string }[] = [];
  if (a.slug) links.push({ label: "View on Kitsu", href: `https://kitsu.app/anime/${a.slug}` });
  if (a.mal_id)
    links.push({
      label: "View on MyAnimeList",
      href: `https://myanimelist.net/anime/${a.mal_id}`,
    });
  return links;
}


/* ---------------------------------------------------------------------------
 * Format defaulting.
 *
 * 27 of 142 entries in a season are music videos, and 0% of them are ever
 * scored. Another 29 are ONAs (13% scored) and 11 are films (9%). TV series are
 * 66 titles at 48% scored. So the headline "73% of the season has no score" was
 * mostly measuring music videos rather than saying anything about anime.
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

/* The week as a schedule is read: Monday first.
 *
 * WEEKDAYS above is Sunday-first because its index has to line up with
 * getUTCDay(). That is arithmetic, not presentation, and the two should not be
 * the same list. */
export const SCHEDULE_DAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

export function weekdayLabel(day: string): string {
  return day.charAt(0).toUpperCase() + day.slice(1);
}

export function hasBroadcastSlot(a: Anime): boolean {
  return slotMinutes(a) !== null;
}

/** Minutes past midnight JST, for ordering a day's listings. Null when the slot
 *  is missing or unparseable, which is also what makes it the has-a-slot test.
 *
 *  Sorted chronologically within the calendar day, so a 00:26 broadcast opens
 *  its day rather than closing the previous one. Japanese listings often bill
 *  that as the previous evening's late-night block, but the source reports a
 *  calendar day and re-mapping it here would be this site inventing a
 *  convention the data never stated. */
export function slotMinutes(a: Anime): number | null {
  const day = a.broadcast_day?.trim().toLowerCase();
  if (!day || !WEEKDAYS.includes(day) || !a.broadcast_time) return null;

  const [hours, minutes] = a.broadcast_time.split(":").map(Number);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null;
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null;

  return hours * 60 + minutes;
}

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
