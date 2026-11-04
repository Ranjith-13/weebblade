# Frontend Architecture & Engineering Specification

Read `DESIGN.md` before changing anything visual. Most choices here are measured, not preferences.

## Direction

**Halftone Almanac - colour as certainty.** The design spends its one colour on whether a title
has a score: scored titles print in full colour with a flag-pink tab, unscored ones drain to
greyscale and screen back to visible halftone. It was drawn when 39 of 142 titles had one. With
MAL and AniList beside Kitsu, a settled season's TV is ~88-90% scored - but the default view is
never a settled season. It is the newest that has started, which is always the least scored:
Fall 2026 is 27% screened back against Summer 2026's 10% (measured 2026-10-14). And not the
rest regardless: in Summer 2026,
17 of 62 ONAs and 8 of 59 music videos (measured 2026-09-14). So the screened-back state is a
quarter of the TV default and the majority one format chip away - 56% of Fall 2026 across all
formats. A third state, diagonal rule fill,
is for a title with no artwork - a *separate* gap from a missing score, and it must stay
separate, though posters now cover 99.9% of the catalogue.

The certainty treatment is driven by `isKnown(anime)` over real data. **Never apply
`.plate-unknown` decoratively** - the moment it stops meaning "no score upstream", the whole idea
becomes ornament.

## Where the tokens live

`app/globals.css`, in the `@theme` block. That is the **single source of truth for every colour**.
`lib/design-tokens.ts` exports only variable *names* and composed patterns, so no hex is ever
duplicated. There is no literal hex anywhere in `app/`, `components/` or `lib/`; keep it that way.

Palette: `paper #E9E7E0` · `plate #DFDCD2` · `rule #C6C2B6` · `ink #15151A` · `ink-soft #5E5E66` ·
`flag #C2005E` · `data #1B3FBF`. Two signal colours only - a third is drift.

**The reader can choose: System / Light / Dark, in the footer** (`components/ThemeChoice.tsx`),
with System the default because most people have already told their OS and a site that asks again
did not listen. The choice is an attribute on `<html>`; the media query answers for everyone who
never touches it, including anyone with JS off.

**The masthead carries a second control, and it is two-state on purpose.** `ThemeToggle` flips
light/dark only: the header is where someone reaches when the page is too bright to read *now*,
which is a one-tap question, while "System" is a preference and belongs where preferences are set.
Picking System in the footer hands control back to the OS. Two controls over one value, so they
share the store and a local change dispatches its own event - `storage` fires in *other* tabs only,
and without that the footer sat on a stale "System" after the header had moved the page, which
looks exactly like a control that did nothing. The e2e suite asserts the two agree.

It flips against what the reader is **looking at**, not what they chose, so it resolves System
against `matchMedia` and subscribes to it: a reader on System who changes their OS theme sees the
label change under them rather than being offered the mode they are already in. The label names the
action ("Dark" = make it dark), never the state, and it carries the chip border every other control
here has - set in plain `.meta` beside the wordmark it printed "WeebBlade  Dark", which reads as the
name of an edition rather than as a thing to press.

**It rides with the wordmark, not with the nav, and that is a measurement.** See the nav budget
below; putting a sixth control in that row gave the site its first horizontal scrollbar.

**`THEME_KEY` lives in `lib/types.ts`, not in the component, and that is not tidiness.** The root
layout is a Server Component and needs the string to build the blocking script that applies a
stored theme before first paint. Importing it from a `"use client"` module hands a Server
Component a client *reference* instead of the value, so the script shipped as
`localStorage.getItem(undefined)`: it compiled, it ran, and it silently did nothing while every
reload flashed light. The smoke suite now asserts the applied theme at `domcontentloaded`, before
hydration, because a test that waits for the page to settle passes on a site that flashes.

The control is an external store, not `useState` + `useEffect` - `localStorage` *is* external
state, and the `set-state-in-effect` rule objects to the alternative, as it does for `Airing.tsx`.

**The attribute now lands a frame AFTER the click**, because the flip runs inside a View
Transition and that API snapshots the old state before calling back. `localStorage` and the
`CHANGED` event are still synchronous, so both controls re-render at once while the page's
colours cross-fade - which is the intended effect, not a lag. Anything reading `data-theme`
straight after a click is racing it: the smoke suite did, passed on desktop and failed on
phone, which is the worst shape a test can have. Use a retrying assertion
(`toHaveAttribute`), never a single read.

**Dark mode is a palette swap, not a second design.** `@media (prefers-color-scheme: dark)` in
`globals.css` redefines the same variables; both signal hues are preserved exactly (flag 331°,
data 227°) and only lightness moves. Dark `--color-ink` is the light palette's paper. No component
is mode-aware, and the halftone needs no variant because its dots are `--color-paper`. The social
card deliberately stays light: `opengraph-image.tsx` regex-reads the FIRST match in the file, so
**never move the dark block above `@theme`**. The smoke suite computes contrast in both modes.

**Contrast is computed, not eyeballed.** The first draft's `#FF2E88` measured 2.83:1 (fails even
large-text AA) and `#6E6E75` measured 4.09:1 (fails body). Re-measure if you change a colour.

## Typefaces

**Bodoni Moda** (display) + **Archivo** (text), via `next/font/google`. Display sizes only for the
didone; its hairlines break up at body size.

**Fraunces and Instrument Serif are both banned here.** The first pass used Fraunces to avoid
Instrument Serif, which is swapping one generated-site default for the other. Justify a face
against this product or do not change it.

