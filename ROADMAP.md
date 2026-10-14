# WeebBlade — Roadmap

What is worth doing next, what it costs, and what state each item is actually in.

Replaces `IMPROVEMENTS.md`, which this folds in. One tracking document, because two
roadmaps disagree with each other within a week.

**How this file is kept.** An item moves to Done when something was *checked*, not when
code was written. The distinction is not pedantry: the round of work that produced the
first version of this file reported a CORS rule as safe, a test suite as passing, a
document as updated and a cold-start figure as known — and of those four, one was
verified live to be unsafe, one was a single file out of 406 tests, one had not been
touched at all, and one had never been measured by anyone. Every claim below says how
it was established.

**Cost rule.** Nothing here may introduce a bill. There is no payment method on Render
or Vercel, and both suspend a free service at its quota rather than charging. Figures
below are from the providers' own published limits, checked 13 October 2026.

Status: **[x]** done and verified · **[~]** partly done · **[ ]** open

---

## Done

### 1. [x] Vercel preview deployments can call the API

Branch previews get URLs nobody can list in advance, and `/search` runs in the browser,
so without a rule a preview's search box fails while production's works.

Shipped as `allow_origin_regex`, then **corrected**: the first version was
`^https://weebblade(-.*)?\.vercel\.app$`, described as supporting previews "without
exposing the API to unauthorized domains". It did the opposite. `vercel.app` is a shared
suffix and project names are free-form, so anyone can register a matching name — verified
against the live API, which returned `access-control-allow-origin` for
`weebblade-malware.vercel.app`.

Now pinned to the `-git-` preview shape, overridable by `ALLOWED_ORIGIN_REGEX`, with a
test fixing the three origins the first version let through.

*Verified:* live, after deploy — production and `weebblade-git-*` allowed,
`weebblade-malware` and `weebblade-anything` denied.

**Honest limit:** no pattern over somebody else's domain is squat-proof. This is tolerable
only because the API is public, unauthenticated and read-only, so CORS guards a free
container's bandwidth rather than anyone's data. If that ever stops being true, this rule
is not the control to rely on.

### 2. [x] Cold start is explained rather than suffered

A free instance sleeps after 15 idle minutes. Two halves shipped:

- **Warm-up ping** (`frontend/components/WarmupPing.tsx`) — a background `/health` call on
  page load, so the API wakes while the reader is reading rather than when they hit search.
  On-demand deliberately: a 14-minute external pinger would hold the container awake 744
  hours a month against an allowance of 750, which is the whole budget spent on nobody.
- **A notice in search** after 3.5s (a warm search answers in ~150ms), **rewritten**: it
  read "Waking up the server container on Render… initial query after idle takes ~30
  seconds while the container boots". A reader has no container and did not choose the
  host. Now: *"Waking the search service. It sleeps when nobody has searched for a quarter
  of an hour, and takes about a minute to come back."*

*Corrected after item 3 measured it.* The notice first said "about a minute", borrowed
from Render's docs, and fired after 3.5s. Both were wrong against the real service: it
wakes in **32.4s**, and a warm search on an 0.1-CPU instance takes **1.8s**, so a 3.5s
threshold sat barely a second above normal and would have told readers the service was
asleep while it was awake. Now half a minute, after 5s.

---

## Open — measurement

### 3. [x] Time an actual cold start

Done, 13 October 2026, after 17 minutes with nothing touching the API:

| | |
|---|---|
| `/health`, cold | **32.4s** (connect 0.06s, so all of it server-side) |
| First `/search` after the wake | 2.5s |
| `/search`, warm | 1.8s |
| `/health`, warm | 0.09s |

Three things this settled. The wake is **half a minute, not a minute** - Render's published
figure is conservative, and printing it would have been safe and wrong. A warm search is
**1.8s, not the 150ms measured on a laptop** - an 0.1-CPU instance is an order of magnitude
slower at the ONNX embedding, which is what made the 3.5s threshold unsafe. And the first
search after a wake is only 0.7s worse than a warm one, so the model and the warehouse are
both ready by the time `/health` answers: the 32s is the whole cost, not a prelude to more.

Not separable from outside: connect was 0.06s, so container start, the 41 MB download and
the model load are one opaque 32s. Splitting them needs Render's own logs.

