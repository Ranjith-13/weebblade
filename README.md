# WeebBlade

Anime trend-tracking platform built as an end-to-end data engineering project —
ingestion, orchestration, processing, storage, an API, a frontend, and two AI-assisted
features on real pipeline infrastructure, not a one-off notebook.

Live: [weebblade.duckdns.org](https://weebblade.duckdns.org) (API) ·
[weebblade-airflow.duckdns.org](https://weebblade-airflow.duckdns.org) (Airflow UI, credentialed)

## What it does

Tracks seasonal anime — releases, genre shifts, studio output, scores — pulled weekly from
four independent sources and reconciled into one queryable warehouse:

- [AniList](https://anilist.co/graphiql) (GraphQL)
- [Jikan](https://docs.api.jikan.moe/) (REST, the community MyAnimeList mirror)
- [MyAnimeList API v2](https://myanimelist.net/apiconfig) (REST, the official one — a
  separate source from Jikan, and the only one carrying studios and source material)
- [Kitsu](https://kitsu.docs.apiary.io/) (JSON:API)

Two AI features sit on top:

1. A weekly LLM-generated natural-language trend digest, scoped to one season.
2. Semantic "find similar titles" search over local embeddings + a vector store — not
   just tag-matching.

## Architecture

```
AniList ──┐
Jikan  ───┤
MAL    ───┼──► Airflow ingestion tasks ──► raw JSON + per-source Parquet snapshots
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
                    │         └── airing schedule ◄── AniList, daily: six weeks of episodes
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
  LLM digest   Chroma index   FastAPI (/anime, /schedule, /digest, /search)
     (Groq)   (all-MiniLM-L6-v2)      │
                                      ▼
                          Caddy (TLS, security headers, access logs)
                                      │
                                      ▼
                          Next.js frontend (Vercel)
```

Each ingestion source runs as an independent Airflow task — one API being down doesn't
block the others from landing data, and the downstream merge/digest/search tasks run over
whatever actually arrived rather than requiring every source to succeed. That isn't
theoretical: Jikan has been down upstream for this project's whole life, and AniList was
until September 2026, and the catalogue kept publishing on Kitsu and MAL throughout.

### Merging, not stacking

The four sources describe the same shows in different vocabularies, on different scales,
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

## API

- `GET /catalogue` — the seasons on file with their title counts, the sources that
  contributed, and the total. What a client needs to know about the catalogue without
  paging through it.
- `GET /anime` — filter by `season`, `season_year`, `genre`, `format`, `min_score`,
  `studio` (across every season); `sort` (`score_desc` | `popularity_desc` | `title`),
  `limit`, `offset`.
- `GET /anime/{wb_id}` — a title by its stable identity, following it if it merged, with its
  next few episodes from AniList's airing schedule (`upcoming_episodes`).
- `GET /anime/{wb_id}/franchise` — the title's franchise, oldest first, each entry with its
  relation to the title; entries older than the catalogue come from MAL, with no `wb_id`.
- `GET /anime/{source}/{source_id}` — a title by any source key it was ever made of.
- `GET /schedule?days=7` — every episode airing from midnight today in Japan, for up to 14 days,
  from AniList's schedule. Shows the catalogue does not hold come as AniList describes them.
- `GET /digest`, `/digest/latest`, `/digest/{run_date}` — the weekly LLM trend digest.
- `GET /search?q=...&n=...` — semantic similarity search over indexed titles; each result
  carries its poster, score, format and `wb_id`.
- `GET /health` — liveness.

Read-only, public, unauthenticated. Rate-limited per client IP: 60/min by default,
20/min on `/search` (it runs the embedding model on every call).

## Stack

| Layer | Choice |
|---|---|
| Infra | AWS EC2, managed by Terraform (imported, zero drift) |
| Orchestration | Apache Airflow 2.10.4 (self-hosted, Docker Compose, LocalExecutor) |
| Ingestion | Python — AniList (GraphQL), Jikan / MAL / Kitsu (REST) |
| Processing | PySpark (single-node) |
| Storage | DuckDB views over Parquet |
| Backend | FastAPI + slowapi rate limiting |
| AI | Groq (digest) + sentence-transformers/Chroma (semantic search) |
| Frontend | Next.js 16 App Router, Tailwind v4, GSAP — deployed on Vercel |
| Reverse proxy / HTTPS | Caddy (Let's Encrypt, security headers, access logs) |
| CI/CD | GitHub Actions — pytest and a frontend build/typecheck/lint on every push, auto-deploy `main` to EC2 |

## Repository layout

```
ingestion/    anilist/ jikan/ mal/ kitsu/ — each: client, fetch_season, transform;
              mal/ also fetch_relations (the franchise graph's edges), anilist/ also
              fetch_airing (episode airdates); backfill, reprocess
processing/   spark session, schema normalization, matching, consolidation, identity
              registry, franchise graph, DuckDB catalog
ai/           digest/ (Groq prompt + generation), search/ (embed, index, query)
backend/      FastAPI app — routers, schemas, DuckDB access, rate limiter
frontend/     Next.js app (see frontend/README.md and frontend/DESIGN.md)
airflow/      the weekly DAG, the daily airing-schedule DAG, and their image
infra/        Terraform for the EC2 host and security group
caddy/        Caddyfile and image
scripts/      per-session SSH, off-instance backup pull
tests/        pytest suite
```

## Running it

The whole backend stack runs from Docker Compose:

```bash
cp .env.example .env   # fill in the values it names
docker compose up -d
```

Tests:

```bash
python -m pytest tests/ -v
```

The frontend is separate — see [frontend/README.md](frontend/README.md).

## Operations

- **SSH is closed by default.** No standing rule for a home address; both CI and
  `scripts/weebblade-ssh.sh` authorize a single `/32` for the session and revoke it after,
  using an IAM user scoped to ingress rules on one security group and nothing else.
- **Backups** run nightly on the server, with `scripts/weebblade-backup.sh` pulling an
  off-instance copy — server-local backups sit on the same EBS volume as the data.
- **The Airflow UI sits behind HTTP basic auth** as well as its own login. It runs
  arbitrary code by design, so its pre-authentication surface should not be reachable by
  anything unauthenticated.
- **Schema validation runs at ingest** — see "Merging, not stacking". A failure isolates
  one source rather than the run: the others land, and consolidation carries the failed
  source's previous snapshot forward.
- **fail2ban** watches Caddy's access log and `sshd`, pushing to ntfy on ban — a layer
  below the app-level rate limiting.

## Status

Ingestion → merge → warehouse → both AI features → API → frontend → CI/CD are all live
and verified end-to-end against real data: twenty seasons (Fall 2021 to Summer 2026) and
6,136 titles from three live sources, a franchise graph over 895 franchises, and digests
publishing weekly.

Known gaps: Jikan is down upstream (the pipeline degrades rather than fails). The
frontend runs locally only — it builds, typechecks and lints in CI on every push, but has
not been imported to Vercel. Off-instance backups pull to a second machine rather than
to S3, which still needs an IAM policy.

## License

MIT — see [LICENSE](LICENSE).
