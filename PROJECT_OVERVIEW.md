# WeebBlade — project overview

**A seasonal anime discovery application powered by a multi-source data pipeline.**

Built by Ranjith S K. This document explains the product and its engineering story for a demo, portfolio review, or interview. For setup and repository details, see [README.md](README.md).

## The 30-second pitch

> I built WeebBlade to turn anime data from different providers into one usable seasonal catalogue. You can browse shows, explore studios and source material, check weekly broadcast slots, search by meaning, and read a generated season digest. Behind the interface, I built a pipeline that collects, validates, normalizes, and merges the data, then serves it through an API. The main engineering challenge was making inconsistent and sometimes unavailable sources work together without pretending the resulting data is complete.

## Why I built it

Anime makes a useful domain for a real data-engineering project: several providers describe the same titles, but their identifiers, names, score scales, release classifications, and available fields differ. A useful interface depends on resolving those differences correctly.

WeebBlade connects that engineering work to something a person can use. Instead of ending with a cleaned dataset, the project carries the data through to discovery pages, schedules, search, and summaries. That makes problems visible: a bad merge becomes a duplicate show, a missing field becomes an empty fact, and stale data becomes an outdated page.

## Who it serves

| Person | What they can use it for |
|---|---|
| Someone choosing seasonal anime | Browse a season and narrow the catalogue by interests and available metadata. |
| Someone following airing shows | See recurring broadcast slots grouped by day, with local-time information. |
| Someone exploring beyond a familiar title | Follow studio and source-material links, or search using a description. |
| Someone wanting a season overview | Read an AI-generated digest based on warehouse summaries. |
| An engineering reviewer | Inspect a complete path from external APIs to a working application and its operational tooling. |

These are intended uses. The project does not yet establish measured user adoption or prove that it saves users time.

## What gap it addresses

The practical gap is between **data being available somewhere** and **that data being consistent enough to power one application**.

A title may have streaming links in one source and studio information in another. Names may differ, scores may use different scales, and an API may fail during a scheduled run. WeebBlade brings the available fields together, standardizes their representation, and presents them through a shared catalogue.

The product brings seasonal browsing, weekly slots, semantic discovery, and generated summaries into one experience. Its strongest demonstrated distinction is the integration behind that experience. It does not establish that these features are unique or that it is more complete than established anime services.

## What the application does today

- **Seasonal browsing:** explore collected seasons, with TV as the default and other formats available. Filter by genre and source material, and explore studio catalogues.
- **Title details:** see available scores out of 10, synopsis, artwork, studios, source material, trailers, streaming links, and source-site links.
- **Weekly schedule:** view known recurring broadcast slots by Japanese weekday, with local-time information. These are weekly slots, not confirmed individual episode releases.
- **Semantic search:** find catalogue entries by meaning using text embeddings, rather than relying only on exact title matches. This is not personalized recommendation.
- **Season digest:** read generated commentary grounded in aggregate catalogue queries. It remains generated text that can need review.
- **Public read-only API:** access catalogue data, title details, search, and digests programmatically.

Not every title has every field. An absent score means the merged record has no usable score; it does not prove that nobody has rated the show elsewhere.

## How it works

```text
External anime APIs
        ↓
A scheduler — GitHub Actions now, Airflow before it — runs independent collection tasks
        ↓
Raw JSON saved → transformed rows validated → Parquet snapshots
        ↓
PySpark normalizes fields and merges matching titles across sources
        ↓
DuckDB exposes the consolidated catalogue through queryable views
        ↓
Catalogue queries + semantic search index + generated digest
        ↓
FastAPI serves the data → Next.js presents it to the user
```

Three source integrations are implemented: Kitsu, official MyAnimeList, and AniList. A fourth, Jikan, was a community mirror of MyAnimeList rather than an independent dataset; it was never reachable during this project and its public API was discontinued on 1 October 2026, so it has been removed. Kitsu and official MAL supplied most of the catalogue in recent runs; source reachability can change.

