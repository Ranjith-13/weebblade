# WeebBlade

Anime/manga trend-tracking platform built as an end-to-end data engineering project —
ingestion, orchestration, processing, storage, an API, and two AI-assisted features on
real pipeline infrastructure, not a one-off notebook.

## What it does

Tracks anime trends (seasonal releases, genre shifts, studio output) pulled weekly from
three independent sources — [AniList](https://anilist.co/graphiql),
[Jikan](https://docs.api.jikan.moe/) (MyAnimeList), and [Kitsu](https://kitsu.docs.apiary.io/) —
reconciled into one queryable warehouse. Two AI features sit on top:

1. A weekly LLM-generated natural-language trend digest.
2. Semantic "find similar titles" search over local embeddings + a vector store — not
   just tag-matching.

## Architecture

```
AniList ──┐
Jikan  ────┼──► Airflow ingestion tasks ──► raw JSON + per-source Parquet
Kitsu  ────┘         │
                      ▼
              PySpark consolidation (schema reconciliation, score normalization)
                      │
                      ▼
              DuckDB warehouse (dated snapshots + a "latest per title" view)
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
   LLM digest   Chroma search   FastAPI (/anime, /digest, /search)
      (Groq)   (sentence-transformers)
```

Each ingestion source runs as an independent Airflow task — one API being down doesn't
block the others from landing data, and the downstream processing/digest/search tasks
run over whatever actually arrived that week rather than requiring every source to
succeed.

## API

- `GET /anime` — filter by season, genre, format, minimum score; sortable, paginated.
- `GET /anime/{source}/{source_id}` — single title detail.
- `GET /digest`, `/digest/latest`, `/digest/{run_date}` — the weekly LLM trend digest.
- `GET /search?q=...` — semantic similarity search over indexed titles.

## Stack

| Layer | Choice |
|---|---|
| Infra | AWS EC2 (Terraform config written, not yet applied) |
| Orchestration | Apache Airflow (self-hosted, Docker) |
| Ingestion | Python — AniList (GraphQL), Jikan + Kitsu (REST) |
| Processing | PySpark (single-node) |
| Storage | DuckDB + Parquet |
| Backend | FastAPI |
| AI | Groq (digest) + sentence-transformers/Chroma (semantic search) |
| Reverse proxy / HTTPS | Caddy |
| CI/CD | GitHub Actions — test on every push, auto-deploy `main` |
| Frontend | React (GitHub Pages) — not yet built |

## Status

Ingestion → processing → storage → both AI features → API → CI/CD are all live and
verified end-to-end against real data. The frontend is the one piece not yet built.

## License

MIT — see [LICENSE](LICENSE).
