# WeebBlade - where this grows next

*Working notes on where this grows next. `ROADMAP.md` is the record of what was done and
why; this is the argument about what to do. Tracked since 2026-10-18 - it was gitignored
until then, which meant the range-read measurement in item 4 existed on exactly one laptop
and in no backup, including the off-site mirror, which copies the data lake and not the
repository.*

Written 2026-10-14, after the roadmap emptied out. Everything here stays inside the
free tiers, and the measurements below are from the live system rather than estimates.

---

## The measurement that reframes everything

**This said ~120 minutes a month of 2,000, six percent. Re-measured 2026-10-18: 762 minutes,
38%.** The backfill to 40 seasons roughly doubled the weekly run, and a week of heavy
development did the rest.

| Workflow | Runs (30d) | Minutes |
|---|---|---|
| Tests (CI on every push) | 72 | 413 |
| Weekly pipeline | 6 | 163 |
| Test and deploy | 27 | 124 |
| Daily pipeline | 11 | 22 |
| Backfill, republish, mirror, image | 26 | 41 |
| **Total** | **142** | **762** |

Read it in two halves, because they behave differently. **The pipeline itself is ~211 of
those minutes and is now the predictable part**: a weekly run settled at 57 minutes over 40
seasons, a daily at ~3, so steady state is roughly 245 + 90 = **335 minutes a month, 17%**,
whatever anyone does. The other 550 were development - 72 CI runs and 27 deploys in a week
of pushing - and they go to nearly nothing in a quiet month.

So the old conclusion survives but the margin does not. Compute is still not the binding
constraint, but "six percent" made it sound unlimited and it is not: another doubling of the
catalogue puts the pipeline alone near 40% before anybody writes a line of code, and
`build_similar` is quadratic (4m20s at 11,989 titles, so ~20 minutes at double).

**The serving side turned out to be the lesser worry.** This said the API downloading the
whole warehouse into a 512 MB container was the constraint, and that quadrupling the
catalogue would make it ~160 MB and a much slower cold start. Doubling it made the warehouse
79 MB and the API still answers in ~0.4s. The thing that actually ran out of room first was
the weekly run's wall clock: 59m17s against a 60-minute timeout, raised to 120 on 2026-10-17.

## The unlock, verified 2026-10-14

GitHub release assets **support HTTP range requests**:

```
Range: bytes=0-15  ->  206 Partial Content
Accept-Ranges: bytes
Content-Range: bytes 0-15/41693184      (16 bytes of a 41 MB file)
```

DuckDB reads Parquet over HTTP with ranged reads. Publish the catalogue as Parquet
alongside the warehouse and the API can query it **in place** - fetching the few megabytes
a query touches instead of the whole file. The size ceiling effectively disappears, and
with it the reason not to backfill deeply.

*Caveat to test:* a private repo's asset URL is signed and time-limited, so the API would
mint one per session. On a public repo it is a plain URL and the problem vanishes - which
is one more argument for going public.

---

## The list, ranked

### 1. [x] Read the time dimension that is already being collected

