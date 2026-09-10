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
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
  LLM digest   Chroma index   FastAPI (/anime, /digest, /search)
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
theoretical: AniList and Jikan have both been down upstream for most of this project's
life, and the catalogue has kept publishing on Kitsu and MAL throughout.

### Merging, not stacking

The four sources describe the same shows in different vocabularies, on different scales,
under different transliterations, and don't agree which season a title starts in.
Consolidation is a **field-level** merge over the whole catalogue, not a union of rows:

- Per column, the first non-null value in source-priority order wins — so a title takes
  its streaming links and cover art from Kitsu and its studios from MAL in the same row.
- Sources are matched across snapshots, not per dated file — they aren't fetched on the
  same day, and an exact-date lookup silently dropped whole sources.
- Scores are normalized to one scale (MAL rates 0–10, Kitsu 0–100; both land in
  `score_100`, and the frontend shows them out of 10), and durations to one unit.
- Every source is checked against the shared schema *before* it is written. Units and
  vocabulary are the thing most likely to be got wrong when adding a source, and a whole
  column on the wrong scale is far cheaper to catch at ingest than on the live site.

## API

- `GET /anime` — filter by `season`, `season_year`, `genre`, `format`, `min_score`;
  `sort` (`score_desc` | `popularity_desc` | `title`), `limit`, `offset`.
- `GET /anime/{source}/{source_id}` — single title detail.
- `GET /digest`, `/digest/latest`, `/digest/{run_date}` — the weekly LLM trend digest.
- `GET /search?q=...&n=...` — semantic similarity search over indexed titles.
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
ingestion/    anilist/ jikan/ mal/ kitsu/ — each: client, fetch_season, transform
processing/   spark session, schema normalization, consolidation, DuckDB catalog
ai/           digest/ (Groq prompt + generation), search/ (embed, index, query)
backend/      FastAPI app — routers, schemas, DuckDB access, rate limiter
frontend/     Next.js app (see frontend/README.md and frontend/DESIGN.md)
airflow/      the weekly DAG and its image
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
and verified end-to-end against real data: two seasons and ~480 titles in the catalogue
today, digests publishing weekly.

Known gaps: AniList and Jikan are down upstream (the pipeline degrades rather than
fails), and **the frontend has not been deployed yet** — it builds, typechecks and lints
in CI on every push, but the Vercel import is a dashboard flow that hasn't been done, so
the site currently runs locally only. Off-instance backups pull to a second machine
rather than to S3, which still needs an IAM policy.

## License

MIT — see [LICENSE](LICENSE).
