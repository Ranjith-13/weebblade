# WeebBlade - Deployment & Operations Guide

This guide details the production deployment, infrastructure architecture, environment configuration, and operational monitoring for WeebBlade across Render, Vercel, and GitHub Actions.

---

## 1. Hosting Architecture Overview

The system operates entirely on zero-cost tiers across decoupled cloud providers:

| Layer | Platform | Runtime Profile | Constraints & Bounds |
| :--- | :--- | :--- | :--- |
| **Backend API** | Render | Docker Container (Debian base) | 512 MB RAM, ephemeral disk, sleep after 15m idle |
| **Frontend UI** | Vercel | Next.js 16 (App Router) | Edge caching, serverless SSR, client-side search |
| **Orchestration** | GitHub Actions | Ubuntu Runners | 2,000 min/month allowance, <60 min per job limit |
| **State Storage** | GitHub Releases | Release Assets | State tarball (`state.tar.gz`) published per run |
| **Backup Mirror** | GitLab | Package Registry | Off-site redundancy via SHA-256 checksum ledger |

### Infrastructure Evolution
The API and frontend originally ran on a single AWS EC2 instance behind Caddy, orchestrated by Airflow in a Docker Compose stack. To achieve a zero-cost operational model and eliminate recurring compute costs (~$63/month), the stack was re-architected into serverless automation and edge hosting. On 13 October 2026, the EC2 instance, EBS volumes, and security groups were decommissioned. The `airflow/` directory remains in the repository: the DAGs define the step-by-step pipeline contracts that GitHub Actions reimplements, and their requirements file serves as the version pin for all downstream environments.

---

## 2. Backend Container Deployment (Render)

The API is defined in `render.yaml` as an infrastructure blueprint.

### Memory & Disk Engineering (512 MB Boundary)
Operating within Render's free 512 MB memory boundary with no persistent storage shaped two key engineering decisions:
1. **Stateless Boot & Release Downloads:** The container downloads the latest materialized DuckDB warehouse (`warehouse.duckdb`) from GitHub Release assets during startup (`backend/app/warehouse.py`) and serves it in-memory.
2. **ONNX Runtime Embeddings:** Text embeddings for search queries use an ONNX-runtime port of `all-MiniLM-L6-v2` (`ai/search/embed.py`), holding resident memory at 406 MB versus ~868 MB under PyTorch.
3. **Buffer Pool Bounds:** DuckDB naturally sizes its buffer pool from visible host memory. In containerized environments where the container sees host memory, this causes OOM crashes. Bounding DuckDB to a 192 MB buffer pool and 2 execution threads (`backend/app/db.py`) caps total process footprint at ~406 MB under peak load.

### Cold Start & Warm-up
A container on Render sleeps after 15 minutes of inactivity and requires ~30-40 seconds to pull the warehouse and wake. To prevent user confusion:
- The frontend registers a lightweight warmup ping on first interaction.
- The search interface displays an indeterminate progress bar while waiting for container boot.

---

## 3. Environment Configuration & Variables

### A. Render Dashboard Variables
Configure the following in the Render service settings:

| Variable | Description | Value / Format |
| :--- | :--- | :--- |
| `WAREHOUSE_REPO` | Repository hosting published release assets | `Ranjith-13/weebblade` |
| `ALLOWED_ORIGINS` | Permitted frontend origins for CORS | `https://weebblade.vercel.app` |
| `ALLOWED_ORIGIN_REGEX` | Permitted preview branch patterns | `^https://weebblade-git-[^.]+-ranjith-13\.vercel\.app$` |
| `GITHUB_TOKEN` | Fine-grained token (Contents: Read) | Required for release asset downloads |

### B. GitHub Actions Secrets
Configure in GitHub Repository Settings -> Secrets and variables -> Actions:

| Secret | Role |
| :--- | :--- |
| `GROQ_API_KEY` | API key for automated weekly LLM season digest generation |
| `MAL_CLIENT_ID` | Official MyAnimeList API v2 client identifier |
| `NTFY_TOPIC` | Optional notification topic on ntfy.sh for pipeline alert notifications |
| `GITLAB_TOKEN` | Access token for the off-site mirror package registry |

### C. GitHub Actions Repository Variables
| Variable | Value | Role |
| :--- | :--- | :--- |
| `API_IS_LIVE` | `true` | Un-gates frontend CI builds and smoke tests |
| `API_BASE_URL` | `https://weebblade-api.onrender.com` | Target URL for Next.js prerendering during CI |

---

## 4. Frontend Deployment (Vercel)

The frontend is deployed as a standard Next.js application on Vercel:
1. Set **Root Directory** to `frontend`.
2. Configure **Environment Variables**:
   - `NEXT_PUBLIC_API_BASE_URL`: The deployed API address (`https://weebblade-api.onrender.com`).
   - `NEXT_PUBLIC_SITE_URL`: The production web URL (`https://weebblade.vercel.app`).

### Rate-Limit Protection via Edge Caching
All server-side reads go through Next.js 16 cache boundaries (`use cache` + `cacheLife('hours')`). Because the pipeline publishes daily and refetches the catalog weekly, hourly caching prevents frontend visitors from depleting the shared backend IP rate limit. Search executes strictly client-side so individual users consume only their personal rate allocation.

---

## 5. Operations, Backups & Verification

### Disaster Recovery & Mirroring
- **Release Assets:** Pipeline state (`state.tar.gz`) is versioned and published as release assets across workflow runs.
- **Off-Site GitLab Mirror:** `pipeline/mirror.py` pushes state copies to GitLab's package registry. Cryptographic SHA-256 hashes and archive sizes are recorded in `MIRROR.md`.
- **Local Snapshot Pulls:** `scripts/weebblade-backup.sh` pulls release state archives locally twice weekly, ensuring historical datasets remain independent of single-vendor accounts.

### Dependency Pinning & Pinned Tests
`airflow/requirements.txt` pins `duckdb==1.1.3` because a warehouse written by a newer DuckDB release cannot be read by an older engine. To test against the exact production binary:
```bash
scripts/pinned-tests.sh setup    # Setup local venv matching pinned binary
scripts/pinned-tests.sh          # Execute test suite
```

### Health Monitoring
- Endpoint `GET /health` reports the current served release tag, warehouse timestamp, and health status.
- A `null` warehouse response triggers an automated restart and 3-stage retry sequence (`ensure_warehouse`).