**A native title is tagged with the language it is in** (`scriptLang()` in `lib/types.ts`, used on
the title page's secondary line). `<html lang="en">` was the only language declaration on the site,
so every Japanese and Korean title was announced to a screen reader in English and hyphenated by
English rules. It is detected from the script, not from the source's metadata, which does not carry
one. **Han alone is deliberately not claimed**: this catalogue holds Chinese donghua beside Japanese
titles and kanji cannot tell them apart, so an undeclared string stays undeclared rather than being
labelled wrongly - `ja` on a Chinese title is worse than the inherited `en`, because it is confident.

Do not add variable-font axes you do not actually vary. Fraunces briefly shipped `SOFT`, `WONK`
and `opsz` that no rule ever set, costing 82 KB (152 KB to 70 KB) for no visual difference.

## Banned

Inter, Geist, Roboto, Open Sans, Lato, Montserrat, Poppins, and system-font defaults. Purple/indigo
gradients. Cream-and-terracotta (`#F4F1EA` + `#D97757`). Rounded corners and drop shadows  - 
separation is hairline rules. ALL-CAPS tracked eyebrows used indiscriminately: `.stamp` is
for structural data labels only and must stay in single digits sitewide, `.meta` carries everything
else. Em-dashes in visible copy (the null marker on an unscored plate is the one exception).
Decorative dots or squares before labels. `01 / 02` numbering on a countable list. `·`-joined
metadata and `→` appended to link text. Uniform card grids where every item
carries equal weight regardless of what is known about it.

**The em-dash ban is enforced by `eslint.config.mjs`**, not by remembering it: it was broken three
times after being written into DESIGN.md, once as `&mdash;` where grepping for the character found
nothing. Any em-dash in JSX text, a string or a template under `app/`, `components/` or `lib/` is a
lint error. The one legitimate use, the null marker in tabular data, is `NULL_MARKER` from
`lib/types.ts`. Comments are not matched. The en-dash in `A–Z` is a range and is fine.

**The digest quotes scores at the scale the site prints**, which it did not until 2026-10-18.
`ai/digest/prompt.py` handed the model `83.63/100` straight out of the warehouse, so the prose
said "an 83.63 rating" on a page whose every other element said 8.4: two numbers for one thing,
and two decimal places this product uses nowhere. The prompt was inconsistent with itself as
well, since score *changes* were already described "out of 10" a few lines above.

`_out_of_ten()` matches `scoreOutOfTen` exactly, and that is finer than it looks. The site is
`(score100 / 10).toFixed(1)`; Python's `round()` rounds halves to even and gives 7.2 where the
site shows 7.3. It quantizes the **float** rather than its string, because `83.5 / 10` is
8.34999999999999964 and `toFixed` sees that too, so both answer 8.3 where `Decimal("8.35")`
would answer 8.4. Checked against node for seven values. The model is also told the rule, since
one handed 8.4 can still decide to write 84% or 8.36.

**The digest is repunctuated on the way out of `lib/api.ts`** (`plainPunctuation`), because it is
the one block of prose here nobody wrote and the home page prints its lead. Punctuation only, never
words. The e2e suite asserts the rendered `.digest-prose` carries no em-dash, non-breaking hyphen
or narrow no-break space, and that assertion was checked by disabling the normaliser and watching
it go red. If you change what it does, `/digest`'s intro paragraph describes it to readers and has
to keep matching.

If a change would fit three other products, it is wrong.

## Data layer - three upstream bugs it works around

`lib/api.ts` fetches the whole season once and derives everything locally. Do not "optimise" this
back into per-view API calls; it is *fewer* upstream requests, and it is the only place these are
fixable:

1. **Pagination is unstable under `score_desc`** (103 NULL scores in the one-season catalogue, no
   deterministic tie order; over half of a season's non-TV is still unscored).
   Three identical fetches returned 126 / 116 / 122 distinct titles. **`sort=title` is pinned in
   `getSeason()` and is load-bearing** - do not remove it.
2. **`popularity` is a rank, lower = more popular.** The API's only popularity sort returns the
   least popular first. Sorted locally.
3. **Genre facets are derived from the data.** A hardcoded list drifted and shipped a `Sci-Fi` chip
   that matched nothing.

Never render `favourites`: each source's own count on its own site, a median of 0 and up to
7,740 on AniList (2026-09-14), so it says which site a row came from as much as anything. `studios`, `source_material` and `mal_id` were on this
list when Kitsu was the only source and all three were 100% null; MAL supplies all three, so the
first two lead the facts list and `mal_id` is what `sourceLinks()` uses to reach MyAnimeList.

## Seasons

The warehouse holds twenty-two seasons (Fall 2021 to Winter 2027, 6,359 titles on 2026-10-14),
and **a page reads
one of them, never the catalogue.** `getSeason(key)` fetches that season whole (`sort=title`, 100
a page) and every view is derived from it as before. Nothing fetches the whole catalogue:

- the season list, the sources and the total come from `GET /catalogue` (`getCatalogueSummary`),
  one small request;
- a studio's titles, the one question that spans seasons, come from `/anime?studio=` (`getStudio`),
  and a studio view loads no season at all: its chips are built from its own titles (`facetsOf`);
- search results arrive from the API with their poster, score and format, so `/search` no longer
  ships a lookup of every title.

It used to be one `getCatalogue()` that every page shared, sliced locally. Fine at 481 titles;
after the backfill it was 28 requests per cache period, and five years of history would have gone
over the API's 60 a minute and taken the site down. Measured 2026-09-11, production builds of both
on one machine against the live API:

| | Whole catalogue (before) | Per season (now) |
|---|---|---|
| Cold render of a season | 28 requests, 4.4s | 4 requests (summary + 3 pages), 0.9s first, 0.3-0.5s after |
| Studio view | from the catalogue | 1 request, 0.4s |
| `/search` HTML | 514 KB | 22 KB |
| Build-time page generation | 6.7s | 1.9s |
| As the catalogue grows | +1 request per 100 titles, on every page | unchanged; only one season's size counts |

So **backfill depth no longer touches the frontend.** What can still move a render is the size of a
single season, and `backfill.py` reports the largest season's request count for that reason. Do not
reintroduce a read of the whole catalogue: if a new view seems to need one, it needs an API
endpoint that answers the question instead, the way `/catalogue` and `studio=` do.

`getSeason(key?)` and `getFacets(key?)` both default to the **newest season present**, derived from
the data - so backfilling an older season never changes what a bare URL shows. Ordering is by year
then the industry's quarterly order, not alphabetical: FALL sorts last in a year, not first.

Facets are scoped per season. Offering a genre chip that matches nothing in the season being viewed
is the same dead-control bug as the old hardcoded `Sci-Fi`, reached from a different direction.
Switching season therefore clears `genre` and `service`.

### Getting to a season

Ten seasons were on file and the site hid nine of them: the header linked to "The season",
singular, the front page named one season in its largest type, and the only switcher was the first
of six chip rows inside `/browse`'s filter block. So there are now three ways in, and one index:

- **The season index** (`components/SeasonIndex.tsx`) is a native `popover` rendered once in the
  layout, listing every season by year with its count and one sentence on what a season is here.
  Anything with `popoverTarget={SEASON_INDEX_ID}` opens it: the header's **Seasons** button, the
  `/browse` heading, the front page's masthead. Being a popover it opens without JS, closes on
  Escape or an outside click, and sits in the top layer where no `overflow` can clip it. It scrolls
  twenty-two seasons, so it carries `overscroll-behavior: contain`: without it, reaching the end of
  the list chains the scroll into the catalogue standing behind, and the reader loses their place in
  both at once. It prerenders
  with nothing marked current (a layout gets no `searchParams`) and the live version marks the season
  in view and closes itself on navigation.
- **`/browse`'s heading is the season's name**, with its earlier and later neighbours beside it. The
  season chip row is gone from the filter block; do not put it back there.
- **A title page links into its own season.** Its genres, format, source material, the new Season
  fact and the back link all carry `season=`, and `format=all` when the title is not TV (the browse
  default would hide it from its own results). Before this they dropped the season, so on any older
  title a genre click opened the *newest* season: Iyashikei from Laid-Back Camp 3 (Spring 2024) found
  nothing. A genre below the four-title chip threshold still filters, and `/browse` shows it as the
  active chip so it can be seen and cleared.

The header marks the current section with a flag bar laid over its ink rule. That reads the pathname
in a client component, which suspends during prerender on routes with an unknown param, so it sits in
`<Suspense>` with the same nav, unmarked, as the fallback. Without that boundary the build fails.

**The sources tag a title to its START season only**, so a show that began in Spring and is still
airing appears under Spring, not Summer. Kitsu and AniList do this natively; MAL does not, and its season
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

## Title addresses

A title page lives at **`/anime/{wb_id}`**, the title's stable identity (`processing/identity.py`).
Build every link with `titleHref()` in `lib/types.ts`; never compose `/anime/{source}/{source_id}`.
That old address named whichever source won the title's merge that week, so it moved whenever the
winner did and every link made before broke.

- **`proxy.ts` answers the old form with a 308** to the identity address. The API resolves any source
  key a title was ever made of, including one that since lost its merge (`mal/58877` reaches Ace of
  the Diamond act II S2, whose page Kitsu's row now wins). An unknown key falls through to a real
  404. It is in the proxy because a redirect thrown inside a streamed page becomes a client-side
  meta refresh with a 200; the proxy runs before rendering.
- **A merged identity still answers.** Its page loads the survivor from the API and redirects to
  the survivor's address (client-side, in the stream) with a canonical link. Merges are too rare to
  justify an API call in the proxy on every title view.
- **`getTitle` returns `null` for a missing title rather than throwing.** An error leaving a
  `"use cache"` function does not reliably arrive as the same class; a thrown 404 was recognised by
  the page and missed by its metadata, which then served an indexable page titled "Title".
- **A not-found inside a streamed page is a 200 with `noindex`**, never a 404: the status is sent
  with the shell. Only the proxy can send a real 404, which is why an unknown old key gets one and
  an unknown identity does not. Keys not shaped like an identity are rejected before any API call.

## Franchises

A title page ends with its franchise (`components/Franchise.tsx`), from
`GET /anime/{wb_id}/franchise`: every title joined to it by MAL's story relations, oldest first.
What joins a franchise, and why shared characters and MAL's "other" do not, is in
`processing/franchise.py`.

- **It lists titles the catalogue does not hold.** The prequel from before Fall 2021, an
  announced sequel: the API describes them from MAL's relation data, with no `wb_id`. They link
  to MyAnimeList and say "On MyAnimeList", and they are screened back, because there is no score
  for them here. That is the certainty treatment meaning what it always means, not a new state.
- **A listing, not a grid,** like the schedule: the year is the column the eye runs down, the
  relation to this title (Prequel, Side story) sits on the right, and this title is marked where
  it falls. Two columns on a wide screen, filled top to bottom so it still reads as a timeline.
- **Long franchises open on the twelve entries around this title** (`FranchiseList`), with the
  rest behind "Show all". Gundam runs to 130 and Detective Conan to 129; the entries next to this
  one are the ones anyone came for.
- **It never takes the page down.** The section streams in its own `<Suspense>` after the title,
  a failed franchise request renders nothing, and a title in no franchise gets no section.

## More like this

The last block on a title page (`components/Similar.tsx`), from
`GET /anime/{wb_id}/similar`. **Below the franchise, deliberately**: the franchise is the rest
of *this* story and is a fact; this is a guess about what else to watch, and the order says
which is which.

**It is not the search index, and that is the whole feature.** It was logged as free - one
`array_cosine_similarity` against a vector already built and published - and on the live
catalogue that returns puns. The search document leads with every name a title has, because
that is what took "type the other name and find it" from 10/40 to 22/40, so the vector matches
on names: *Blue Box Season 2* came back beside *The Blue Orchestra Season 2*, *The Fire Hunter
Season 2* and *Pacific Rim: The Black Season 2*. A second document, of genres and synopsis with
no names at all, takes the mean genre overlap of the five nearest neighbours from 0.290 to
0.402 and makes the examples sane: Blue Box finds school romances, SPY x FAMILY finds Buddy
Daddies, BOCCHI THE ROCK! finds BanG Dream. All of the reasoning, and the three filters it
needs to be usable, are in `ai/search/similar.py`.

- **A title with no synopsis gets no block**, and is nobody else's neighbour. 533 titles have
  none; giving them a shape line instead made two blanks identical and served each to the other
  as a perfect match.
- **Its own franchise is excluded** at build time. The section directly above lists it in full.
- **The caption has to keep matching what it does.** It says "nearest by genre and synopsis,
  not by popularity, rating, or what anyone else watched next", because a block headed "More
  like this" otherwise reads as a recommendation engine, and nothing here knows what is good.
- **Quality is uneven and that is honest.** Tight clusters work (romance, slice-of-life, music);
  broad fantasy does not - Frieren's nearest are generic isekai. A sequel's neighbours are 69%
  sequels against a 15% base rate, because sequel synopses say "the second season of".
- Streams in its own Suspense with the footer guard, renders nothing on failure, and is empty
  rather than broken on a warehouse published before the table existed.

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

Re-measured over the newest season: on 2026-09-09 (228 titles) after MAL joined, and on
2026-09-14 (237 titles) after AniList joined. MAL supplies studios, source material and scores but
carries **no** slug, cover, trailer or streaming links; AniList, ranked below both, fills banners,
trailers, streaming links and scores where they have none. Each source raised some fields and
diluted others. The TV column is what `/browse` shows by default.

| Field | 09-09 | 09-14 | 09-14, TV | Rule |
|---|---|---|---|---|
| `user_count` | 100% | 100% | 100% | Safe to rely on |
| `source_material` | 83% | 90% | 96% | MAL's contribution; was 0% before it |
| `studios` | 68% | 72% | 96% | Same |
| `rating_rank` | 64% | 64% | 91% | |
| `slug` | **61%** | 62% | 91% | **MAL rows have none.** `sourceUrl()` returns null; render no link, never a broken one |
| `score_100` | 43% | 44% | 88% | The whole certainty system exists for this. **Stored /100, displayed /10** |
| `streaming_services` / `_urls` | 36% | 51% | 93% | Show an honest "no link listed" when absent |
| `trailer_id` | 35% | 56% | 93% | Render the component or nothing |
| `broadcast_day` / `_time` | 29% | 28% | 85% | The slot line and `NextAiring`, where AniList has no airdate |
| `cover_url` | **11%** | **32%** | 69% | **Enhancement only. Never reserve space for it** |

**A poster URL being present does not mean there is a poster.** Six of them 404 at Kitsu's
origin. The title carries a `poster_url`, so an `<Image>` is rendered, and because `alt=""` a
failed one draws nothing at all - not even a browser's broken-image icon - so the largest plate
on a title page was an empty bordered box. The name is therefore rendered **underneath** every
poster rather than instead of it: a poster that loads covers it completely (`object-cover`,
asserted in the smoke suite), and a dead one reveals the design's own treatment.

Costs nothing and needs no liveness check at ingest, which is 6,359 HEAD requests a week and is
why it was never done. **The diagonal rule stays conditional on `poster_url` being absent**: it
means "no artwork registered", and laying it under every plate would give it a second meaning,
"not arrived yet", which is the same objection DESIGN.md makes to animating the halftone. The
plate tone is neutral and says nothing, so that is what every plate gets.

Scores are **stored out of 100 and shown out of 10** - `scoreOutOfTen()` and `SCORE_MAX` in
`lib/types.ts` own that, and the browse plate, the detail page and the search plate all go through
them. Storage keeps Kitsu's native scale because that is what the warehouse holds and what MAL's
0-10 is converted up to at ingest; the display is /10 because that is what readers expect from a
ratings site. Do not divide by 10 at a call site - three of them drifting apart is exactly what the
helper exists to prevent.

`age_rating` needs `ageRatingLabel()`. Kitsu says `PG`/`R`/`G`, MAL says `pg_13`/`g`/`r`/`pg`, and
the two are different scales, so this is normalised for display only and never flattened into one
vocabulary - MAL's `pg_13` has no Kitsu equivalent and calling it `PG` would understate it.

`streaming_*` are parallel arrays; pair them with `streamingLinks()`. Junk URLs are dropped at
ingest, so anything reaching the client is a usable absolute link.

The trailer is a click-to-load facade (`components/Trailer.tsx`). **Do not swap it for a plain
iframe** - that ships ~500 KB of third-party JS and sets cookies on every view whether or not
anyone presses play.

## The API and this app race on every push

Render replaces a free container rather than draining it, so around a deploy its proxy answers
**502** with nothing behind it. Both the CI build and the Vercel build prerender against the live
API at exactly that moment, and a single 502 took the whole build down twice in two days - the
second time on the very commit whose deploy it was racing.

`getJson` in `lib/api.ts` retries **502, 503 and 504** and network errors, three times, backing off
2s / 6s / 15s. About 23 seconds, which is proportionate rather than arbitrary: this app already
waits ~32s for a sleeping container with no fetch timeout at all. It is not meant to ride out a
long outage - a build that waits that long *should* go red, because a Vercel deploy made then
would have failed too.

**503 is retried too, since 2026-10-23, and excluding it was half right.** From `get_db` it means
the warehouse is not on disk, which does not clear in seconds - that is one source. The other is
Render's edge answering while no instance is healthy, which clears exactly the way 502 does, and
nothing in the status tells them apart. CI went red on `f0199cc`, a backend-only commit: the API
image rebuilt, Render swapped the container, and the frontend job took 503 on `/catalogue`,
`/changes` and `/_not-found` inside the same second. Every route at once is what "no backend"
looks like. Retrying costs ~23 seconds on the day the API genuinely has nothing and ends in the
same red build; not retrying costs a red build on every push that touches `backend/`.

**`_retry=N` on the URL is load-bearing and looks like debris.** Next memoises `fetch` by URL
within a render pass, so retrying the identical URL is answered from that memo and **no request
leaves the process**. Measured against a stub that failed its first three calls: without the
parameter the build made one request per caller and died; with it, `/catalogue` was asked at 0s,
2s and 6s and the third answered. `cache: "no-store"` does **not** defeat the memo. Remove the
parameter and the retry silently becomes a no-op that still looks correct.

Checked both ways with the cache cleared each time - with the retry the build exits 0, without it
exits 1, same stub. `lib/api.ts` is `server-only`, so none of this runs in a reader's browser;
`/search` does its own fetch from the client and is untouched.

## Caching is a rate-limit boundary, not a perf tweak

The API limits per client IP (60/min, 20/min on `/search`) and on Vercel every visitor shares the
app's egress addresses. Server reads use `'use cache'` + `cacheLife('hours')`; the pipeline
publishes daily and refetches the catalogue weekly, so an hour of cache sits well inside the
interval anything actually moves in. (It published weekly until 2026-10-19, which is why the
freshest daily score reading a reader could see was sometimes eight days old.)

**`/search` deliberately runs client-side** so each visitor spends their own budget on their own
queries. Do not move it to the server. Results carry no artwork from the API, so the server passes
a trimmed season lookup and the client joins locally.

**Enter is guarded against the IME, and on this catalogue that is not an edge case.** While an
input method is composing, Enter confirms the candidate it is offering; it does not submit. So
typing `ゆるキャン` and pressing Enter to pick the kanji submitted the half-formed kana instead,
spending one of the reader's 20 queries a minute on a string they never meant to send and replacing
the box's contents mid-thought. `e.nativeEvent.isComposing` is the browser saying the IME still owns
the keystroke; preventing the default stops only the submit. The e2e assertion is on the **network**,
not on the handler, because a guard that calls `preventDefault` on an event nobody submits would
pass a DOM-level test and still be wrong.

`lib/types.ts` is client-safe; `lib/api.ts` imports `server-only`. Importing `API_BASE` from
`api.ts` into a client component drags `cacheLife` into the browser bundle and breaks the build.

## Airdates and countdowns come from AniList

AniList publishes the broadcast schedule episode by episode, and a daily DAG
(`airflow/dags/anilist_airing.py`) lands every episode airing in the next six weeks, plus the
day behind. MAL has only a weekly slot and Kitsu fills episode dates in after they air, so before
AniList came back the site could say when a show *usually* airs and never when this week's episode
does. Two places use it:

- **A title page** carries its next few episodes (`upcoming_episodes` on `GET /anime/{wb_id}`) and
  shows the first one still ahead: "Episode 11 of 12 airs Monday 14 September, 20:57 JST", then a
  live countdown and the reader's own time (`EpisodeCountdown`). Several episodes, not one,
  because the page is cached for an hour and the first may have aired since. Where AniList has no
  airdate, the MAL slot block below it is shown instead, caveat and all - **but only while the
  show is airing** (`isAiring`). MAL keeps the slot on a finished show, and 986 finished titles
  counted down to a "next slot" for a series that was over.
- **AniList settles whether a show is still airing, in the warehouse.** The merged status is the
  winner's as of the title's snapshot, so it calls shows airing long after their finale. The daily
  DAG asks AniList about exactly the titles the sources call airing, and `anime_media_latest`
  corrects `status` from the answer, so every list agrees: browse's airing tabs and the front
  page's counts as much as the title page. `merged_status` keeps what the sources said;
  `anilist_status` is AniList's own word. A hiatus leaves `status` "current" (the series is
  running, and there is no shared word for a pause), which is why "airing" in the frontend means
  `isAiring()`, not `status === "current"` - use it everywhere. Where AniList overrules the
  sources, the Status fact says "Finished, per AniList", naming the source, because every other
  field still comes from the ones that disagree. The first check hid 34 slots, Yu-Gi-Oh! Go
  Rush!! (finished March 2025) among them; 80 of the 1,100 remain.
- **A title page also lists what has already aired**, from `aired_episodes`. That is a
  *different read* from the countdown above it: `anime_airing` holds only the current fetch,
  so an episode left the site the morning after it went out and a show seven episodes into a
  twelve episode season could say when episode eight was due and nothing whatever about the
  seven anyone had watched. `anime_airing_history` globs the dated files instead - they were
  always being written and kept, and nothing read them. 1,198 episodes against the current
  fetch's 719, and **544 already aired against 67** (2026-10-19). An episode is listed once,
  **as the schedule last had it**: a broadcast that slips is corrected at the next daily check
  and 87 of the first month's episodes were rescheduled, so keeping the earliest reading would
  archive the schedule as announced rather than as it happened. Shown whether or not the title
  is still airing, because a finale's date is a fact about a finished show too.
- **`/schedule`** is the next seven days of `GET /schedule`, one column per day in Japan. Each row
  is the time in Tokyo with its countdown under it, then the title, episode, format and the
  reader's own time. Shows the catalogue does not hold (One Piece, Detective Conan, long-runners
  older than it) are listed as AniList has them, screened back, and link to AniList.

**The columns are JST, and calendar days.** This looks wrong and is not: many of these broadcast
late at night in Tokyo, so a Monday 00:26 episode is Sunday evening across the Americas. Grouping
by the reader's day would mean the server cannot render the page at all. So Japan's time is
rendered on the server, the reader's own is added in the browser, and the intro says which is
which. A 00:26 broadcast opens its day rather than closing the previous evening's, because the data
reports calendar days.

**Japan's dates are formatted by hand, not with `Intl`** (`jstAirdate`, `dayKeyLabel` in
`lib/types.ts`). They render on the server and hydrate in the browser, and Node's ICU and a
browser's abbreviate September differently ("Sept" against "Sep"): a hydration mismatch waiting on
the calendar. The reader's own time uses `toLocaleString`, but only after mount, where nothing
has to agree with the server.