> **Shipped 2026-10-14: `score_history` on the detail response, the arc under a title's score,
> and `/scores` ("How a score settles") from `GET /scores/settling`.**
>
> **(a) The data was already published.** `anime_media` in the live warehouse holds 66,098
> rows; `anime_media_latest` is just its top slice. No pipeline change, no new ingestion, no
> backfill. (Third time this pattern has come up: the obvious route looked like an ingestion
> change and the answer was a query.)
>
> **(b) THE FIRST TABLE I WROTE HERE WAS WRONG, and finding out why is the better finding.**
> It read:
>
> | Season | titles | moved |
> |---|---|---|
> | Fall 2026 (airing) | 24 | 100% |
> | Summer 2026 | 117 | 85% |
> | Fall 2025 | 160 | 7% |
> | Spring 2025 | 161 | 4% |
>
> and concluded *a score is alive while a show airs and settles within about two seasons*.
> Clean, quotable, and a measurement of the pipeline's own refetch schedule. **The weekly run
> refetches the season it covers and copies every other row forward unchanged**: the 68 Fall
> 2021 TV titles carry a row on all ten snapshots with their `user_count` summing to exactly
> 592,705 every time. Those rows were never asked about, so a flat score says nothing.
>
> Conditioned instead on proof of a real fetch - the source's own vote count moved, a detector
> that does not look at the score - over 544 re-asked readings of TV titles:
>
> | | re-asks | answer differed | enough to print | median change |
> |---|---|---|---|---|
> | Season on air during the window | 297 | 235 (79%) | **103 (35%)** | 0.19 |
> | Season already over | 245 | 86 (35%) | **2 (1%)** | 0.00 |
>
> **A score is never finished being revised. It stops being revised visibly.** A third of the
> readings of a two-year-old season still come back different, two decimal places below
> anything the site prints. Direction is balanced both ways (122 up / 113 down while airing),
> so there is no hype-decay story, which is worth knowing because it is the story everyone
> assumes.
>
> **(c) And before a score moves it has to arrive.** Fall 2026 sat in the catalogue through 4
> runs with no scored title at all, then went 1 to 19 to 55 to 59 of 81 in fifteen days. That
> is the halftone-as-certainty system drawn in time, which is why it is on the page.
>
> Window: 11 snapshots, 2026-09-10 to 2026-10-12. 10 of the 22 seasons were never re-asked
> inside it and are absent from the table rather than listed as settled. 533 of the 544
> re-asks are Kitsu's.

**What is left of this item.** The series deepens by one run a week on its own. Worth revisiting
once there are two full seasons of re-asks, when "how long after a finale" becomes answerable
with real resolution rather than the one cliff the current window can see.

Other things computable from data already on disk, with zero upstream requests:

- a studio's output per year across 22 seasons
- genre share per season, and how it shifts
- which source revises its own numbers most, and in which direction (the re-ask machinery for
  this now exists in `backend/app/routers/scores.py`)
- how many titles a season gains after it starts (the "late listing" tail)

*Why it matters beyond the feature:* this is a pipeline that carefully accumulates a
longitudinal dataset and then renders it as a catalogue. The time series is the thing that
makes it a data project rather than a nice front end over an API.

### 2. [~] Track scores daily for airing titles

Changes are recorded weekly, so a score that moves twice in a week reads as one move and
anything inside the week is invisible. The daily run already queries AniList for the airing
schedule and status; adding `averageScore` for the ~80 currently-airing titles is a handful
more requests inside the same rate limit.

Score movement *during* a season is the actual story, and weekly granularity flattens it.

*Cost:* a few requests a day. *Risk:* low. *Pairs with #1* - it makes the series dense
enough to be worth plotting.

> **Collection shipped 2026-10-16. Nothing reads it yet, and that is the honest state.**
>
> **It cost no requests at all, not "a few a day".** `ingestion/anilist/fetch_status.py`
> already asks AniList about exactly the airing titles every morning at 06:00 UTC, so
> `averageScore` and `popularity` are two more fields on a query that was already going out.
>
> `popularity` is not decoration. `/scores` counts a pair of readings only where the source's
> own vote count moved, because a detector that looks at the score throws away every reading
> that came back the same and reports movement near 100% by construction. AniList's
> `popularity` is that vote count, and without it a daily series cannot tell a score that was
> re-asked and did not move from one that was never asked at all.
>
> **The storage needed no new fetch either, and nearly no new code.**
> `ingestion.storage.write_daily` has been keeping `processed/anilist_status/{date}.parquet`
> as history since the day it was written; only `processed/current/` was ever read, because
> the status check is joined into `anime_media_latest` and the dated glob would cost every
> request a file more each day. `anime_score_daily` reads the glob instead, and it is the only
> view in the warehouse that does: here the history *is* the subject, and nothing else touches
> it. (Fourth time this pattern has come up - the obvious route looked like an ingestion change
> and most of the answer was a query over data already being written.)
>
> Readings with no score are dropped rather than carried as nulls: a title nobody has rated
> has not been measured, which is a different thing from one measured at the same value.
>
> **What is NOT done: nothing serves it.** No endpoint, no page, and the score arc on a title
> page is still the weekly series. That is deliberate rather than unfinished - on the day this
> shipped the view holds nothing, because the first file carrying a score is written by the
> next daily run. A chart of one point is not worth building against, and the shape of the
> dense series is easier to judge once there is a week of it. The view is guarded to not exist
> until some file carries the column, so the warehouse is valid either way.
>
> **Next, once a week or two has accrued:** join it into the title-page score arc for airing
> titles, and re-run `/scores`'s own measurement against daily rather than weekly re-asks. The
> 35%-while-airing figure is computed from weekly pairs; denser readings should move it, and
> whether it moves up or down is the first thing worth knowing.

