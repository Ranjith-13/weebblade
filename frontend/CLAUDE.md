@AGENTS.md

# Frontend

Read `DESIGN.md` before changing anything visual. Most choices here are measured, not preferences.

## Direction

**Halftone Almanac — colour as certainty.** Only 39 of 142 titles have a score, so the design
spends its one colour on that fact: scored titles print in full colour with a flag-pink tab,
unscored ones drain to greyscale and screen back to visible halftone. A third state, diagonal rule
fill, covers the 37 titles with no artwork — that is a *separate* gap from a missing score and
must stay separate.

The certainty treatment is driven by `isKnown(anime)` over real data. **Never apply
`.plate-unknown` decoratively** — the moment it stops meaning "no score upstream", the whole idea
becomes ornament.

## Where the tokens live

`app/globals.css`, in the `@theme` block. That is the **single source of truth for every colour**.
`lib/design-tokens.ts` exports only variable *names* and composed patterns, so no hex is ever
duplicated. There is no literal hex anywhere in `app/`, `components/` or `lib/`; keep it that way.

Palette: `paper #E9E7E0` · `plate #DFDCD2` · `rule #C6C2B6` · `ink #15151A` · `ink-soft #5E5E66` ·
`flag #C2005E` · `data #1B3FBF`. Two signal colours only — a third is drift.

**Contrast is computed, not eyeballed.** The first draft's `#FF2E88` measured 2.83:1 (fails even
large-text AA) and `#6E6E75` measured 4.09:1 (fails body). Re-measure if you change a colour.

## Typefaces

**Bodoni Moda** (display) + **Archivo** (text), via `next/font/google`. Display sizes only for the
didone; its hairlines break up at body size.

**Fraunces and Instrument Serif are both banned here.** The first pass used Fraunces to avoid
Instrument Serif, which is swapping one generated-site default for the other. Justify a face
against this product or do not change it.

Do not add variable-font axes you do not actually vary. Fraunces briefly shipped `SOFT`, `WONK`
and `opsz` that no rule ever set, costing 82 KB (152 KB to 70 KB) for no visual difference.

## Banned

Inter, Geist, Roboto, Open Sans, Lato, Montserrat, Poppins, and system-font defaults. Purple/indigo
gradients. Cream-and-terracotta (`#F4F1EA` + `#D97757`). Rounded corners and drop shadows —
separation is hairline rules. ALL-CAPS tracked eyebrows used indiscriminately: `.stamp` is
for structural data labels only and must stay in single digits sitewide, `.meta` carries everything
else. Em-dashes in visible copy (the null marker on an unscored plate is the one exception).
Decorative dots or squares before labels. `01 / 02` numbering on a countable list. `·`-joined
metadata and `→` appended to link text. Uniform card grids where every item
carries equal weight regardless of what is known about it.

If a change would fit three other products, it is wrong.

## Data layer — three upstream bugs it works around

`lib/api.ts` fetches the whole season once and derives everything locally. Do not "optimise" this
back into per-view API calls; it is *fewer* upstream requests, and it is the only place these are
fixable:

1. **Pagination is unstable under `score_desc`** (103 NULL scores, no deterministic tie order).
   Three identical fetches returned 126 / 116 / 122 distinct titles. **`sort=title` is pinned in
   `getSeason()` and is load-bearing** — do not remove it.
2. **`popularity` is a rank, lower = more popular.** The API's only popularity sort returns the
   least popular first. Sorted locally.
3. **Genre facets are derived from the data.** A hardcoded list drifted and shipped a `Sci-Fi` chip
   that matched nothing.

Never render `studios`, `source_material`, `mal_id` (100% null) or `favourites` (0-25, noise).

## Seasons

The warehouse holds more than one season. `getCatalogue()` fetches every title once and the
per-season views are sliced from it locally, because the whole catalogue is a few hundred rows and
slicing beats a request per season.

`getSeason(key?)` and `getFacets(key?)` both default to the **newest season present**, derived from
the data - so backfilling an older season never changes what a bare URL shows. Ordering is by year
then the industry's quarterly order, not alphabetical: FALL sorts last in a year, not first.

Facets are scoped per season. Offering a genre chip that matches nothing in the season being viewed
is the same dead-control bug as the old hardcoded `Sci-Fi`, reached from a different direction.
Switching season therefore clears `genre` and `service`.

**Both sources tag a title to its START season only**, so a show that began in Spring and is still
airing appears under Spring, not Summer. Kitsu does this natively; MAL does not, and its season
endpoint returns everything *airing* in a season - One Piece and Sazae-san included, each carrying
its debut season. `ingestion/mal/fetch_season.py` drops those at ingest. Without it they reached
the warehouse and gave this switcher 30 phantom entries of one to three titles each.

**The sources disagree about the season for some titles** - nine live ones were Summer to Kitsu
and Spring to MAL. Consolidation therefore runs over the whole catalogue at once rather than per
season (`consolidate_catalogue`), because a season-scoped merge can never see both halves of such
a pair, and each one showed up as a duplicate on the site.

`getSeasons()` also enforces `MIN_SEASON_TITLES`: a season it offers should be a season we actually
ingested.