**One clock for the page** (`components/Airing.tsx`): a `useSyncExternalStore` store that polls
every 15 seconds and notifies when the minute changes, so a hundred countdowns move together
instead of a hundred intervals re-rendering out of step. Its server snapshot is null, which is how
every component knows to render nothing clock-dependent during SSR and hydration. Not `useState` +
`useEffect`: two lint rules object to that (`set-state-in-effect`, `purity`), rightly.

**Layout shift is designed out, and measured at 0** on `/schedule` at 390 and 1440 against a
production build:

- the countdown sits under the Tokyo time, not at the end of the meta line, because that line is
  nowrap and clips, and the countdown is the one thing on a row that must not be clipped;
- every row's meta line and countdown hold their height before the clock arrives;
- "Today in Japan" is rendered in every column and hidden in all but today's, because arriving
  from nothing it pushed the day's count aside;
- the week streams in behind its fallback even from a prerendered page, and the footer waits
  for it (`data-footer-waits`, below): in view under the fallback, it was pushed off at 1440
  when the week arrived (0.09).

Measured the first week: 112 episodes of 110 shows. Of the 62 Summer titles MAL still called
airing with a weekly slot, 54 were on AniList's week; of the other eight, three had finished
between 9 and 11 September, two were on a break, and AniList had no dates for three.