### 3. [x] "More like this" from vectors that already exist

> **Shipped 2026-10-14, and the premise in this entry was wrong.**
>
> This said: "a SQL query (`array_cosine_similarity` against the row's own vector) over data
> already built, already published and already paid for. *Cost:* none. *Risk:* none. The
> cheapest real feature left." Measured on the live catalogue, that query returns puns.
>
> The search document leads with every name a title has, and deliberately: that is what took
> "type the other name and find it" from 10/40 to 22/40, and `embed.text_for_embedding`
> carries the four documents that were compared to choose it. A vector that leads with names
> matches on names:
>
> | query | what the search index offered |
> |---|---|
> | Blue Box Season 2 | The Blue Orchestra **Season 2**, The Fire Hunter **Season 2**, Pacific Rim: The Black **Season 2** |
> | SPY x FAMILY | **Spy** Classroom, **Spy** x Sect |
> | WITCH WATCH | **Witch** Hat Atelier, **Witch** on the Holy Night, The Dawn of the **Witch** |
>
> **Search and similarity are two different retrieval tasks and cannot share one index.** A
> second document - genres and synopsis, no names - takes the mean genre overlap of the five
> nearest non-franchise neighbours from 0.290 to 0.402, and the examples stop being wordplay:
> Blue Box finds school romances, SPY x FAMILY finds Buddy Daddies, BOCCHI THE ROCK! finds
> BanG Dream and The Colors Within.
>
> **Re-ranking the existing index by genre overlap was tried first**, because it needs no new
> embedding. It scores 0.541 against the second index's 0.402 - and that is the measure being
> optimised, so the number is worthless. The results give it away: SPY x FAMILY still returns
> Spy Classroom and Spy x Sect, BOCCHI still leads with its own recap. Re-ranking reorders a
> candidate pool; it cannot repair one that is already thirty titles sharing a word.
>
> **Three filters were needed before it was usable**, each found by looking at the output:
> titles with no synopsis excluded (533 of them produced identical documents, so two blanks
> were served to each other as perfect matches); the title's own franchise excluded (the page
> lists it directly above); and a 0.10 distance floor, below which it is the same work under
> another name - *Wanmei Shijie 5* with *Perfect World 4*, *The Outcast Season 4* with *5th
> Season*.
>
> **Cost, actual:** ~60s of CPU in the weekly run and 0.8 MB in the warehouse. The neighbours
> are precomputed as rows, not a second vector column, which would have been 9.8 MB on a file
> the API downloads whole on every wake. Serving is a join, 47 ms.
>
> **Known limits, stated on the page:** quality is uneven - tight clusters work, broad fantasy
> does not - and a sequel's neighbours are 69% sequels against a 15% base rate, because sequel
> synopses say "the second season of".

### 4. [~] Backfill depth - after 1-3, and after the serving shape changes

> **40 seasons as of 2026-10-17**, 2017-SPRING to 2027-WINTER, up from 22. Two batches
> through `.github/workflows/backfill.yml`: 2020-WINTER to 2021-SUMMER, then 2017-SPRING to
> 2019-FALL. 10,806 source rows across 54 snapshots, roughly 7,500 titles once merged, in
> about 13 minutes of fetching. The state tarball went 39 MB to 47 MB.
>
> **Stopped at 40 rather than going to 2000, deliberately.** The note below gates the full
> depth on the range-read change; 40 needs nothing, because the cost of the current shape is
> the cold-start download and ~1.8 MB a season is still a cold start in the tens of seconds
> rather than minutes. This is the measurement that decides whether the rest is worth
> building: if the warehouse and the cold start are tolerable here, the ceiling is further
> away than the note assumed.
>
> **None of it is on the site yet.** A backfill writes snapshots into the lake; the catalogue
> is consolidated and the warehouse published by the weekly run. Sunday 00:00 UTC is when
> these 18 seasons become titles.

