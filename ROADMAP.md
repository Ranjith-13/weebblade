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

### 2. [~] Cold start is explained rather than suffered

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

*Why **[~]** and not **[x]**:* see item 3. The duration in that sentence is Render's
published figure, not a measurement.

---

## Open — measurement

### 3. [ ] Time an actual cold start

Nobody has. "35–50s" and "~30s" were both asserted without a stopwatch, and one of them
reached user-facing copy. The only honest number currently available is the provider's
"about a minute".

Needs 15 minutes with no traffic (the warm-up ping defeats casual attempts), then a timed
first request. Worth recording the breakdown too: container start, 41 MB warehouse
download, ONNX model load. If the download dominates, item 9 becomes worth doing.

*Cost:* none. *Next:* leave it idle, then time `/health` and a first `/search`.

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
| OG images (if revisited) | `ImageResponse` per title | same | **500 KB bundle limit including fonts** — Bodoni Moda would have to be embedded and may not fit. Measure before committing to it |

One real constraint worth knowing: Vercel's Hobby terms prohibit commercial use. A
portfolio project is fine; anything that starts earning is not.