## What changed, per source

A title page lists what its sources have reported differently from one fetch to the next
(`anime.changes`, from `processing/changes.py`), newest first, each change a sentence from
`changeSentence()` in `lib/types.ts` with the sources that reported it.

- **Render it only when there is a history.** The weekly run refetches the current season
  alone, so most older titles have none; an empty section would say "nothing changed" about a
  title that was simply not being watched.
- **Keep every change attributed.** Two sources' scores for one title differ and move
  separately - on 13 September one title went 7.5 to 7.4 on Kitsu and 7.1 to 7.0 on MAL - so a
  score change without its source reads as a contradiction of the score beside it.
- It renders with the title body, inside the same Suspense boundary, so it cannot shift the
  layout: 0 on four titles at 1440x1000 and 390x844 on a production build.

`/changes` is the same history read the other way round: the week's changes across every title,
grouped by what kind of news each is (`CHANGE_SECTIONS` in `lib/types.ts`), listed like `/schedule`
rather than gridded like `/browse` - the subject is an event, and one show can appear under two
headings. Its window ends at the newest fetch compared, not today, so it is a fixed week between
runs rather than a shrinking one. The nav carries it as the fifth section.

**The nav row is a width budget, and the figure recorded here was wrong for a month.** This said
"the five items still sit on one line (measured, 352px of 390)". They did sit on one line - by
hanging off the edge of it. Re-measured 2026-10-15 at 390 on a production build, the row was
366-372px inside a 350px column (`max-w` minus the `px-5` gutters), overflowing its container on
*every* route and the viewport itself on `/schedule` (392) and `/search` (391), with `/changes`
exactly on the line at 390. Nothing caught it because nothing measured the document's scroll width;
the original note recorded the claim it wanted rather than the number.