22 seasons now (Fall 2021 onward). Back to 2000 is ~100 seasons. Upstream rate limits make
it slow but free, spread over weeks.

**Do not start this before the range-read change**, or the 512 MB box becomes the problem
and the whole catalogue has to be reshaped under time pressure instead of calmly.

### What "the range-read change" is, since the phrase appeared once and was never defined

Written down 2026-10-17 because the sentence above was the only mention of it anywhere in the
repository, and it is the gate on this whole item. A blocker that is a phrase rather than a plan
is how an item stays open forever - and this file is not tracked by git, so there was no history
to recover the intent from either.

**The constraint.** `backend/app/warehouse.py` downloads the whole published `warehouse.duckdb`
to the container's disk at startup and serves from it. That is ~40 MB today over 22 seasons. The
container has 512 MB of memory and the ONNX query embedder already holds ~406 MB of it, so
roughly 100 MB is free. A hundred seasons is about five times the catalogue and five times the
vectors; the download alone approaches the headroom, before a query touches it.

**The change: stop holding the file, read the pages a query needs.** DuckDB can `ATTACH` a
database over HTTPS through `httpfs`, read-only by default since 1.1, and it fetches byte ranges
rather than the file.

Measured against the real published warehouse (`state-2026-10-12`, 41.7 MB), served locally with
an 80 ms delay per request to stand in for a round trip to GitHub:

| | downloaded (today) | attached over HTTP |
|---|---|---|
| Before the first answer | ~32 s | **1.08 s** |
| The same queries again | - | **0.00 s**, pages cached in memory |
| Bytes read | 41.7 MB (100%) | **4.5 MB (10.7%)** over 15 requests, 13 of them ranged |
| Disk needed | the whole file | none |

The last row is the one that unblocks this item: bytes per query are a function of what the query
touches, not of how big the catalogue is, so a hundred seasons costs what twenty-two does.

**IT IS GATED ON THE REPOSITORY BEING PUBLIC**, which is the part worth knowing before planning
anything. A private release asset needs a token, and GitHub answers an asset request with a 302
to a signed `objects.githubusercontent.com` URL that the token must not follow - `warehouse.py`
carries a redirect handler for exactly that. Those signed URLs also expire, so a long-lived
`ATTACH` to one would break mid-serve. Public, it is a plain URL and this is a two-line change.
So "make the repo public" and "backfill to 2000" are one decision, not two.

**Caveats, because they decide whether the figures above hold.** Measured on DuckDB **1.5.6**,
while the API pins **1.1.3** - the version that `ATTACH` over HTTP became read-only by default,
but not the one these numbers came from, and 1.1.3 is pinned here for behaviour differences that
have bitten before. Confirm on 1.1.3 before committing to it. The 80 ms stand-in is also a guess
at the real latency from Singapore; the shape (one second, then cached) is what matters, not the
digit. And nothing here tested a cold container losing its page cache on every wake, which is the
case this design lives in.

### 5. [ ] The known data gaps

- 39 titles `airing_unconfirmed` - nothing upstream can confirm them
- 529 with no synopsis (26 fillable, measured)
- ~~romaji search recall 24/40~~ - **done 2026-10-16** (ROADMAP 13). Blending the keyword
  match in worked; adding native titles to the indexed document did not, and was measured
  and reverted. The harness is `ai/search/evaluate.py`, so "measurable before and after" is
  now true rather than aspirational
- 6 Kitsu poster URLs 404 at the origin

---

## Deliberately not doing

**A fourth source.** Three that disagree enough to be interesting, and a merge that handles
it, is the right number. A fourth adds reconciliation work without new questions - and
Jikan was just removed for good reasons.

**More frequent full runs.** Weekly matches how fast the data actually changes. Daily full
runs would spend budget re-deriving identical answers.

**Marking changed titles on grid plates.** It needs a backend change (`changes` is empty on
list rows), the caption is already full at `Ep 3 · 15 Oct JST · TV`, and DESIGN.md bans
decorative markers. The discoverability problem it was logged for is solved by the home page
line. ROADMAP 6 was closed on this basis on 2026-10-16, so the two files now agree.
