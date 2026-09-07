# WeebBlade

Anime/manga trend-tracking platform built as an end-to-end data engineering project: ingestion,
orchestration, storage, and two AI-assisted features on top of real pipeline infrastructure
rather than a one-off notebook.

## What it does

Tracks anime/manga trends (seasonal releases, studio output, genre shifts over time) sourced from
the [AniList GraphQL API](https://anilist.co/graphiql). Two AI features sit on top of the
pipeline output:

1. A weekly LLM-generated natural-language trend digest.
2. Semantic "find similar titles" search using local embeddings + a vector store — not just
   tag-matching.

## Stack

| Layer | Choice |
|---|---|
| Infra | Terraform → AWS EC2 |
| Orchestration | Apache Airflow (self-hosted) |
| Ingestion | Python + AniList GraphQL API |
| Processing | PySpark (single-node) |
| Storage | DuckDB + Parquet |
| Backend | FastAPI |
| Frontend | React (GitHub Pages) |
| Reverse proxy / HTTPS | Caddy |
| CI/CD | GitHub Actions → GHCR → deploy to VM |
| AI | Groq/Gemini free-tier API (digest) + sentence-transformers/Chroma (semantic search) |

## Status

Early scaffolding — infra is up, pipeline and app code are being built out incrementally.

## License

MIT — see [LICENSE](LICENSE).