Two things made it hide. The width **moves with the route** - the active item is semibold, and
"Schedule" marked is 6px wider than nothing marked - so it tipped over on one page and not another.
And "sits on one line" is true of a row that overflows, so the eye confirms it.

**The variance is gone rather than absorbed** (2026-10-16). Each label reserves its *marked*
width - the text is rendered a second time, bold, at zero height, purely to size the box
(`.nav-label::after`, `content: attr(data-label)`) - so the row is one width on every route:
347px below 440, 387 to 639, 419 above. The weight is kept rather than dropped, because the
flag bar says where you are and the weight says it again for anyone who cannot see a 2px rule.

That cost 15px and broke both numbers it had just been given. The row went to 355 and hung
into the right-hand gutter at 390, and 360 - swept clean an hour earlier - overflowed outright.
`gap-x-2.5 min-[440px]:gap-x-5 sm:gap-x-7` fits the column again, and the step moved from 420
because at 20px gaps the row needs 427px of viewport rather than 412.

**And it wraps**, which is what stops this being a number to re-derive whenever a label
changes. Below ~387px no gap helps: five words at 0.875rem do not fit 320px of column, so
`flex-wrap` makes that two short rows instead of a horizontal scrollbar. Swept 320 to 1440:
one width per viewport, inside its column, no overflow anywhere.

