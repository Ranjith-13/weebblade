import "server-only";
import { cacheLife } from "next/cache";
import {
  API_BASE,
  ApiError,
  type Anime,
  type AnimeListResponse,
  type AnimeQuery,
  type Digest,
} from "./types";

/* Server-only data layer. The client-safe pieces (types, API_BASE, pure
 * formatters) live in ./types so the browser bundle never pulls `cacheLife` in.
 * The "server-only" import above turns that mistake into a build error naming
 * this file, rather than the confusing Pages-Router error it produces
 * otherwise. */

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
  if (!res.ok) {
    throw new ApiError(res.status, `${res.status} from ${url}`);
  }
  return res.json() as Promise<T>;
}

/* Every read below is cached. The upstream API rate-limits per client IP
 * (60/min, 20/min on search) and all visitors share this app's egress IPs, so
 * uncached passthrough would spend one shared budget for the whole audience.
 * The pipeline publishes weekly, so an hour of staleness costs nothing real.
 * Search is deliberately absent here - it runs client-side (see
 * app/search/SearchClient.tsx) so each visitor spends their own budget on their
 * own unique queries. */

export async function getAnimeList(query: AnimeQuery = {}): Promise<AnimeListResponse> {
  "use cache";
  cacheLife("hours");
  return getJson<AnimeListResponse>(buildUrl("/anime", { ...query }));
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
    // 503 is the documented "no digest generated yet" state, not a failure -
    // the home page renders an honest empty state rather than an error.
    if (err instanceof ApiError && err.status === 503) return null;
    throw err;
  }
}

export async function getDigestDates(): Promise<string[]> {
  "use cache";
  cacheLife("hours");
  return getJson<string[]>(buildUrl("/digest"));
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
