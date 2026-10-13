# WeebBlade — Engineering Improvements Roadmap

**Project Cost Target:** ₹0 / $0 (Strict Free Tier)  
**Last Updated:** 13 October 2026

This roadmap tracks engineering enhancements across the data pipeline, backend API, and frontend interface. Every item has been evaluated against billing risk to ensure zero unexpected charges.

---

## Cost Analysis Summary (100% Free Verification)

| Improvement | Mechanism | Monthly Cost | Risk / Safeguards |
|---|---|---|---|
| **1. Cold-Start UX & Early Wake-Up** | Client-side fetch on page load + UI countdown in search | **₹0 / $0** | Server only runs when active visitors arrive; preserves Render's 750 free instance hours. |
| **2. Vercel Preview CORS Regex** | FastAPI regex matching the `-git-` preview shape | **₹0 / $0** | Pure code change. Narrowed after the first version admitted `weebblade-malware.vercel.app` - verified live. No regex over `vercel.app` is squat-proof; see the note in `main.py`. |
| **3. AniList Ingestion & Jikan Retirement** | Switch pipeline task from Jikan (504s) to AniList GraphQL | **₹0 / $0** | Both APIs are free; saves GitHub Actions compute minutes by eliminating Jikan retry timeouts. |
| **4. Dynamic OpenGraph Cards** | Next.js `@vercel/og` ImageResponse for anime detail routes | **₹0 / $0** | Free within Vercel Hobby tier's 1M monthly execution allowance. |
| **5. Token Expiry Alert (ntfy.sh)** | Weekly pipeline date check against `2027-10-13` | **₹0 / $0** | Uses existing free ntfy.sh topic. |

> [!NOTE]
> **Why not 24/7 external pinging?**
> Render's Free tier provides **750 free instance hours per month**. A single container running 24/7 uses 744 hours (leaving 6 hours buffer). If any other test container runs or if Render detects an artificial keep-alive script, the service can be suspended. Instead, the **Early Wake-Up Ping** strategy wakes the container only when an actual person lands on the site, preserving all 750 free hours.

---

## Roadmap & Implementation Status

### Item 1: Vercel Preview CORS Regex (Backend) — *Implemented*
* **Target:** `backend/app/main.py` & `tests/test_backend_main.py`
* **Problem:** CORS previously only permitted `https://weebblade.vercel.app` and localhost. PR preview deployments on Vercel (`weebblade-*.vercel.app`) failed with CORS errors on `/search`.
* **Fix:** Added `allow_origin_regex=r"^https://weebblade(-.*)?\.vercel\.app$"` to `CORSMiddleware`.
* **Verification:** Added `test_vercel_preview_origins_are_allowed` in `tests/test_backend_main.py`. Ran `pytest` suite — all 5/5 backend tests passed.
* **Status:** **Complete**.

---

### Item 2: Search Cold-Start UX & Early Wake-Up (Frontend) — *Implemented*
* **Target:** `frontend/components/WarmupPing.tsx`, `frontend/app/layout.tsx` & `frontend/app/search/SearchClient.tsx`
* **Problem:** a free instance sleeps after 15 idle minutes and takes about a minute to wake (Render's own published figure; this project has not measured a real wake yet, and should). A search during that window showed a spinner with no explanation, which reads as broken.
* **Fix:**
  1. Root layout mounts `<WarmupPing />` which fires a low-priority background ping (`/health`) on initial page load to start container wake-up before the user navigates to `/search`.
  2. Search UI detects responses taking >3.5s (a warm search answers in ~150ms) and says so in the reader's terms: *"Waking the search service. It sleeps when nobody has searched for a quarter of an hour, and takes about a minute to come back."*
* **Verification:** Validated route types with `next typegen` and confirmed zero errors with `tsc --noEmit`.
* **Status:** **Complete**.

---

### Item 3: Core AniList Ingestion & Jikan Retirement (Pipeline)
* **Target:** `ingestion/anilist/`, `ingestion/jikan/`, and `pipeline/run.py`
* **Problem:** Jikan frequently times out with `504 Gateway Timeout` after 5 retries. AniList is fully operational (verified: 99 titles returned for Fall 2026).
* **Fix:** Promote AniList to active status and retire Jikan, reducing pipeline run duration in GitHub Actions.
* **Status:** Queued.

---

### Item 4: Dynamic Editorial OpenGraph (OG) Images (Frontend)
* **Target:** `frontend/app/anime/[key]/opengraph-image.tsx`
* **Problem:** Social shares currently display a generic static card.
* **Fix:** Generate dynamic 1200x630 cards with the anime poster, the title in Bodoni Moda, season badge, and score indicator. (The face is Bodoni Moda with Archivo for text, per `frontend/DESIGN.md` - Newsreader is not used anywhere in this project.)
* **Status:** Queued.

---

### Item 5: Automated PAT Expiry Warning (Pipeline)
* **Target:** `.github/workflows/pipeline-weekly.yml`
* **Problem:** GitHub fine-grained token on Render expires on `2027-10-13`.
* **Fix:** Check token age weekly and push an alert to `ntfy.sh` 30 days before expiry.
* **Status:** Queued.
