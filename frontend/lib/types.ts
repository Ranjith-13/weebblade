/* Client-safe half of the API layer: types, the base URL, and pure formatting
 * helpers. Kept separate from lib/api.ts because that module imports
 * `cacheLife`, which is server-only - the search UI runs in the browser and
 * importing anything from api.ts there drags the whole server module into the
 * client bundle and fails the build. */

/* The API this site reads. Overridden by NEXT_PUBLIC_API_BASE_URL - set it in
 * Vercel's project settings, and in CI through the API_BASE_URL repository
 * variable - so the default is only what applies when nobody says otherwise.
 *
 * It was https://weebblade.duckdns.org, an EC2 instance deleted on 13 October
 * 2026. The API runs as a container built from backend/Dockerfile now; see
 * render.yaml. Baked into the client bundle at build time, like every
 * NEXT_PUBLIC_ variable, which is fine - it is a public read-only API. */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://weebblade-api.onrender.com";

/* Where this site itself lives: the base for canonical URLs, Open Graph images,
 * robots.txt and the sitemap. Three files used to hardcode it separately, all
 * three to the EC2 host, which would have published a dead domain in every
 * crawler's index and every shared link's preview. Override with
 * NEXT_PUBLIC_SITE_URL if the deployment is named something else. */
/** Where a reader's explicit theme choice is remembered.
 *
 *  HERE, NOT IN components/ThemeChoice.tsx, AND THAT IS NOT TIDINESS. The root
 *  layout is a Server Component and it needs this string to build the blocking
 *  script that applies a stored theme before first paint. Importing it from a
 *  "use client" module gives a Server Component a client REFERENCE rather than
 *  the value, so the script shipped as localStorage.getItem(undefined) - it
 *  compiled, it ran, it silently did nothing, and every reload flashed light
 *  before the choice reapplied. This module carries no "use client", so both
 *  sides get the actual string. */
export const THEME_KEY = "weebblade-theme";

export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://weebblade.vercel.app";

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
  /** The episodes that have already aired, newest first, from the archive of
   *  every schedule fetched rather than the current one. Before it existed an
   *  episode left the site the morning after it aired, so a show mid-season
   *  could say when the next one was due and nothing about any that had been. */
  aired_episodes: AiringEpisode[];
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
  /** True where the sources call a title airing, AniList has never answered for
   *  it, and it premiered over a year ago: nothing can confirm it is still
   *  running. 67 of the 296 titles the sources call airing have no answer, 48
   *  of them premiered over a year ago. Not airing, as far as this site can
   *  say - see isAiring. */
  airing_unconfirmed: boolean;
  /** What its sources have said differently from one fetch to the next, newest
   *  first. Only a single title carries them; lists leave it empty. */
  changes: Change[];
  /** Every run's reading of this title's score, oldest first. Same rule as
   *  `changes`: only a single title carries it. Usually flat - see scoreArc,
   *  which is the only thing that should render it. */
  score_history: ScorePoint[];
  source_scores: SourceScore[];
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

/** Mirrors backend/app/schemas.py:ChangedTitle - a change with the title it
 *  belongs to, as GET /changes returns it. */
export type ChangedTitle = Change & {
  wb_id: string;
  title: string | null;
  format: string | null;
  poster_url: string | null;
  season: string | null;
  season_year: number | null;
};

/** Mirrors backend/app/schemas.py:ChangeFeed. The window is the days up to the
 *  newest fetch compared, not up to today: between weekly runs it stays put. */