**The smoke suite asserts `scrollWidth <= clientWidth`** on six routes at 390 and 1440, and
that the nav is a single width across routes *and* inside its column - the first version of
this fix cleared the window while hanging into the gutter, and only the column check caught it.

Layout shift 0 at 1440x1000 and 390x844, cold and
warm, on a production build (2026-09-21), with /schedule measured alongside as a control.

**A title page says whether its score has stopped moving** (`scoreRevisions` in `lib/types.ts`,
under the arc in the score rail): *"Revised twice since 11 October, last by Kitsu"*. The number
itself is a commodity - three other sites print it - and what this one can add is how much it is
worth yet: the printed score of a season still on air changes on 30.9% of re-asked readings
against 0.8% of one already over.

**Counted from `changes`, never from `score_history`.** Those points carry a run_date and a score
and no vote count, so a pair reading the same value twice cannot be told apart from a row carried
forward - and most rows in most runs are carried forward. Counting them is the mistake `/scores`
exists because of. A change entry is written only where a source reported something different, so
it cannot invent a revision.

**It names the source, and that is correctness rather than courtesy.** The figure quoted is one
source's while the score above is the merged winner, and they legitimately differ: Dragon Ball
Super shows 8.3 beside a newest change of 8.0 to 8.1. Unattributed, that is the site contradicting
itself on one screen. The smoke suite asserts the line always carries a source name.