The merge chooses populated fields using a defined source priority. It does not average provider scores into a new rating. Dated snapshots support inspection and reprocessing, while prior source data can remain available when a fresh collection fails. That improves continuity but also means some displayed fields may be older than others.

## What I built and what it demonstrates

| Work | Engineering skill demonstrated |
|---|---|
| API clients and source transforms | Working with different API protocols, schemas, and vocabularies. |
| Ingest validation and normalization | Detecting malformed data and reconciling score scales, durations, and field types. |
| Catalogue-wide field merging | Entity matching, deduplication, source precedence, and handling missing values. |
| Scheduled workflow and Parquet history | Scheduled processing, task dependencies, and repeatable data processing. The same steps run from Airflow DAGs or from a command, which is what let the pipeline move hosts without rewriting it. |
| DuckDB warehouse and FastAPI | Turning processed data into a queryable application service. |
| Embedding search and digest generation | Applying existing AI models to a concrete dataset; no claim of training a model. |
| Next.js frontend and design system | Translating the data model into browsing, detail, search, and schedule surfaces. |
| Tests, CI, containers, access controls, and backups | Operating the application beyond a local prototype. |

The stack includes Python, Airflow, PySpark, Parquet, DuckDB (including its vector search), FastAPI, sentence-transformers and ONNX, Groq, Next.js, Tailwind, GSAP, Docker, and GitHub Actions — which now runs the pipeline as well as the tests. It ran on AWS EC2 behind Caddy, with Docker Compose and Terraform, until October 2026.

## What is complete, and what is not

At the documented October 2026 milestone, the pipeline runs on GitHub Actions at no cost, with 6,356 catalogue entries across 22 seasons; its state travels between runs as a release asset. The API and frontend ran on an AWS EC2 box that was decommissioned in October 2026. The API is deployed as a container on Render's free tier (`weebblade-api.onrender.com`), downloading the published warehouse at startup instead of sharing a disk with the pipeline, and the frontend is live on Vercel (`weebblade.vercel.app`). Counts change as ingestion and matching improve.

The main limitations are:

- Coverage depends on collected sources; some scores, artwork, links, and schedules are missing.
- Weekly collection is not real-time episode tracking.
- Matching rules can leave duplicates or incorrectly combine similar records; field-level contribution and freshness need clearer tracking.
- Search-index replacement and data publication need stronger protection against partial failures.
- The application has no personal watchlists, user-submitted ratings, or personalized recommendations.
- Backups are a twice-weekly pull of the published state to a second machine; a third copy, independent of GitHub, remains an improvement.

This is a functioning portfolio application with real operational work behind it. It is not yet a proven large-scale consumer service.

## How to present it in a demo

1. **Start with the problem:** multiple sources describe the same anime differently, and useful discovery requires bringing those records together.
2. **Show the product:** browse a season, open a title, follow a studio link, then show the schedule and a descriptive search.
3. **Show the flow:** explain how collection becomes validated snapshots, merged records, and user-facing pages.
4. **Explain one hard problem:** show how matching titles and filling fields across providers is different from simply stacking API responses.
5. **Show engineering evidence:** point to validation, merge tests, CI, and a completed pipeline run. Use current evidence rather than promising every source succeeds.
6. **Close with the next improvement:** better coverage and per-field freshness/provenance, followed by measured user feedback and reliability improvements.

For a technical interview, spend more time on matching and failure handling. For a potential user, spend more time on what they can discover and how the schedule helps them.

## Where the product can go next

The next useful step is to measure missing fields and stale records, then improve coverage where users feel those gaps. Stronger identity matching and field-level source tracking would make the catalogue easier to trust. Confirmed episode information would make the schedule more useful than recurring slots alone.

Once people can use the hosted frontend, their feedback can guide whether watchlists, alerts, richer comparisons, or other discovery features deserve priority. Those are future directions, not shipped features.