export type ChangeFeed = {
  since: string | null;
  until: string | null;
  changes: ChangedTitle[];
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

/** The BCP-47 tag for a string, where its script settles the question, and
 *  undefined where it does not.
 *
 *  Every title on this site sits inside `<html lang="en">`, including the
 *  native ones. A browser given no better information applies English line
 *  breaking and English font selection to Japanese, and a screen reader reads
 *  it in an English voice, which is unintelligible rather than merely wrong.
 *
 *  THE HAN CASE IS DELIBERATELY LEFT UNLABELLED, and that is the whole reason
 *  this is a function rather than a hardcoded lang="ja". Kana or Hangul settle
 *  it: nothing else uses them. Han alone does not - this catalogue holds
 *  Chinese donghua beside Japanese anime, "Douluo Dalu" and "Wanmei Shijie"
 *  among them, and tagging those `ja` would tell a screen reader to read
 *  Chinese in Japanese. Saying nothing leaves the reader where they already
 *  were; saying the wrong thing is worse than the gap it fills. */
export function scriptLang(text: string | null | undefined): string | undefined {
  if (!text) return undefined;
  if (/[\u3040-\u309f\u30a0-\u30ff]/.test(text)) return "ja"; // hiragana, katakana
  if (/[\uac00-\ud7af\u1100-\u11ff]/.test(text)) return "ko"; // hangul
  return undefined; // Han alone cannot be told apart here, so it is not claimed
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
/** Which season a bare URL means: the newest that has STARTED, not the newest
 *  on file. The pipeline fetches the next season months ahead, so seasons[0] is
 *  routinely one nobody can watch yet.
 *
 *  Here rather than in api.ts because this was being decided in three places
 *  and two of them were wrong: /browse's generateMetadata took seasons[0], so
 *  the heading read "Fall 2026" while the tab, the bookmark and the search
 *  result read "Winter 2027"; and the season index marked that same unstarted
 *  season as the current one, under a comment claiming it mirrored getSeason().
 *  A client component needs it, so it cannot live in the server-only module. */
export function startedSeason<T extends { upcoming: boolean }>(seasons: T[]): T | undefined {
  return seasons.find((s) => !s.upcoming) ?? seasons[0];
}

/** Whether a season is still being re-asked, or was frozen when it was captured.
 *
 *  THE WEEKLY RUN REFETCHES THE CURRENT SEASON AND THE NEXT ONE, and nothing
 *  else (`ingestion/seasons.capture_both`). Every older season holds whatever
 *  its sources said on the day it was fetched - a 2017 score is as of the
 *  afternoon it was backfilled and will not move again. That is the right trade
 *  for finished shows, whose scores barely move, and it is why backfilling is a
 *  command rather than something the weekly run does. But it is also a fact
 *  about the data that the site has never stated, on a project whose whole
 *  claim is not pretending the data is more complete than it is.
 *
 *  Position in the list rather than a date: the API hands every title the
 *  CATALOGUE's run_date, which is the week it was last consolidated, not the
 *  day its season was last asked about - Fall 2021, Fall 2024 and Fall 2026 all
 *  read 2026-10-12. There is no per-season fetch date to print, so this states
 *  the rule instead of inventing a number for it.
 *
 *  And position rather than a second quarter comparator: getSeasons already
 *  sorts newest first, and a copy of that ordering is a copy that will disagree
 *  (backend/app/seasons.py makes the same argument about its CASE expression). */
export function isFrozenSeason<T extends { key: string; upcoming: boolean }>(
  key: string | null | undefined,
  seasons: T[],
): boolean {
  if (!key) return false;
  const current = startedSeason(seasons);
  if (!current) return false;
  const at = seasons.findIndex((s) => s.key === key);
  const live = seasons.findIndex((s) => s.key === current.key);
  return at > live; // older than the season still being refetched
}

/** The em-dash, and the ONLY place this site is allowed to print one.
 *
 *  DESIGN.md bans em-dashes in visible copy because it is the single most
 *  reliable tell of generated prose, with one carve-out: the marker for "no
 *  value" in tabular data, which is a typographic convention rather than a
 *  flourish. Naming it means the lint rule in eslint.config.mjs can reject
 *  every other em-dash in app/, components/ and lib/ without an allowlist, and
 *  a reader of a plate, a search result or a social card can see that the dash
 *  there is the same deliberate one. */
// Written as an escape so that it reads as deliberate rather than typed.
// eslint-disable-next-line no-restricted-syntax -- the one em-dash this site prints
export const NULL_MARKER = "\u2014";

// What an LLM reaches for and a keyboard does not. The narrow no-break space
// and the non-breaking hyphen are invisible as characters and obvious as
// provenance; the digest of 2026-10-12 carried 26 of the hyphen and 13 of the
// space.
const NARROW_NBSP = "\u202f";
const NB_HYPHEN = "\u2011";
const EM_DASH = /\s*\u2014\s*/g;
const SENTENCE_END = /(?<=[.!?])\s+/;

/** Generated prose, repunctuated as this site punctuates.
 *
 *  THE DIGEST IS THE ONE BLOCK OF TEXT HERE NOBODY WROTE, and it is also the
 *  largest: the home page prints its lead paragraph. The run of 2026-10-12
 *  carried five em-dashes, one of them in that lead, against a design rule that
 *  bans them by name. Fixing it in the prompt would only reach digests not yet
 *  written, and models follow negative formatting instructions unevenly; this
 *  reaches the ones already stored, on the next render, deterministically.
 *
 *  It changes punctuation and never words, which is the line that keeps "written
 *  by an LLM from this week's ingested data" an honest caption. ageRatingLabel()
 *  normalises a vocabulary for display on the same principle.
 *
 *  WHAT AN EM-DASH BECOMES, decided by reading the output rather than by taste:
 *  - Two in one sentence are a parenthesis, so they become brackets. "hit the
 *    schedule (including Aoashi Season 2, Blue Box Season 2 and Firefly
 *    Wedding) while several series shifted premiere dates".
 *  - One is almost always introducing an elaboration, which is a colon's job.
 *    A comma was tried first and makes run-ons of the cases that matter: "a
 *    slew of streaming deals landed, Aoashi Season 2 now streams on iQIYI"
 *    joins two independent clauses, where "landed: Aoashi Season 2 now
 *    streams" does not.
 *  - Except straight after a figure, where a colon reads as a ratio or a label
 *    rather than an introduction: "an average score of 69.6, slightly under
 *    Summer's 71.0", not "69.6: slightly under".
 *
 *  Three em-dashes in one sentence is past deterministic repair and they all
 *  become colons. No digest has yet done it. */
export function plainPunctuation(text: string): string {
  return text
    .replaceAll(NB_HYPHEN, "-")
    .replaceAll(NARROW_NBSP, " ")
    .split("\n")
    .map((line) => line.split(SENTENCE_END).map(repunctuate).join(" "))
    .join("\n");
}

function repunctuate(sentence: string): string {
  const dashes = sentence.match(/\u2014/g)?.length ?? 0;
  if (dashes === 0) return sentence;

  const rewritten =
    dashes % 2 === 0
      ? (() => {
          let inside = false;
          return sentence.replace(EM_DASH, () => ((inside = !inside) ? " (" : ") "));
        })()
      : sentence.replace(EM_DASH, (_match: string, at: number) =>
          /\d$/.test(sentence.slice(0, at)) ? ", " : ": ",
        );

  // A dash that closed a clause at the end of a sentence leaves " )." behind.
  return rewritten.replace(/ +([.,;:!?)])/g, "$1").replace(/\( +/g, "(");
}

/** Mirrors backend/app/schemas.py:SimilarTitle - a neighbour of a title by what
 *  it is about. Trimmed rather than a whole Anime, like a SearchResult: enough
 *  to draw a plate, and nothing a block of six needs to carry six times. */
export type SimilarTitle = {
  wb_id: string;
  title: string | null;
  poster_url: string | null;
  score_100: number | null;
  format: string | null;
  season: string | null;
  season_year: number | null;
  /** Cosine distance from the title being viewed. A good neighbour sits between
   *  0.2 and 0.6; see ai/search/similar.py for what lives below that. */
  distance: number;
};

export const SCORE_MAX = 10;

export type ScorePoint = { run_date: string; score_100: number };

export type SourceScore = { source: string; score_100: number; user_count: number | null };

/** The sources' scores, best first, only where they actually disagree.
 *
 *  THE PAGE PRINTS ONE NUMBER AND THE WAREHOUSE HOLDS THREE. Measured over this
 *  catalogue, 4,138 titles are scored by two or more sources and only 2.9% of
 *  them agree: 36% differ by 0.2 to 0.3, 24% by 0.4 to 0.5, 21% by 0.6 to 1.0
 *  and 325 titles by more than a point. The merged figure is a choice, and the
 *  readings it beat are data this project collected and then discarded at
 *  render time - on the one page element every visitor looks at.
 *
 *  BELOW 0.2 IT SAYS NOTHING: a single decimal step is where rounding and a
 *  crowd of a different size land, not a disagreement.
 *
 *  THE THRESHOLD WAS 0.4 AND THAT WAS MEASURING THE WRONG THING. It was set
 *  from the spread distribution alone, and it hid the title this feature was
 *  built from: MyAnimeList 8.7, AniList 8.5, Kitsu 8.4 is a spread of 0.3, so
 *  the rule excluded its own motivating example. What makes that title worth a
 *  block is not the size of the gap but who is on each side of it - the 8.4 the
 *  page prints comes from 1,447 votes and the 8.7 it hides comes from 204,162.
 *  A pure spread cutoff cannot see that, and set high enough to filter noise it
 *  also filters the cases where a tiny crowd is outvoting a huge one. 0.2 keeps
 *  them and still drops the 10.6% that agree to within a decimal.
 *
 *  Vote counts travel with the scores because the gap is usually a population
 *  rather than a verdict. One real title reads MyAnimeList 8.7 from 204,162
 *  votes, AniList 8.5 from 99,660, and Kitsu 8.4 from 1,447 - and the page
 *  shows 8.4, because Kitsu won the merge. Without the denominators that looks
 *  like three opinions; with them it is one crowd of 1,447 outvoting one of
 *  204,162 on which number a reader sees. */
export const SPREAD_WORTH_SHOWING = 0.2;

export function disagreeingSources(
  scores: SourceScore[] | null | undefined,
): SourceScore[] {
  const rated = (scores ?? []).filter((s) => s.score_100 != null);
  if (rated.length < 2) return [];
  const shown = rated.map((s) => Number(scoreOutOfTen(s.score_100)));
  const spread = Math.max(...shown) - Math.min(...shown);
  // Rounded, because the comparison has to happen at the precision the site
  // prints: 0.39999 is this rule's own floating-point noise, not a reading.
  return Math.round(spread * 10) / 10 >= SPREAD_WORTH_SHOWING ? rated : [];
}

/** "204k", "1.4k", "860" - a vote count at a glance, in a 15rem rail.
 *
 *  Hand-rolled rather than Intl.NumberFormat's compact notation for the reason
 *  jstAirdate is hand-rolled: this renders on the server and hydrates in the
 *  browser, and two ICU builds that abbreviate differently are a hydration
 *  mismatch waiting on somebody else's upgrade. */
export function compactCount(n: number | null | undefined): string | null {
  if (n == null || n < 0) return null;
  if (n < 1_000) return String(n);
  if (n < 1_000_000) {
    const k = n / 1_000;
    return `${k < 10 ? k.toFixed(1) : Math.round(k)}k`;
  }
  const m = n / 1_000_000;
  return `${m < 10 ? m.toFixed(1) : Math.round(m)}m`;
}

/** What a title's score has done, in one clause, or null where it has done
 *  nothing worth printing.
 *
 *  COMPARED AT THE PRECISION THE SITE SHOWS, which is the whole of the design
 *  here. Scores are averages over tens of thousands of votes and they crawl: of
 *  3,653 titles with two or more readings, 283 moved at all and only 121 moved
 *  enough to be visible at one decimal (measured 2026-10-14). Printing "8.41 to
 *  8.36" on a page that elsewhere says 8.4 would be inventing precision the
 *  product does not use anywhere else.
 *
 *  It is still worth having where people look, because movement tracks how
 *  recently a show aired - the votes stop arriving and the average sets. Where a
 *  source was demonstrably asked again, the printed score changed on 35% of
 *  readings of a season still on air and on 1% of readings of one already over
 *  (544 re-asked readings, 2026-10-14; /scores shows the working). So this fires
 *  about a third of the time on a current title and essentially never on an old
 *  one, which is the same rule the rest of the page follows: say it where there
 *  is something to say.
 *
 *  An earlier version of this note put those rates at 51% and 0% by counting
 *  snapshots rather than fetches. Most rows in most runs are carried forward
 *  unchanged, so that version was measuring which seasons the pipeline refetches
 *  - see app/scores/page.tsx and backend/app/routers/scores.py. */
export function scoreArc(points: ScorePoint[] | null | undefined): string | null {
  if (!points || points.length < 2) return null;

  const shown = points.map((p) => Number(scoreOutOfTen(p.score_100)));
  const low = Math.min(...shown);
  const high = Math.max(...shown);
  if (low === high) return null;

  const first = shown[0];
  const last = shown[shown.length - 1];
  const since = calendarDate(points[0].run_date);

  if (last > first) return `up from ${first.toFixed(1)} since ${since}`;
  if (last < first) return `down from ${first.toFixed(1)} since ${since}`;
  // Ends level, middle did not: the arc is the fact, so name its range.
  return `between ${low.toFixed(1)} and ${high.toFixed(1)} since ${since}`;
}

/** Mirrors backend/app/schemas.py. One season's re-asked readings: a reading
 *  counted only where the source's own vote count had also moved, which is the
 *  proof that it was fetched rather than carried forward. See /scores. */
export type SeasonSettling = {
  season: string;
  season_year: number;
  /** Titles with at least one re-asked reading, not the size of the season. */
  titles: number;
  reasks: number;
  /** The number came back different at all, against different at the one
   *  decimal this site prints. The gap between them is the finding. */
  revised: number;
  visible: number;
  /** Points out of 100, as the warehouse stores a score. One whole point is the
   *  smallest step the site can print. */
  median_change: number;
  largest_change: number;
  up: number;
  down: number;
  phase: SeasonPhase;
};

/** Where a season's own quarter sits against the window of run dates: on air
 *  while the pipeline was watching, over before it began, or not yet started. */
export type SeasonPhase = "airing" | "over" | "upcoming";

export type SettlingBand = Omit<SeasonSettling, "season" | "season_year" | "largest_change"> & {
  seasons: number;
};

export type ArrivalPoint = { run_date: string; listed: number; scored: number };

export type ScoreSettling = {
  first_run: string | null;
  last_run: string | null;
  snapshots: number;
  /** Seasons the catalogue holds, against the ones in `seasons`. The difference
   *  is seasons nothing asked about again, which this cannot speak for. */
  seasons_held: number;
  reasks: number;
  sources: { source: string; reasks: number }[];
  seasons: SeasonSettling[];
  bands: SettlingBand[];
  arrival: { season: string; season_year: number; points: ArrivalPoint[] } | null;
};

/** Mirrors backend/app/schemas.py:DailyScorePoint. */
export type DailyScorePoint = {
  fetched_on: string;
  score_100: number;
  user_count: number | null;
};

/** Mirrors backend/app/schemas.py:PrintedMove.
 *
 *  `votes_gained` is the field that keeps this printable. A score stored out of
 *  100 and shown out of 10 crosses a rounding boundary on a single vote, so two
 *  readings a day apart can both be real and only one be news: on 2026-10-17
 *  one title moved 6.8 to 6.9 on two new votes while another moved 6.9 to 7.0
 *  on 521. Never print a move without the weight behind it. */
export type PrintedMove = {
  on: string;
  was: number;
  now: number;
  votes_gained: number | null;
};

/** Mirrors backend/app/schemas.py:DailyScores - a title's score as asked every
 *  morning, oldest first. Only airing titles have readings. */
export type DailyScores = {
  wb_id: string;
  points: DailyScorePoint[];
  /** Pairs of consecutive readings where the vote count moved. The unit; a
   *  reading that returns the same vote count cannot be told from a copy. */
  reasks: number;
  moves: PrintedMove[];
  votes_gained: number | null;
};

/** How few new votes make a printed move arithmetic rather than news.
 *
 *  A score out of 100 shown out of 10 flips on the vote that crosses .05, so
 *  the question is never "did the number change" but "did enough people
 *  change it". Measured over the first day of daily readings (2026-10-17, 199
 *  titles): of nine printed moves, four rode fewer than twenty new votes and
 *  one rode two. Those four are a rounding boundary being crossed and the
 *  page says so rather than reporting them as opinion shifting.
 *
 *  Twenty rather than a rounder hundred because this is a floor on arithmetic,
 *  not a judgement about significance: at 20 votes against a base of several
 *  hundred the average itself can genuinely have moved a point. */
export const VOTES_WORTH_CALLING_A_MOVE = 20;

/** The printed moves big enough to be about opinion rather than rounding. */
export function realMoves(daily: DailyScores | null): PrintedMove[] {
  if (!daily) return [];
  return daily.moves.filter(
    (m) => m.votes_gained !== null && m.votes_gained >= VOTES_WORTH_CALLING_A_MOVE,
  );
}

/** What a phase is called on the page. The data's own words are for the data. */
export const PHASE_LABEL: Record<SeasonPhase, string> = {
  airing: "On air",
  over: "Over",
  upcoming: "Not started",
};

/** A count as a share of its total, for a table that prints both.
 *
 *  The null marker rather than 0% where there is no total: a season nothing was
 *  asked about has no rate, and 0% would state the opposite of that. */
export function shareOf(part: number, whole: number): string {
  return whole === 0 ? NULL_MARKER : `${Math.round((part / whole) * 100)}%`;
}

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
/* Three, not four. Jikan - the community MyAnimeList mirror this project
 * fetched as a fourth source - had its public API discontinued on 1 October
 * 2026, after a brownout from September. It never landed a row here in the
 * project's whole life. Leaving it in this list made the masthead say "3 of 4
 * sources live", which reads as one being temporarily down rather than gone,
 * and MyAnimeList's own API now covers what the mirror was for. */
export const ALL_SOURCES = ["anilist", "kitsu", "mal"] as const;

const SOURCE_LABELS: Record<string, string> = {
  anilist: "AniList",
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

/** How often the sources have revised this score, or null where they have not.
 *
 *  WHY THIS IS NOT COMPUTED FROM score_history, which is right there and would
 *  be easier. Those points carry a run_date and a score and no vote count, so a
 *  pair reading the same value twice is indistinguishable between "asked again,
 *  unchanged" and "carried forward untouched" - and most rows in most runs are
 *  carried forward. Counting them is exactly the mistake /scores was built
 *  after making: it produced a clean, wrong table measuring the refetch
 *  schedule. A change entry exists only where a source reported something
 *  different, so counting those cannot invent a revision.
 *
 *  ATTRIBUTED, because an unattributed figure here contradicts the number above
 *  it. Dragon Ball Super shows 8.3 while its newest score change reads 8.0 to
 *  8.1: the first is the merged winner, the second is what AniList did to its
 *  own. Printed bare that is the site disagreeing with itself; with the source
 *  named it is provenance, which is the thing this project is for.
 *
 *  Says nothing when nothing moved, and that silence is load-bearing. The
 *  weekly run refetches only the current season, so an older title has been
 *  asked once: no change entries means "never re-asked", not "settled", and
 *  only 498 of 7,229 scored titles have any history at all. Among titles
 *  currently airing it is 66 of 76, which is where a reader is deciding.
 *
 *  What it cannot say is that a score HAS settled - that needs the vote count
 *  to tell a re-ask from a copy, which the detail response does not carry. The
 *  half that works is the actionable half: this number is still moving. */
export function scoreRevisions(changes: Change[] | null | undefined): string | null {
  const moves = (changes ?? []).filter((c) => c.field === "score" && c.old != null);
  if (moves.length === 0) return null;

  // changes arrive newest first (processing/changes.py), so the oldest entry's
  // `since` is when the sources were last agreed, and the newest is the latest
  // word on it.
  const newest = moves[0];
  const oldest = moves[moves.length - 1];
  const from = oldest.since ?? oldest.run_date;
  const COUNT: Record<number, string> = { 1: "once", 2: "twice", 3: "three times" };
  const times = COUNT[moves.length] ?? `${moves.length} times`;
  const who = joinSources(newest.sources ?? []);

  // A non-breaking space inside the date: balanced across two lines in a 15rem
  // rail this otherwise broke as "11 / October", and a date split over a line
  // end reads as two facts. U+00A0 only - the narrow no-break space the digest
  // normaliser strips is a different character and is not wanted here.
  const when = calendarDate(from).replace(" ", "\u00a0");
  return `Revised ${times} since ${when}, last by ${who}`;
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
  if (a.airing_unconfirmed) return false;
  return a.status === "current" && (!a.anilist_status || a.anilist_status === "current");
}

/** The Status fact. Where AniList overrules the sources it says so, because
 *  every other field on the page still comes from the sources that disagree.
 *  AniList is only asked about titles the sources call airing, so any other
 *  answer from it is an overruling.
 *
 *  Where it never answered at all and the premiere is over a year old, the
 *  sources' word is years stale and nothing can check it: the page says that
 *  rather than announcing a show is on the air this week on the strength of a
 *  2022 snapshot. */
export function statusLabel(a: Anime): string {
  const said = a.anilist_status;
  if (said && said !== "current" && STOPPED[said]) return `${STOPPED[said]}, per AniList`;
  if (a.airing_unconfirmed) return "Listed as airing, unconfirmed";
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

/* The kinds of change, in sections a reader would ask for rather than the
   field names the pipeline uses. Order is the page's order: what happened to a
   show first, what it is going to do next, then the numbers. */
export type ChangeSection = {
  key: string;
  title: string;
  fields: readonly string[];
  /** Narrows a field further, where one field carries two kinds of news. */
  where?: (change: Change) => boolean;
};

/** How the week's changes are grouped. "Seven episode counts" and "ten shows
 *  finished" are read differently, and one show can appear under two headings.
 *
 *  FIRST SCORED IS ITS OWN SECTION, and that split is the one that matters. A
 *  score change with no previous value is not a smaller version of 8.2 to 8.1 -
 *  it is the moment a title stops printing screened back and comes up in
 *  colour, which is the single event this whole design is built to show. They
 *  were mixed into "Score moves" and sorted among them by title, so on
 *  2026-10-15 eighty-nine of them were hidden inside a list of 147 that the
 *  page described as score moves. The one genuinely newsworthy class of change
 *  was invisible, and carried the same typographic weight as a 0.1 tick. */
export const CHANGE_SECTIONS: readonly ChangeSection[] = [
  { key: "status", title: "Finished and started", fields: ["status"] },
  { key: "dates", title: "Dates and seasons", fields: ["premiere", "season", "broadcast"] },
  { key: "episodes", title: "Episode counts", fields: ["episodes"] },
  { key: "first-scored", title: "First scored", fields: ["score"], where: (c) => c.old == null },
  { key: "score", title: "Score moves", fields: ["score"], where: (c) => c.old != null },
  { key: "watch", title: "Trailers and streaming", fields: ["trailer", "streaming"] },
  { key: "listed", title: "Newly listed", fields: ["listed"] },
];

/** The week's changes said in one line: how many, and the three kinds there
 *  were most of.
 *
 *  Three because the tail is long and uninformative - a week carries eight
 *  kinds and the smallest are a handful each, so listing them all turns a
 *  sentence into a table nobody reads. Derived from the feed rather than
 *  written down, for the same reason every other count on this site is: a
 *  number in the copy is wrong within a week.
 *
 *  Returns null under a threshold, because "the sources reported 2 changes
 *  this week" is not an invitation, it is an apology. */
export function changeSummary(
  changes: { field: string }[],
  least = 20,
): { total: number; kinds: { label: string; count: number }[] } | null {
  if (changes.length < least) return null;

  const counts = new Map<string, number>();
  for (const change of changes) {
    counts.set(change.field, (counts.get(change.field) ?? 0) + 1);
  }

  /* Short, because this renders in one sentence on the page people land on and
     every word of it is vertical space in front of the catalogue. "scores", not
     "scores moved": the sentence already says they changed. */
  const LABELS: Record<string, string> = {
    score: "scores",
    streaming: "streaming links",
    status: "starts and finishes",
    episodes: "episode counts",
    trailer: "trailers",
    listed: "newly listed",
    premiere: "premieres",
    season: "refiled seasons",
    broadcast: "broadcast slots",
  };

  const kinds = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 3)
    .map(([field, count]) => ({ label: LABELS[field] ?? field, count }));

  return { total: changes.length, kinds };
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