*Note:* it took two attempts. The first used `bc`, which is not installed, so the timings
were lost and the request woke the container - costing another 17 minutes. curl reports
`%{time_total}` itself and needs nothing.

---

## Open — pipeline

### 4. [x] Retire Jikan

Verified before acting, because the premise came from an audit rather than from here, and
the verification changed the reason. Jikan is not flaky and not down: **its public API was
[discontinued on 1 October 2026](https://github.com/jikan-me/jikan-rest/issues/613)**,
announced in June, maintenance mode from then, brownout from 1 September. It is not coming
back, and MyAnimeList's own API already covers what the mirror was for.

Checked directly first: `api.jikan.moe` resolves on both A and AAAA records, and IPv4,
IPv6 and a raw TCP connect to 443 all time out. The runner's logs say `Network is
unreachable`. It never landed a single row in this project's life - the warehouse logs
"No files yet for view anime_media_jikan" on every run.

Removed from 29 files: the ingestion module and its tests, the pipeline step, the Airflow
task, the merge priority, the catalogue view, the change feed, the run checks, the API's
source list, and the frontend's.

The cost was 30s of a 464s weekly run and an ERROR traceback in every log. **The reason to
do it was not the 30 seconds.** `ALL_SOURCES` had four entries and three were live, so the
masthead read "3 of 4 sources live" - which tells a reader one source is temporarily
missing. Nothing was missing. On a site whose whole claim is that it is honest about where
its data came from, that was the actual defect.

Two things deliberately kept. The duration regex in `normalize.py` still casts to string
before extracting digits, because Jikan sent free text and a future source doing the same
should widen a column rather than break a run - it costs nothing on an int. And the
historical comments stay: they explain why the code is shaped as it is, which is still
true even though the source is gone.

### 4b. [x] Social cards per title

Every title page sent the site's own card — the same picture and the same
sentence whichever of 6,359 shows you posted — so a shared link said nothing
about the show. Each title now renders its own: artwork, name, the facts, and
the certainty treatment, which is the one idea the design runs on (DESIGN.md §2)
applied in the place strangers see it first. A scored title prints a flag-pink
number; an unscored one gets the em-dash null marker and says "no score
upstream".

The constraint flagged before starting turned out not to bind: Bodoni Moda 900
is 43.8 KB and Archivo 500 is 109.5 KB, **153 KB of the 500 KB** `ImageResponse`
budget. Posters are fetched per request rather than bundled, so a cover never
counts against it.

Two things the first draft got wrong, both caught by rendering a card and
looking at it. It joined the facts with `·`, which DESIGN.md bans by name, and
it drew the null marker in the rule colour, where a 78px Bodoni em-dash is one
hairline and reads as a rendering artefact rather than a decision.

The palette is read out of `app/globals.css` at module load rather than typed
into the card, because Satori has no stylesheet and DESIGN.md allows no literal
hex in `app/`. A renamed token fails the build with a message saying so.

*Verified:* a real 1200x630 PNG for both certainty states, and the smoke suite
now asserts the magic bytes and dimensions rather than a 200 - an error page is
also a 200.

### 5. [x] Warn before the GitHub token expires

The token expires **2027-10-13**. The API already names the failure once it happens — a 401
logs `GITHUB_TOKEN is expired, revoked or wrong` — but nothing warns beforehand, and the
symptom (a warehouse that stops updating, then 503s after a restart) is easy to misread.

Done: `pipeline/token_expiry.py`, called by the weekly run with `if: always()` - a run that
failed its checks is not a reason to skip telling somebody their credentials are lapsing,
and is probably the week they are least likely to notice on their own.

Thirty days, because the weekly is what carries it: four or five reminders is enough to be
heard and few enough not to become furniture. It counts down, says "expires today" on the
day, and says "expired 3 days ago" after - "expires in -3 days" is the kind of line that
makes a reader doubt the alert rather than the token. Every message carries the
instructions, because whoever reads it will be a year from having thought about any of this.

*Deliberately not* built on GitHub's `GitHub-Authentication-Token-Expiration` header, which
is [documented as unreliable for fine-grained tokens](https://github.com/orgs/community/discussions/172213),
returning server time or a minute from now. A warning that fires falsely gets muted, and
then the real one is muted with it. A date somebody typed is worse engineering and better
behaviour.

11 tests, including one asserting the date in the module matches the one in `README.md` -
two places name it and a regenerated token has to update both.

*Cost:* none.

---

## Open — interface

Found by reading the live site at 1440 and 375, against `frontend/DESIGN.md`.

### 6. [~] The best thing on the site is invisible

A title page carries a per-source changelog — *"Score 8.2 to 8.1, per AniList"*, *"Premiere
moved from 1 October to 2 October, per MyAnimeList"*, *"Now on Netflix, per Kitsu and
AniList"* — and an airing block that states its own provenance and freshness. No other
anime site has this. It is the pipeline made visible, and it sat below a facts table,
below the fold, reachable only by opening a title and scrolling.

**Done on the title page:** a line under the title says *"6 changes recorded, the latest on
11 October"* and links to the section, so scrolling for it is a decision rather than an
accident. Conditional, because the weekly run refetches only the current season and most
older titles have no history — a pointer to an empty section would promise what the page
cannot show. The smoke suite asserts it as an implication: where the section exists, so
does a link to it.

**Done on the home page:** a line under the digest says what the week held and links to
`/changes` — *"The sources changed their minds 361 times this week — 147 scores, 80
streaming links and 55 starts and finishes, each with the source that reported it."*
Counted from the feed, never written down.

**That needed no API change**, which this file previously said it would. `/changes` already
returns every entry with its `wb_id` in one small cached request — the same shape that made
the plate airdates free. The note was written before that was noticed; a marker on an
individual plate would still need the backend, because `changes` is empty on list rows.

*The cost, measured on a phone:* the first poster moved from **1,418px to 1,491px**, 73px.
A first draft of the sentence cost 142px and was cut in half, because this is the page
`DESIGN.md` already trimmed the digest on to lift the posters up, and spending that back on
a teaser would have been the same mistake from the other direction.

**Still open:** the grid itself says nothing. A plate whose title changed this week looks
exactly like one that did not.

### 7. [x] `/browse` opens with a wall of controls

Measured first, and the measurement moved the argument. At 1440 the first plate sat at
611px against a 1000px fold - survivable, and my earlier "below the fold at 1440" was
overstated. **The phone was the real case**: at 390x844 the first plate sat at **1,259px**
with the fold at 844, the genre chips alone running 358 of those pixels. A screen and a
half of controls before a single poster.

That is the number DESIGN.md already fixed the home page *from*: the full digest put
posters at ~2,400px, the one-paragraph lead brought them to ~1,270. /browse had quietly
arrived back there.

Folded into a native `<details>`, so filtering still ships no JS and every view is still a
real URL - the rule the block is built on. It opens whenever anything is filtering, because
a reader who cannot see what is narrowing their results cannot clear it either, and the
summary names the active filters so a filtered view says so while closed.

| | before | after |
|---|---|---|
| First plate, 390x844 | 1,259px | **405px** |
| Plates on the first screen, phone | 0 | 4 |
| First plate, 1440x1000 | 611px | **302px** |
| Plates on the first screen, desktop | 0 | 12 |

*One thing worth keeping:* Tailwind's `group-open:` compiles to the `:open` pseudo-class,
which this browser applied to one of the two state labels and not the other, so an opened
block said both "Open" and "Close" at once. `group-[[open]]:` uses the attribute the
element actually carries. Caught by reading computed styles, not by the typecheck or the
build.

### 8. [x] The certainty system has NOT lost its job - I was wrong

Closed by measuring rather than by deciding, because the premise was false.

I wrote that the halftone had stopped doing anything on the default view, reasoning from a
figure in `CLAUDE.md`: "88% of a season's TV is scored now". That number is real and it is
the wrong one to reason from. It was measured on 2026-09-14, when the default view was a
Summer season well into its run. **The default is never a settled season** - `startedSeason`
picks the newest that has STARTED, which is always the one whose titles have had the least
time to be scored.

Measured live, 2026-10-14:

| Season | TV screened back | All formats |
|---|---|---|
| Fall 2025 | 25% | 45% |
| Winter 2026 | 12% | 40% |
| Spring 2026 | 12% | 44% |
| Summer 2026 | 10% | 54% |
| **Fall 2026** (what a visitor sees) | **27%** | **56%** |

A quarter of the default grid is screened back, and 56% of it one format chip away. That is
not "a uniform grid where every item carries equal weight"; it is the system working on the
majority condition it was drawn for.

The structural point is the useful one, and it is now in `DESIGN.md`: because the default
tracks the newest started season, this view regenerates its own unknowns every quarter. The
design cannot age out of a job while that is true.

*What was actually wrong* was the documentation, which quoted one season's number as if it
were the catalogue's. Both files now give the range and say which end the reader is looking
at.

### 9. [x] Grid plates say which episode lands this week

They carried the word "Airing", which is true and answers nothing. Where the week's
schedule knows, a plate now reads **Ep 3 · 15 Oct JST · TV** - same slot, same line, so a
grid of a hundred keeps its rhythm. Measured: every caption 18px at 390 and at 1440, no
wrapping, no uneven rows. 30 of 30 plates on the first page of the current season carry an
episode; a finished season shows just the format, exactly as before.

**No API change, which was the thing worth checking first.** `/anime` does carry an
`upcoming_episodes` field - and leaves it empty on list rows, filled only for a single
title. So the obvious route was a backend join across every row of every season. `/schedule`
already returns the week keyed by `wb_id` (118 of 124 episodes have one) in one small
request that is cached for hours, which is the pattern the whole data layer is built on:
fetch once, derive locally.

The date is Japan's and says so. A bare weekday would be read as the reader's own, and
these broadcast late enough at night in Tokyo to be the previous evening across the
Americas - the distinction `/schedule` spends a paragraph on. The earliest entry per title
is this week's episode rather than strictly the next: the window opens at midnight in
Tokyo, so for a few hours after a broadcast it names one that has just aired. "Ep 3, 15
Oct" is true either way; only the word "next" would not be, which is why the plate does not
use it.

### 10. [x] The warehouse was only ever read across, never down

Twenty-two seasons of weekly snapshots sat in `anime_media` - 66,098 dated rows - and every
view on the site read `anime_media_latest`, its top slice. The time axis was being
accumulated and never read. `/scores`, "How a score settles", is the page that reads it,
from one new endpoint, `GET /scores/settling`.

**The first measurement was clean, quotable and wrong, and that is the item.** Counting
snapshots per season produced a table saying a score is alive while its show airs and
settles within about two seasons: 100% of the airing season moved, 7% of a year before,
none of Fall 2021. What it was actually measuring is the pipeline's own refetch schedule.
The weekly run fetches the season it covers and writes every other title's row again
unchanged - the 68 Fall 2021 TV titles carry a row on all ten snapshots with their
`user_count` summing to exactly **592,705 on every one of them**. Those rows were never
asked about, so a flat score says nothing at all.

The fix is to count a *re-ask*: a pair of consecutive readings where the source's own vote
count had also moved, which no copy can fake. The detector is deliberately not the score,
because a test that looks at the answer discards every reading that came back the same and
reports movement near 100% by construction. Over 544 re-asked readings of TV titles:

| | re-asks | answer differed | enough to print | median change |
|---|---|---|---|---|
| Season on air during the window | 297 | 235 (79%) | **103 (35%)** | 0.19 |
| Season already over | 245 | 86 (35%) | **2 (1%)** | 0.00 |

So the honest finding is better than the one it replaced: **a score is never finished being
revised, it stops being revised visibly.** A third of the readings of a season two years old
still come back different, two decimal places below anything this site prints. And direction
is balanced both ways (122 up, 113 down while airing), so the obvious story - hype decaying
after the finale - is not in the data.

The page says the method before it says a number, for that reason. Ten of the twenty-two
seasons were never re-asked inside the window and are absent rather than listed as settled;
533 of the 544 re-asks are Kitsu's, and the page says that too.

**Also on the page:** a season acquires its scores weeks after it is listed. Fall 2026 sat in
the catalogue through four runs with no scored title, then went 1 to 19 to 55 to 59 of 81 in
fifteen days. That is the halftone-as-certainty system drawn along the time axis, which is
the argument for it being a page rather than a paragraph.

**Not in the nav.** The five sections already fill 352px of a 390px line. It is reached from
the score arc on a title page, where a reader who sees a number move asks whether that is
normal, and from `/changes`, which is the same history one week at a time.

### 11. [x] "More like this", and the index that could not answer it

6,359 embeddings sat in the published warehouse and one page used them. A similar-titles block
was logged as the cheapest feature left: one `array_cosine_similarity` against the row's own
vector, over data already built and published.

**It returns puns.** The search document leads with every name a title has, which is what makes
"type the other name and find it" work (10/40 to 22/40, measured when it was chosen). A vector
that leads with names matches on names, so Blue Box Season 2 came back beside The Blue
Orchestra Season 2, The Fire Hunter Season 2 and Pacific Rim: The Black Season 2, and SPY x
FAMILY beside Spy Classroom and Spy x Sect. **Search and similarity are different retrieval
tasks and cannot share an index.**

A second document - genres and synopsis, no names - lifts the mean genre overlap of the five
nearest non-franchise neighbours from 0.290 to 0.402, and the examples become sane: SPY x
FAMILY finds Buddy Daddies, BOCCHI THE ROCK! finds BanG Dream. Re-ranking the old index by
genre overlap instead scores 0.541, which is higher and meaningless, because that is the
measure being optimised; its results still lead with Spy Classroom and with BOCCHI's own recap.
A re-rank reorders a candidate pool and cannot repair one.

Three filters, each found by reading the output rather than by design: **no synopsis, no
neighbours** (533 titles had none, and the shape line the search index gives them made two
blanks identical, so each was served to the other as a perfect match); **the title's own
franchise excluded**, since the section above lists it in full; and a **0.10 distance floor**,
below which it is the same work under another name that MAL's relations do not cover.

Precomputed as rows rather than a second vector column: 0.8 MB instead of 9.8 on a file the API
downloads whole on every wake, and a 47 ms join instead of a scan. It costs ~60s of CPU a week.

Live when the next weekly run publishes a warehouse carrying the table; until then the endpoint
answers with an empty list and the block does not render.

---

## Open — carried over, not urgent

- **Six poster URLs are dead upstream** at Kitsu (404 at origin, confirmed). Currently
  ignored narrowly in the smoke suite so it does not go permanently red. A liveness check
  at ingest would cost 6,359 HEAD requests a week, which is why it has not been done.
- **Romaji search recall is 24/40** — typing a title's other name finds it first 24 times
  out of 40. Adding native titles to the indexed document, or blending keyword matching
  with vectors, would lift it.
- **533 titles have no synopsis anywhere** (2026-10-14; 26 were fillable when checked).
  Upstream gap.
- **40 titles are `airing_unconfirmed`** (2026-10-14) — nothing upstream can confirm them.
- **State lives in two places**, GitHub releases and one laptop. No third copy.
- **The repo is private**, so the API needs a token to read its own warehouse. Making it
  public removes that dependency and the 2027 expiry with it. The history scan was clean.

---

## Cost

Checked against the providers' published limits, 13 October 2026. No payment method is on
file anywhere, and all three suspend at the quota rather than charging.

| Item | Mechanism | Allowance | Risk |
|---|---|---|---|
| 1. Preview CORS | code only | — | none |
| 2. Warm-up ping | browser calls `/health` on load | Render free: 512 MB, **750 instance-hours/month** | on-demand only; the container sleeps when nobody visits. An always-on pinger would spend 744 of 750 and was rejected for that |
| 4. Retire Jikan | fewer ingest calls | GitHub Actions: 2,000 min/month, using ~20 | reduces usage |
| 5. Token warning | date check in the weekly | existing ntfy topic | none |
| 6–9. Interface | code only | Vercel Hobby: 100 GB bandwidth, **1M function invocations**, 4h active CPU | hard caps that stop serving, not bill |
| Social cards | `ImageResponse` per title | same | Measured: the two fonts are **153 KB of the 500 KB** budget, so it fits with room. Posters are fetched at request time rather than bundled, which keeps it there whatever a cover weighs |

One real constraint worth knowing: Vercel's Hobby terms prohibit commercial use. A
portfolio project is fine; anything that starts earning is not.
