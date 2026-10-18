# WeebBlade — frontend

Next.js 16 (App Router) reading the public WeebBlade API. Deployed separately from the backend:
Vercel builds this directory, while the API runs as a container on Render (`weebblade-api.onrender.com`).

Design intent lives in [`DESIGN.md`](./DESIGN.md) — read that before changing visual decisions;
most of them are deliberate rather than defaults.

## Running it

```bash
npm install
npm run dev
```

Defaults to the live API. To point elsewhere, set `NEXT_PUBLIC_API_BASE_URL` (e.g. a local backend
on `http://localhost:8000`).

## Three things worth knowing before changing the data layer

**Caching isn't a performance nicety here, it's a rate-limit boundary.** The API limits requests
per client IP (60/min, 20/min on `/search`), and on Vercel every visitor shares this app's egress
IPs — uncached passthrough would spend one shared budget on behalf of the whole audience. Every
server-side read in `lib/api.ts` is therefore wrapped in `use cache` + `cacheLife('hours')` — an
hour sits well inside the interval anything moves in, since the pipeline publishes daily and
refetches the catalogue weekly.

**Search is the deliberate exception.** `app/search/SearchClient.tsx` fetches from the browser, so
each visitor spends their own rate-limit budget on their own unique queries. Server-side caching
would buy nothing for queries nobody repeats, and search results have no SEO value worth
prerendering.

**The whole season is fetched at once, and that is deliberate.** `getSeason()` pulls the whole
season - 233 to 370 titles, three or four requests of 100 - caches it, and derives every filter,
sort, facet and page locally. It is
*fewer* upstream requests than passing filters through, and it is the only place three upstream
behaviours can be corrected:

1. **Pagination is unstable under the default sort.** `score_desc` orders by
   `score_100 DESC NULLS LAST` over 103 NULLs in the one-season catalogue, so ties have no deterministic order and
   `LIMIT/OFFSET` slices a differently shuffled result each call — three identical two-page
   fetches returned 126, 116 and 122 distinct titles. `sort=title` is stable and is pinned in
   `getSeason()`. **Do not remove it.**
2. **`popularity` is a rank** — lower is more popular — and the API's only popularity sort returns
   the least popular first. Sorted locally instead.
3. **Genre facets are derived from the data.** A hardcoded list had drifted and offered a `Sci-Fi`
   chip that matched nothing (the real tag is `Science Fiction`).

Because of that split, `lib/` is two modules on purpose:

- `lib/types.ts` — types, `API_BASE`, pure formatters. Safe to import from client components.
- `lib/api.ts` — server-only fetchers. Imports `server-only`, so importing it from a client
  component fails the build with a message naming this file rather than a confusing Pages Router
  error.

## Known trade-off

Detail routes stream inside `<Suspense>` (required by Cache Components when reading `params`),
which means a `notFound()` for a nonexistent title renders the correct 404 UI but responds `200` —
the status is already committed once streaming starts. Fine for a project where those URLs aren't
linked anywhere; switching to `export const instant = false` would restore a real 404 status at the
cost of blocking first paint.