**Silence means never re-asked, not settled.** The weekly run refetches only the current season, so
an older title was asked once: 498 of 7,229 scored titles have any history at all, but 66 of the 76
airing TV titles do, which is where a reader is deciding. Saying "unchanged" about a 2017 title
would be the clean, wrong claim. What this cannot say is that a score HAS settled - that needs the
vote count to tell a re-ask from a copy, which the detail response does not carry.

## How a score settles

`/scores` is the only page here that reads the warehouse **down the dates** rather than across
the titles, from one request to `GET /scores/settling`. Everything else answers "what is true
now" out of `anime_media_latest`, which is the top slice of `anime_media`'s 66,098 dated rows.

**The unit is a re-ask, and that is the whole page.** A snapshot is not an observation: the
weekly run refetches the season it covers and writes every other title's row again unchanged.
The 68 Fall 2021 TV titles carry a row on all ten dated snapshots with their `user_count` summing
to exactly 592,705 on every one of them, so "no old score moves" is a statement about what was
asked. A pair of consecutive readings therefore counts only where `user_count` moved, which no
copy can fake, and the detector is deliberately not the score itself - a test that looks at the
answer throws away every reading that came back the same and reports movement near 100% by
construction.

The first pass at this measurement did count snapshots, and produced a clean, wrong table saying
a score settles within about two seasons. It was measuring the refetch schedule. Anything that
revisits this should re-read `backend/app/routers/scores.py` before trusting a figure.

What the honest version says, over 544 re-asked readings to 2026-10-12: **35% of readings of a
season still on air changed the printed score, against 1% of a season already over** - but 35% of
the finished seasons' readings still came back *different*, two decimal places below anything the
site prints. A score is never finished being revised; it stops being revised visibly. Direction
is balanced both ways (122 up / 113 down while airing), so there is no decay story to tell.

- **No numbers live in the page.** Every figure is read from the response, because the window
  grows by a run a week.
- **Seasons that were never re-asked are absent, not shown as flat.** Ten of the twenty-two were.
- **It is the one route with no GSAP chunk.** A stagger holds its targets at opacity 0 until a
  scroll trigger fires, and here the targets are the argument, not decoration.
- `getScoreSettling()` returns **null** on a 404 or 503 rather than throwing. The site and the
  API are separately deployed, so a frontend build can reach a container running an older commit;
  throwing took the whole production build down the first time this page was added.
- It is reached from the score arc on a title page and from `/changes`, **not from the nav**: the
  five sections already fill the nav's width budget at 390 (see above).

## What a week did to a score

`components/ScoreDaily.tsx`, from `GET /scores/daily/{wb_id}`, under the airdates on a title
page. **The dense half of `/scores`**: everything else here reads a weekly snapshot, so a score
that moves on Tuesday and again on Friday is one move and a score that moves and moves back is
none. The daily AniList status check already asks about exactly the titles the catalogue calls
airing, so these readings cost no new fetch and were being written and kept with nothing
reading them.

**An endpoint, not a field on the title, which is the opposite call from `score_history`.**
That series was attached because it is small and already in hand; this one reads a dated glob
that gains a file every morning, so attaching it would make all 11,992 title pages pay a
growing scan for an answer only the ~199 airing ones have. The page asks for it only where
`isAiring()` is true, in its own Suspense boundary with the footer guard.

**The unit is a re-ask, the same as `/scores`.** The check writes a row every morning whether
or not anything moved, so a pair counts only where the vote count moved. "Asked five times"
would be a statement about the pipeline's schedule.

**And a printed move is mostly arithmetic, which is what this block had to be designed
around.** A score stored out of 100 and shown out of 10 flips on the single vote that crosses
.05. Of the nine printed moves in the first day of readings (2026-10-17, 199 titles), one rode
**521** new votes and one rode **two**. Printing those the same way reports rounding as news,
which is exactly what `/scores` exists to avoid doing with snapshots. So a move is only called
one above `VOTES_WORTH_CALLING_A_MOVE` (20) new votes, the weight is printed beside it, and the
rest are counted off as a rounding boundary being crossed.

**It names AniList, and that is correctness rather than courtesy** - the same rule the
revisions line in the rail follows. The score above the block is the merged winner of three
sources and these readings are one source's, so they legitimately differ: on the title this was
built against the rail printed 7.5 from MyAnimeList while these said 6.9. Unattributed, that is
the site contradicting itself on one screen. The caption also says the readings are daily while
the score above is from the weekly refetch, so it can run a few days ahead of it.

**Nothing is shown where there is nothing to say**: under two readings there is no pair, a
title with no re-ask had only copies, a finished show is never asked about, and a warehouse
published before the score columns existed has none. All four render nothing rather than a flat
line, which is the rule `/scores` follows for a season nobody re-asked.

**The series cannot be backfilled.** `score_100` entered the status schema on 2026-10-16, so it
starts there and grows a day at a time; the airdate archive, by contrast, was recoverable in
full because the files were always kept.

## Long pages say what is on them

`/changes` is 11,725px at 1440 and 28,444px on a phone - **thirty-three viewports** - and
`/schedule` flows seven days as newspaper columns, so the first screen at 1440 used to read
Thursday / Sunday / Tuesday: the tops of three columns, not the next three days. Both now open
with one `.meta` line of in-page anchors built from the same sections they render, so the index
cannot drift from the page.

**`First scored` is its own section on `/changes`, and that split is the point.** A score change
with no previous value is not a smaller 8.2-to-8.1 - it is the moment a title stops printing
screened back and comes up in colour, which is the one event this design exists to show. 89 of
them were mixed into a 147-row section called "Score moves" and sorted among them by title. The
split is `c.old == null`, declared on the section in `CHANGE_SECTIONS` rather than by field.

