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

### 4. [ ] Promote AniList, retire Jikan

Jikan is a third-party MyAnimeList mirror that has been down for this project's whole life
and still gets fetched every run. The official MAL v2 API now covers what it was for, and
AniList is healthy.

*Unverified:* the claim that AniList "responded with 99 titles for Fall 2026" came from the
audit, not from me. Re-run `ingestion/anilist/fetch_season.py` and check before acting.

*Cost:* saves GitHub Actions minutes rather than spending them. *Care:* the catalogue's
source priority and the `3 of 4 sources live` copy both move if a source is removed, and
`processing/consolidate.py` has opinions about which source wins a merge.

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

### 5. [ ] Warn before the GitHub token expires

The token expires **2027-10-13**. The API already names the failure once it happens — a 401
logs `GITHUB_TOKEN is expired, revoked or wrong` — but nothing warns beforehand, and the
symptom (a warehouse that stops updating, then 503s after a restart) is easy to misread.

A date check in the weekly run, pushing to the existing ntfy topic inside 30 days, is a few
lines.

*Deliberately not* built on GitHub's `GitHub-Authentication-Token-Expiration` header, which
is [documented as unreliable for fine-grained tokens](https://github.com/orgs/community/discussions/172213),
returning server time or a minute from now. A warning that fires falsely gets muted, and
then the real one is muted too. Hardcode the date; it is in `README.md`.

*Cost:* none.

---

## Open — interface

Found by reading the live site at 1440 and 375, against `frontend/DESIGN.md`.

### 6. [ ] The best thing on the site is invisible

A title page carries a per-source changelog — *"Score 8.2 to 8.1, per AniList"*, *"Premiere
moved from 1 October to 2 October, per MyAnimeList"*, *"Now on Netflix, per Kitsu and
AniList"* — and an airing block that states its own provenance and freshness. No other
anime site has this. It is the pipeline made visible, and it sits below a facts table,
below the fold, reachable only by opening a title and scrolling.

Nothing on the home page or in the grid suggests it exists. `/changes` exists but is a
separate section a reader has to already want.

*Cost:* none. *Care:* the section only renders where a title has history, which most older
titles do not — surfacing it must not promise what a given title cannot show.

### 7. [ ] `/browse` opens with a wall of controls

At 1440 the first poster sits below five filter rows, genre alone running three lines. On
the page whose job is "show me this season", the season starts after the apparatus.

`DESIGN.md` already made this trade once in the other direction, moving the season chips
out of the filter block. Worth measuring where the first plate lands at both widths before
changing anything.

### 8. [ ] The certainty system has quietly lost its job

The halftone treatment was drawn when 73% of a season had no score. TV is now 88% scored,
so the default view is a near-uniform grid of full-colour plates — which is the thing
`DESIGN.md` bans in its own words: "one uniform grid where every item carries equal weight".

The idea still earns its keep one format chip away (over half of ONAs, films and music
videos are unscored). This is not a bug and not a reason to fake the state; it is a
question about whether the default view still shows what the design was built to show.

### 9. [ ] Grid plates could say when the next episode is

They carry title, airing status and format. The airing data is already in the warehouse and
already renders on title pages and `/schedule`. "Ep 3, Thursday" on a plate is the single
most useful thing a seasonal almanac can tell someone scanning.

---

## Open — carried over, not urgent

- **Six poster URLs are dead upstream** at Kitsu (404 at origin, confirmed). Currently
  ignored narrowly in the smoke suite so it does not go permanently red. A liveness check
  at ingest would cost 6,359 HEAD requests a week, which is why it has not been done.
- **Romaji search recall is 24/40** — typing a title's other name finds it first 24 times
  out of 40. Adding native titles to the indexed document, or blending keyword matching
  with vectors, would lift it.
- **529 titles have no synopsis anywhere** (26 are fillable). Upstream gap.
- **39 titles are `airing_unconfirmed`** — nothing can confirm them.
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