After a backfill, the frontend serves the previous season list for up to an hour - `cacheLife`
is doing its job. In dev, `use cache` survives a Fast Refresh; clear `.next` to see new data.

## The catalogue defaults to TV

`/browse` with no `format` param shows **TV only**, not everything. `resolveFormat()` in
`lib/types.ts` owns this: absent means `DEFAULT_FORMAT`, and `FORMAT_ALL` ("all") is the explicit
opt-out. LiveChart and AniChart both default to Television for the same reason.

The reason is measured. Re-measured 2026-09-09 over 228 titles, the gap is wider than at first
count: **TV is 75 titles at 81% scored**, while music videos are 51 titles at 15%, movies 31 at
22% and ONAs 60 at 30%. So a headline about how much of "the season" is unscored is mostly a
statement about music videos, not about anime.

Nothing is hidden. Every format keeps its own chip, "All formats" is one click, and the front page
states `Beyond TV` alongside the TV counts and links straight to `?format=all`. **Do not "simplify"
this back to one unfiltered grid** - it puts music videos in a list headed "rated highest", which
they can never be.

## Sparse fields: coverage is a design constraint

Measured across the full season, not a sample. An earlier 40-title sample overstated cover art at
~50% and trailers at ~80%; Kitsu's listing puts well-documented titles first, so the head lies.

Re-measured 2026-09-09 over the newest season (228 titles) after MAL joined. MAL supplies
studios, source material and scores but carries **no** slug, cover, trailer or streaming links, so
adding it raised some fields and diluted others. Both directions matter.

| Field | Coverage | Rule |
|---|---|---|
| `user_count` | 100% | Safe to rely on |
| `source_material` | 83% | MAL's contribution; was 0% before it |
| `studios` | 68% | Same |
| `rating_rank` | 64% | |
| `slug` | **61%** | **MAL rows have none.** `sourceUrl()` returns null; render no link, never a broken one |
| `score_100` | 43% | The whole certainty system exists for this |
| `streaming_services` / `_urls` | 36% | Show an honest "no link listed" when absent |
| `trailer_id` | 35% | Render the component or nothing |
| `broadcast_day` / `_time` | 29% | Drives the slot line and `NextAiring` |
| `cover_url` | **11%** | **Enhancement only. Never reserve space for it** |

`age_rating` needs `ageRatingLabel()`. Kitsu says `PG`/`R`/`G`, MAL says `pg_13`/`g`/`r`/`pg`, and
the two are different scales, so this is normalised for display only and never flattened into one
vocabulary - MAL's `pg_13` has no Kitsu equivalent and calling it `PG` would understate it.

`streaming_*` are parallel arrays; pair them with `streamingLinks()`. Junk URLs are dropped at
ingest, so anything reaching the client is a usable absolute link.

The trailer is a click-to-load facade (`components/Trailer.tsx`). **Do not swap it for a plain
iframe** — that ships ~500 KB of third-party JS and sets cookies on every view whether or not
anyone presses play.

## Caching is a rate-limit boundary, not a perf tweak

The API limits per client IP (60/min, 20/min on `/search`) and on Vercel every visitor shares the
app's egress addresses. Server reads use `'use cache'` + `cacheLife('hours')`; the pipeline
publishes weekly so this costs nothing in freshness.

**`/search` deliberately runs client-side** so each visitor spends their own budget on their own
queries. Do not move it to the server. Results carry no artwork from the API, so the server passes
a trimmed season lookup and the client joins locally.

`lib/types.ts` is client-safe; `lib/api.ts` imports `server-only`. Importing `API_BASE` from
`api.ts` into a client component drags `cacheLife` into the browser bundle and breaks the build.

## Motion

GSAP + ScrollTrigger via `@gsap/react`'s `useGSAP`, in `components/motion/`. **Do not add a second
animation library** — two libraries on the same elements fight over frames.

Every effect sits inside `gsap.matchMedia("(prefers-reduced-motion: no-preference)")` and uses
`gsap.from()`, so reduced-motion users get no animation and a JS failure leaves the page complete
rather than invisible. Transform and opacity only, so CLS stays 0.

Do not add: horizontal scroll hijack (breaks `/browse`'s filters, pagination and URLs), Three.js
(no 3D content), or Lenis (overrides native scroll, hurts fast scanning and accessibility).

Motion must be motivated. If you cannot say in one sentence what an animation communicates —
hierarchy, sequence, feedback, state change — do not add it.

## Verify before claiming

Run the build, then check in a real browser at 390 and 1440. Current gate results: 0 contrast
failures, 0 tap targets under the WCAG 2.2 24px minimum, CLS 0, visible focus on every control.

**Use the Playwright MCP browser, not the in-app Browser pane.** The pane cannot hydrate a PPR
page: it leaves React's postponed markers (`<!--$~-->`) unresolved, so every client component below
a Suspense boundary stays inert. Fibers attach to `body` and the static shell and stop — the
trailer button does not respond and `NextAiring` renders an empty `<p>`. The same page in Playwright
resolves to `<!--$-->` and hydrates fully. This cost a long debugging session chasing a component
that was never broken; if a client component looks dead in the pane, confirm in Playwright before
touching it.
