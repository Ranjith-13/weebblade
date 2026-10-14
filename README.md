# WeebBlade

Anime trend-tracking platform built as an end-to-end data engineering project —
ingestion, orchestration, processing, storage, an API, a frontend, and two AI-assisted
features on real pipeline infrastructure, not a one-off notebook.

Live: **[weebblade.vercel.app](https://weebblade.vercel.app)** · API:
[weebblade-api.onrender.com](https://weebblade-api.onrender.com) — both free, serving the warehouse
the pipeline publishes weekly. See [Where it runs](#where-it-runs).

## What it does

Tracks seasonal anime — releases, genre shifts, studio output, scores — pulled weekly from
three independent sources and reconciled into one queryable warehouse:

- [AniList](https://anilist.co/graphiql) (GraphQL)
- [MyAnimeList API v2](https://myanimelist.net/apiconfig) (REST, the official one, and the
  only source carrying studios and source material)
- [Kitsu](https://kitsu.docs.apiary.io/) (JSON:API)

A fourth, [Jikan](https://docs.api.jikan.moe/) — the community MyAnimeList mirror — was
fetched until October 2026. Its public API was discontinued on the 1st after a brownout
from September, and it had never once landed a row here. MAL's own API covers what it
was for.

Two AI features sit on top:

1. A weekly LLM-generated natural-language trend digest, scoped to one season.
2. Semantic "find similar titles" search over local embeddings + a vector store — not
   just tag-matching.

## Architecture

```
AniList ──┐
MAL    ───┼──► ingestion tasks ──► raw JSON + per-source Parquet snapshots
Kitsu  ───┘         │
                    ▼
            PySpark consolidation — field-level merge across sources, snapshots
            and seasons (schema reconciliation, score normalization, dedup)
                    │
                    ▼
            DuckDB views over Parquet (dated snapshots + a "latest per title" view)
                    │         ▲
                    │         ├── franchise graph ◄── MAL related titles, followed
                    │         │                       past the catalogue until complete
                    │         ├── changes ◄── each source's fetch against its last one
                    │         └── airing schedule ◄── AniList, daily: six weeks of episodes
                    │
        ┌───────────┼───────────────────┐
        ▼           ▼                   ▼
  LLM digest   vector index        FastAPI (/anime, /schedule, /digest, /search)
     (Groq)    (all-MiniLM-L6-v2 vectors, a table in the warehouse)
```

The pipeline runs on **GitHub Actions** — daily at 06:00 UTC, weekly on Sunday — calling the
same functions the Airflow DAGs call (`python -m pipeline.run daily|weekly`). A runner starts
empty, so each run pulls the state it needs from a GitHub release asset, works, and publishes it
back; a weekly run also publishes a materialised warehouse, one self-contained file holding the
catalogue and the vectors.

<a id="where-it-runs"></a>
The API and the Next.js frontend ran on a single AWS EC2 box behind Caddy, orchestrated by
Airflow in a Docker Compose stack. It cost about $63/month to serve a portfolio site, so the
pipeline was moved off it rather than paid for, and on 13 October 2026 the instance, its volume,
its security group and its key pair were deleted — along with the Terraform, Caddyfile and SSH
tooling that described them. `airflow/` stays: the DAGs are what GitHub Actions reimplements
step for step, and its requirements file is the version pin everything else constrains against.

The API is now a container built from [`backend/Dockerfile`](backend/Dockerfile), deployed from
[`render.yaml`](render.yaml) on a free instance: 512 MB of memory, no persistent disk, and no way
to bill anyone — with no payment method on file, Render suspends a Free service that exceeds its
allowances rather than charging for them. Two consequences shaped the code:

- **No disk.** The API downloads the published warehouse at startup
  ([`backend/app/warehouse.py`](backend/app/warehouse.py)) and serves it from the container's
  own filesystem. That artifact was already being built weekly and had no reader.
- **512 MB.** Search queries are embedded through ONNX rather than torch — 406 MB resident
  against 868, same weights, vectors identical to 3e-7
  ([`ai/search/embed.py`](ai/search/embed.py)). Measured end to end, the whole serving process
  peaks at 382 MB: app, model, catalogue reads and five searches.

It sleeps after 15 minutes without a request and takes about a minute to wake, so the first
visitor after a quiet spell waits. The frontend goes to Vercel's free tier.

Each ingestion source runs as an independent task — one API being down doesn't
block the others from landing data, and the downstream merge/digest/search tasks run over
whatever actually arrived rather than requiring every source to succeed. That isn't
theoretical: AniList was down upstream until September 2026 and Jikan for its whole life
here, and the catalogue kept publishing on Kitsu and MAL throughout.

### Merging, not stacking

The sources describe the same shows in different vocabularies, on different scales,
under different transliterations, and don't agree which season a title starts in.
Consolidation is a **field-level** merge over the whole catalogue, not a union of rows:

- Rows are one title when they share a MAL id, or an exact title with the same format
  and year (ONA, OVA and special counting as one - the sources file a short release under
  whichever they like), or an exact title - English or romaji - and premiere date. Every row's own titles count, and matches
  join transitively, so adding a source can only join titles: an AniList row carrying
  MAL's id and Kitsu's title joined 47 pairs the catalogue had listed twice. Two rows of
  one source mapped to different MAL ids are never joined by a title - MAL's two parts of
  *The Tale of The Spirit Stone* share an English title, format and year.
- Per column, the first non-null value in source-priority order wins — so a title takes
  its streaming links and cover art from Kitsu and its studios from MAL in the same row.
  AniList ranks below both: it joined after five years of the catalogue were built from
  them, so it fills gaps rather than replacing what they said - 75 scores and 237 studio
  lists, and banner art, trailers and streaming links for 529, 667 and 629 more titles.
- Genres are the exception: tags add, so a title carries every source's genres, Kitsu's
  first. Taking one winner's list dropped MAL's tags wherever Kitsu also held the show.
  This works only because MAL's genre names are mapped onto Kitsu's at ingest, so
  Sci-Fi and Science Fiction never end up on the same title.
- Sources are matched across snapshots, not per dated file — they aren't fetched on the
  same day, and an exact-date lookup silently dropped whole sources.
- Scores are normalized to one scale (MAL rates 0–10, Kitsu and AniList 0–100; all land
  in `score_100`, and the frontend shows them out of 10), and durations to one unit.
- Every source is checked against the shared schema *before* it is written. Units and
  vocabulary are the thing most likely to be got wrong when adding a source, and a whole
  column on the wrong scale is far cheaper to catch at ingest than on the live site.
  It caught AniList on its first live run, when its transform - written while AniList
  was down - passed "MOVIE" and "RELEASING" straight through.

### Airdates

MAL has a weekly broadcast slot and no airdates; Kitsu fills episode dates in after they air.
AniList publishes the real schedule, so a second, daily DAG lands every episode airing in the
next six weeks (and the day behind) - 540 episodes, eleven requests. It stores the episodes, not
each title's next one: a single next date is stale the moment it airs, while a list lets whoever
reads it pick the first still ahead. The warehouse view reads the newest day's file at query time,
so the daily fetch never opens the warehouse to write. The site shows it as a countdown on each
airing title's page and a week of dated episodes on `/schedule`, including long-runners older than
the catalogue, like One Piece.

The same DAG asks AniList whether the titles the sources call airing still are. The merged status
is the winner's as of the title's snapshot, and it called 81 shows airing that AniList had as
finished, Yu-Gi-Oh! Go Rush!! a year and a half after its finale. The warehouse's latest-title view
corrects `status` from AniList's answer, keeping the sources' own as `merged_status`, so every
list, count and page agrees; a title page shows MAL's weekly slot only while a show is airing.
Answers and episodes are placed on titles by AniList id, then MAL id - and for a title only Kitsu
lists, by the MAL id Kitsu maps it to, where no other title carries it and neither AniList nor MAL
knows the title under another id.
Each daily fetch writes one current file for the views to read, so a query costs the same on day
300 as on day one.

### Franchises

A title page lists the rest of its franchise: prequels, sequels, side stories, spin-offs and
alternative versions, oldest first, including entries older than the catalogue itself.

- MAL keeps a title's related titles off its season listing, so they are fetched one request
  per title. Each chunk lands raw and processed as it arrives, so a fetch that dies resumes
  where it stopped, and a title gone from MAL is recorded rather than retried every week.
- The fetch follows **story** relations outward past the catalogue, in passes, until a pass
  finds nothing new: a sequel the catalogue holds leads to its prequel, and that prequel to the
  first season. Stopping at the catalogue's edge had every franchise begin one step outside it.
- A franchise is a connected component over story relations only. Shared characters and MAL's
  "other" link are stored but do not join: a cameo special or a collaboration music video
  would chain unrelated franchises into one.
- After the first full fetch a weekly run asks only about new titles, airing ones, and what
  they newly name, within a budget.

The first build fetched 8,589 titles in all - the 5,493 catalogue titles with a MAL id, then
3,096 beyond it over 19 passes that shrank from 845 to one. It holds 895 franchises over 5,173
titles, 2,041 of them in the catalogue. The largest are what they should be: Gundam (130),
Detective Conan (129), Doraemon (108), Pokémon (95), One Piece (72). Laid-Back Camp runs from
its 2018 first season to a 2027 fourth; stopping at the catalogue's edge had it begin at the
second.

### What changed

Each title records what its sources report differently from one fetch to the next: a finale,
an episode count, a premiere date or a delay to another season, a new trailer or streaming
link, a score as the page prints it, or an entry a source has just created. It shows on the
title's page and feeds the digest's "since last week" paragraph.

- **Each source against itself.** Changes come from each source's own snapshots, never the
  merged catalogue, which changes whenever the pipeline does: between two September snapshots
  AniList joined and 59 titles merged, and a catalogue diff would have "added" banner art to
  529 titles. Every change keeps the name of the source that reported it.
- **News, not noise.** Member counts and ranks moved for most titles in every pair of
  snapshots, and poster URLs churn with the CDN, so neither counts. A field an older snapshot
  lacks is not compared, and most of a listing gaining a value at once is taken as the pipeline
  filling a field.
- **New means created.** An entry counts as new only if its id is above every one its source
  had listed before. When Kitsu's paging fix served 112 entries for the first time, two were
  new; "not seen before" would have called all 112 new.

Seeded from every snapshot on file: 98 changes back to 30 August 2026, each on its title.

## API

- `GET /catalogue` — the seasons on file with their title counts, the sources that
  contributed, and the total. What a client needs to know about the catalogue without
  paging through it.
- `GET /anime` — filter by `season`, `season_year`, `genre`, `format`, `min_score`,
  `studio` (across every season); `sort` (`score_desc` | `popularity_desc` | `title`),
  `limit`, `offset`.
- `GET /anime/{wb_id}` — a title by its stable identity, following it if it merged, with its
  next few episodes from AniList's airing schedule (`upcoming_episodes`) and what its sources
  have changed about it (`changes`).
- `GET /changes?days=7` — every change recorded in the days up to the newest fetch, with its
  title; one change told by several sources is one entry naming them all.
- `GET /anime/{wb_id}/franchise` — the title's franchise, oldest first, each entry with its
  relation to the title; entries older than the catalogue come from MAL, with no `wb_id`.
- `GET /anime/{source}/{source_id}` — a title by any source key it was ever made of.
- `GET /schedule?days=7` — every episode airing from midnight today in Japan, for up to 14 days,
  from AniList's schedule. Shows the catalogue does not hold come as AniList describes them.
- `GET /digest`, `/digest/latest`, `/digest/{run_date}` — the weekly LLM trend digest.
- `GET /runs?dag=&limit=10` — what recent pipeline runs checked about their own output: their
  numbers, and what failed them, if anything did.
- `GET /scores/settling` — what a score does over its life, read down the warehouse's time
  axis: when a season acquires its numbers, and how often a re-asked reading comes back
  different. The one endpoint here whose unit is a *re-ask* rather than a row, because most
  rows in most runs are copies of the week before.
- `GET /search?q=...&n=...` — semantic similarity search over indexed titles; each result
  carries its poster, score, format and `wb_id`.
- `GET /health` — liveness.

Read-only, public, unauthenticated. Rate-limited per client IP: 60/min by default,
20/min on `/search` (it runs the embedding model on every call).

## Stack

| Layer | Choice |
|---|---|
| Infra | GitHub Actions runs the pipeline; state in release assets. The API is a Docker container on a free 512 MB instance (`render.yaml`) that fetches the published warehouse at startup; the frontend is on Vercel. An AWS EC2 box served it until October 2026 and is gone |
| Orchestration | GitHub Actions on a schedule, calling `pipeline/run.py`. The Airflow 2.10.4 DAGs are the same steps in the same order and ran it on the server until October 2026 |
| Ingestion | Python — AniList (GraphQL), MAL / Kitsu (REST) |
| Processing | PySpark (single-node) |
| Storage | DuckDB views over Parquet |
| Backend | FastAPI + slowapi rate limiting |
| AI | Groq (digest) + `all-MiniLM-L6-v2`; the vectors are a DuckDB table searched with `array_cosine_similarity`. The index is built with sentence-transformers, queries embedded through ONNX to fit 512 MB — a test asserts the two agree |
| Frontend | Next.js 16 App Router, Tailwind v4, GSAP — Vercel free tier |
| Reverse proxy / HTTPS | Terminated by the hosts. Caddy (Let's Encrypt, security headers, access logs) did this on the EC2 box until October 2026 |
| CI/CD | GitHub Actions — pytest (including the Spark merge suite) and a frontend typecheck/lint on every push. The frontend build and smoke tests prerender against the live API, so they are gated behind the `API_IS_LIVE` repository variable |

## Repository layout

```
ingestion/    anilist/ jikan/ mal/ kitsu/ — each: client, fetch_season, transform;
              land.py fetches a season for any of them (the DAG and the CLI share it);
              mal/ also fetch_relations (the franchise graph's edges), anilist/ also
              fetch_airing, resolve_ids and bridge_ids (ids found by title search);
              backfill, reprocess
processing/   spark session, schema normalization, matching, consolidation, identity
              registry, franchise graph, changes between fetches, DuckDB catalog;
              bridge.py decides which MAL id a row should carry and
              mal_id_overrides.py holds the ones asserted by hand; publish.py
              materialises the warehouse into something portable
ai/           digest/ (Groq prompt + generation), search/ (embed, index, query)
backend/      FastAPI app — routers, schemas, DuckDB access, rate limiter
frontend/     Next.js app (see frontend/README.md and frontend/DESIGN.md)
airflow/      the weekly DAG, the daily airing-schedule DAG, and their image
scripts/      the twice-weekly pull of published state to a
              second machine
pipeline/     run.py runs the DAGs' work without Airflow; state.py carries the lake
              between runs as release assets
tests/        pytest suite
```

## Running it

The pipeline is a command — the same functions in the same order the DAGs call them, which is
what GitHub Actions runs and what a laptop can run:

```bash
python -m pipeline.run daily
python -m pipeline.run weekly --dry-run
```

A failing step is recorded and the run carries on, exactly as `trigger_rule=ALL_DONE` makes it
behave in the DAG; the run's own check decides the outcome and sets the exit code.

Tests:

```bash
python -m pytest tests/ -v
```

Two modules ask for a real SparkSession and skip where PySpark is absent, so a laptop without a
JVM runs about 380 of them and CI runs all 428 - the merge is a window function over every column,
which is exactly the kind of code that looks right and behaves differently at runtime. CI installs
PySpark and has a JVM, so any change to `processing/consolidate.py` is proved there on the push
rather than anywhere local.

The frontend is separate — see [frontend/README.md](frontend/README.md).

## Deploying

Both halves are free and neither can bill: with no payment method on file, each provider
suspends rather than charges.

**The API** — [`render.yaml`](render.yaml) is a Render blueprint. New > Blueprint, point it at
this repository, and it asks for the one value the file deliberately does not carry:

| Variable | Value |
|---|---|
| `GITHUB_TOKEN` | A fine-grained token, **Contents: read**, this repository only. Required while the repository is private, since the warehouse is a release asset; worth setting even if it goes public, because unauthenticated GitHub API calls are capped at 60/hour per IP and a free container's outbound address is shared. **The one in use expires 2027-10-13** (GitHub caps these at a year). When it lapses the API keeps serving the warehouse it already has, then 503s after its next restart — the log says `GITHUB_TOKEN is expired, revoked or wrong`. Regenerate at [github.com/settings/personal-access-tokens](https://github.com/settings/personal-access-tokens) and update it in Render. |
| `WAREHOUSE_REPO` | Already set to this repository. Setting it is what switches the API from "read a mounted file" to "fetch the newest published warehouse". |
| `ALLOWED_ORIGINS` | The frontend's origin. Update it if the Vercel project is named something else — `/search` is fetched from the browser, so an origin missing here is a search box that fails. |

**The frontend** — a Vercel project with **Root Directory** set to `frontend`, and
`NEXT_PUBLIC_API_BASE_URL` set to the API's URL.

**Then, in this repository's settings** — set the variable `API_IS_LIVE` to `true`, which
un-gates the frontend build and the Playwright smoke tests, and `API_BASE_URL` to the same URL
so CI prerenders against the real thing. Delete the now-unused AWS secrets
(`WEEBBLADE_SSH_KEY`, `WEEBBLADE_HOST`, `WEEBBLADE_USER`, `WEEBBLADE_SG_ID`,
`CI_AWS_ACCESS_KEY_ID`, `CI_AWS_SECRET_ACCESS_KEY`).

`GET /health` reports which release the API is serving, which is the only way to tell a stale
container from a current one once the warehouse is fetched rather than mounted.

## Operations

- **Backups.** The pipeline publishes its state as a release asset after every run, and
  `scripts/weebblade-backup.sh` pulls that to a second machine twice a week (Sunday after the
  weekly run, Wednesday for what the dailies added), keeping two weeks. The point is the same
  as it was when the state lived on an EBS volume: a year of ingested history should not sit
  in one company's account. The irreplaceable file is `identity/registry.parquet` - everything
  else can be rebuilt from the parquet, and that cannot.
- **Every run checks its own output before calling itself done.** Each DAG ends in a task that
  reads what the run produced, compares it with the run before and fails the run on a source
  that landed nothing or half as much, a title lost or split, a burst of merges, a warehouse
  still serving last week's catalogue, or a task that failed in the middle - which, with every
  step running whatever happened upstream, would otherwise leave the run green. It reads output,
  not the tasks' reports of themselves: run against the 2026-09-14 re-merge, it found two titles
  split that consolidation had counted as new. The numbers are kept and served at `/runs`, and
  a failed run is pushed to the same ntfy topic as the server's other alerts.
- **Schema validation runs at ingest** — see "Merging, not stacking". A failure isolates
  one source rather than the run: the others land, and consolidation carries the failed
  source's previous snapshot forward.
- **Rate limiting is per client IP** — 60/min, 20/min on `/search`, which runs a model on
  every call. On the EC2 box fail2ban sat below this, watching Caddy's log and `sshd`; the
  hosts handle that layer now.

## Status

**The pipeline runs itself, for nothing.** Ingestion → merge → warehouse → digest → search
index all run on GitHub Actions, verified end to end on real data: 22 seasons and 6,359 titles
from three live sources, a franchise graph, and a weekly digest. A weekly run takes about 13
minutes and a daily about one, against 2,000 free minutes a month, and with no payment method on
the account the workflows stop at the quota rather than billing anything.

**It is live, for nothing.** It ran on one EC2 box until 7 October 2026, stopped because
$63/month to host a portfolio site was the wrong trade. It is now a container on a free 512 MB
instance that downloads the published warehouse at startup — measured rather than assumed before
being chosen, and measured again in the container: **199 MiB of 512**, searches in 150 ms, all
6,359 titles and vectors and eight digests. The frontend is on Vercel's free tier.

With the API answering, CI's frontend build and Playwright smoke tests run again (they prerender
against it, and had been gated off since the box stopped) — so a page that renders an empty shell
is caught on the push rather than by a reader.

**Known gaps, stated plainly:**

- Jikan, the fourth source, was never once reachable here, and its public API was
  discontinued on 1 October 2026; it has been removed. The pipeline degrading rather than
  failing is why that cost nothing: the catalogue was built from Kitsu, MAL and AniList
  throughout.
- The frontend has never been deployed. It typechecks and lints in CI on every push; the build
  and smoke tests are gated behind `API_IS_LIVE`, because they prerender against a live API — so
  until the API answers, nothing proves a page still renders.
- Terraform's state file for the EC2 box was lost, so it was torn down through the API rather
  than by `terraform destroy`. Nothing remains: instance, volume, security group and key pair
  are deleted, and a sweep of all 18 enabled regions found no instance, volume, Elastic IP or
  snapshot anywhere.
- The catalogue's identity is rule-based and occasionally wrong in both directions — a title can
  split when a source renames it, or two rows can stay apart when no rule can see they are one
  show. Each run checks its own output and fails loudly when that happens, which is how the last
  three were found.

## License

MIT — see [LICENSE](LICENSE).
