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
  popularity: number | null;
  favourites: number | null;
  start_year: number | null;
  start_month: number | null;
  start_day: number | null;
  run_date: string | null;
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