**An anchor says where it put you.** Following one of those links jumps twenty viewports into a
page that looks exactly like the part just left - every section is drawn the same way and every row
under a heading is a title and a date. `section[id]:target > h2` turns that heading's ink rule flag,
which is the mark the masthead already uses for the current section, so no new element is drawn and
nothing moves. It persists until another anchor is followed, meaning the same thing the nav's marker
means.

**And on a phone the heading stays.** `/changes` is thirty-three viewports there; once a heading has
scrolled past, nothing on screen says which section you are inside. The headings are `sticky` at the
top below `sm` only - above it both pages flow in newspaper columns, and `position: sticky` inside a
multicol fragment is undefined. The heading already carries the ink rule, so it is not a new bar; it
simply stops leaving. Both are asserted in the smoke suite at 390 and 1440.

**A thumbnail gets a finer screen.** The halftone's 4px dot pitch is chosen against a 150-230px
catalogue plate; the schedule and the change feed reproduce the same plate at 36x49, where that
leaves about nine dots across the whole image. A screen nobody can read as a screen is the
certainty system applied decoratively, which DESIGN.md forbids - and on those rows the plate is
the only signal, because neither prints a score. `.plate-fine` halves the pitch, the way a
printer picks a line screen for the reproduction size.

**Schedule titles wrap to two lines.** One line truncated 44 of the week's 123 at 390px; now 9.
`line-clamp-2`, so a title that fits still sits on one line and nothing changes at 1440.

## A filter must not sit in the sort row

`/browse`'s "Rated only" (`?rated=1`) was a chip inside `<FilterRow label="Sort">`, one word from
"Rated first" and styled identically. It removes every title with no score upstream - 22 of 81 -
so a reader aiming at a reordering could delete a quarter of the season with no sign of it. It is
its own facet row now, with a reset chip, and both chips carry counts computed **before** the
rated filter so they say what they would produce under the reader's other choices: `?genre=Mecha`
reads "All titles 5, Rated only 4", not the season's 81 and 59.

## Motion

GSAP + ScrollTrigger via `@gsap/react`'s `useGSAP`, in `components/motion/`. **Do not add a second
animation library** - two libraries on the same elements fight over frames.

Every effect sits inside `gsap.matchMedia("(prefers-reduced-motion: no-preference)")` and uses
`gsap.from()`, so reduced-motion users get no animation and a JS failure leaves the page complete
rather than invisible. Transform and opacity only, so CLS stays 0.

Do not add: horizontal scroll hijack (breaks `/browse`'s filters, pagination and URLs), Three.js
(no 3D content), or Lenis (overrides native scroll, hurts fast scanning and accessibility).

Motion must be motivated. If you cannot say in one sentence what an animation communicates  - 
hierarchy, sequence, feedback, state change - do not add it.

## Verify before claiming

`npm run test:e2e` (frontend/e2e, Playwright) runs a smoke suite against a production build at
1440 and 390 and runs in CI on every push: each route answers, has an `h1` and real content in
`main`, the console is clean, a catalogue link leads to a title page that states a status, and the
two streamed pages measure no layout shift. It asserts no title, count or season - the catalogue
changes weekly, and a test that goes red when Summer becomes Fall is a test that gets deleted.
Removing `data-footer-waits` from `/changes` was tried against it and fails the shift assertion,
which is the point of having it.

It is a smoke suite, not a substitute for looking: it would not notice a page that renders
correct content ungracefully. Run the build, then check in a real browser at 390 and 1440. Current gate results: 0 contrast
failures, 0 tap targets under the WCAG 2.2 24px minimum, CLS 0, visible focus on every control,
and no horizontal overflow on any route at 390 or 1440.

**A page that streams gives the footer something to wait for.** A route that renders behind a
`<Suspense>` - every title page, the schedule - sends the layout first, footer included, and the
content arrives later in the same response. The footer painted in view under the fallback and was
pushed down when the content came: 0.04 to 0.06 on every title page at 1440x1000, and 0.004 to
0.011 more when a title's franchise section arrived after it on an uncached load. So any fallback
that stands above the footer carries `data-footer-waits`, and `body:has([data-footer-waits]) >
footer` keeps the footer out of the layout until the content replaces it (`globals.css`). An
element arriving is not a layout shift; one moving is. A zero-size `<span data-footer-waits
hidden />` is enough for a fallback that draws nothing.

Not a fallback a screen tall, which fixes a long page and breaks a short one: title pages run from
shorter than a 1000px screen (6 of the 12 sparsest measured) to twice it, and on a short one the
footer rose into view when content shorter than the fallback replaced it. Measured 2026-09-14 on
a production build, 14 titles and the schedule, cold and warm: 0 at 1440x1000 and at 390x844.

**A hidden browser never reveals streamed content.** React 19.2 batches the reveal of streamed
Suspense boundaries behind an animation frame: `$RC` marks an arrived boundary `<!--$~-->` and
leaves its content in a hidden `S:` div, and `$RV` only moves it into place after
`requestAnimationFrame` fires (`$RT` is set on the first frame). A document that paints no frames -
the in-app Browser pane while it is hidden, a background tab - therefore keeps every boundary at
`$~`, and every client component inside one stays inert: the trailer button does not respond and
the countdown renders nothing. One frame resolves all of it; confirmed 2026-09-14 on a title page,
where a single screenshot of the hidden pane took 5 `$~` boundaries and 5 hidden segments to 0 and
hydrated every button. This was first misread as the pane being unable to hydrate a PPR page, and
cost a long session chasing a component that was never broken. In the pane, check
`document.hidden`, or take a screenshot before judging a client component. Measurements still
belong in the Playwright MCP browser, which paints headless and takes an exact viewport.
