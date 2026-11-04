# WeebBlade

An automated seasonal anime trend-tracking and intelligence platform powered by an end-to-end data engineering pipeline. It collects, reconciles, and enriches data from AniList, MyAnimeList, and Kitsu into an analytical DuckDB warehouse, served via FastAPI and a Next.js edge application with dense vector semantic search and LLM trend synthesis.

Live Application: **[weebblade.vercel.app](https://weebblade.vercel.app)** | Analytical API: **[weebblade-api.onrender.com](https://weebblade-api.onrender.com)**

---

## Documentation Hub

WeebBlade is documented across modular technical specifications. Consult the relevant guide below:

| Specification | Description |
| :--- | :--- |
| **[System & Architecture Overview](PROJECT_OVERVIEW.md)** | Core domain challenges, entity resolution heuristics (`wb_id`), field-level precedence merge, and data flow. |
| **[Deployment & Infrastructure Guide](DEPLOYMENT.md)** | Production hosting across Render and Vercel, 512 MB memory constraints, buffer-pool tuning, environment variables, and backups. |
| **[Frontend Engineering Specification](frontend/ARCHITECTURE.md)** | Next.js 16 App Router implementation, caching boundaries, 502/503 retry policies, and Tokyo JST date calculations. |
| **[Design System Manifesto](frontend/DESIGN.md)** | The "Halftone Almanac" design standard, computed WCAG contrast tokens, and GSAP motion principles. |
| **[Capacity & Growth Analysis](GROWTH.md)** | Compute economics, monthly runner budgets, memory profiles, and quadratic vector search scaling. |
| **[Engineering Decision Ledger](ROADMAP.md)** | Historical decision records, benchmarked cold-start timings, and verified operational boundaries. |
| **[Pipeline Execution Log](RUNS.md)** | Chronological operational log of daily and weekly automated pipeline runs. |

---

## Architecture Overview

```text
AniList (GraphQL) ──┐
MAL API v2 (REST) ──┼──► Ingestion Tasks ──► Raw JSON + Parquet Snapshots
Kitsu (JSON:API)  ──┘         │
                              ▼
            PySpark Consolidation - field-level merge across sources,
            snapshots, and seasons (schema reconciliation, dedup)
                              │
                              ▼
            DuckDB Views over Parquet (dated snapshots + latest per title)
                              │         ▲
                              │         ├── Franchise Graph ◄── MAL relations
                              │         ├── Change Ledger ◄── per-source deltas
                              │         └── Airing Schedule ◄── AniList broadcast slots
                              │
                  ┌───────────┼───────────────────┐
                  ▼           ▼                   ▼
            Groq Digest  Vector Index        FastAPI Backend
            (Grounded)   (MiniLM ONNX)       (/anime, /schedule, /search)
                                                  │
                                                  ▼
                                             Next.js Edge UI
                                             (weebblade.vercel.app)
```

The data pipeline runs automatically via **GitHub Actions**:
- **Daily (06:00 UTC):** Extracts upcoming broadcast slots, detects daily score movements, and publishes refreshed delta views.
- **Weekly (Sunday):** Executes full historical PySpark consolidation across all 40 seasons, builds dense vector search indices, synthesizes seasonal trend digests, and publishes a standalone materialized DuckDB warehouse (`warehouse.duckdb`).

---

## Core Capabilities

- **Cross-Source Entity Resolution:** Unifies conflicting identifier namespaces across AniList, MAL, and Kitsu into durable WeebBlade IDs (`wb_id`).
- **Precedence-Based Field Merging:** Reconciles disparate metadata using defined source authority (MAL for studios/source material, AniList for media/airings, Kitsu for synopsis baselines).
- **Dense Vector Semantic Search:** Queries 384-dimensional text embeddings in-memory using an ONNX runtime port of `all-MiniLM-L6-v2`, keeping resident memory under 400 MB.
- **Automated Trend Synthesis:** Generates natural-language season digests using Groq LLMs grounded in direct aggregate database queries.
- **Halftone Almanac Interface:** A bespoke Next.js frontend utilizing color exclusively to convey data certainty (scored titles in color, unscored titles screened back to halftone).

---

## Quickstart & Local Development

### Prerequisites
- Python 3.11+
- Node.js 20+
- Java 17+ (required for PySpark local execution)

### 1. Ingestion & Pipeline
```bash
# Clone the repository
git clone https://github.com/Ranjith-13/weebblade.git
cd weebblade

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements-dev.txt

# Execute pipeline steps locally
python -m pipeline.run daily
python -m pipeline.run weekly
```

### 2. Backend API
```bash
# Run FastAPI with hot reload
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### 3. Frontend UI
```bash
cd frontend
npm install
npm run dev
```
The frontend starts at `http://localhost:3000` and automatically proxies API requests.

---

## Testing & Quality Assurance

The codebase includes over 45 unit and integration test suites covering API contracts, PySpark transformations, rate limiters, vector search, and ingestion resiliency:

```bash
# Run complete Python test suite
pytest tests/ -v

# Run frontend end-to-end smoke tests (Playwright)
cd frontend
npx playwright test
```

For testing against the pinned production DuckDB binary (`duckdb==1.1.3`), execute:
```bash
scripts/pinned-tests.sh setup
scripts/pinned-tests.sh
```

---

## Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Pipeline & Processing** | Python 3.11, Apache Airflow, PySpark, DuckDB, Parquet |
| **AI & Embeddings** | Groq (Llama 3), ONNX Runtime, sentence-transformers (`all-MiniLM-L6-v2`) |
| **Backend API** | FastAPI, Uvicorn, Pydantic, SlowAPI (Rate Limiting) |
| **Frontend UI** | Next.js 16 (App Router), React, Tailwind CSS, GSAP, Playwright |
| **Infrastructure & CI** | GitHub Actions, Render (Docker), Vercel, GitLab Registry (Backup Mirror) |

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
