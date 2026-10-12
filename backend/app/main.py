from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from . import warehouse
from .db import DATA_DIR
from .limiter import limiter
from .routers import anime, catalogue, changes, digest, runs, schedule, search

logger = logging.getLogger(__name__)

# How often a long-lived process re-checks for a newly published warehouse. The
# weekly run publishes once a week, so this only has to be shorter than that to
# be correct; six hours means a reader is at most six hours behind a release
# without the service having to be redeployed to notice one.
#
# On a free container that sleeps after fifteen idle minutes this will rarely
# fire at all - the wake-up fetch does the job. It is here for the case where
# the service stays warm, where without it the catalogue would freeze at
# whatever was published the day it last started.
REFRESH_HOURS = float(os.environ.get("WAREHOUSE_REFRESH_HOURS", "6"))

# Who may call this from a browser. Narrowed from "*", which it was while there
# was no frontend origin to name.
#
# Not a security boundary, and worth being honest about which: every endpoint
# here is public, unauthenticated and read-only, there are no cookies and no
# sessions, so CORS is not protecting data - a determined reader can curl any of
# this, and CORS has never applied to curl. What it does is stop another site
# from making this 512 MB container its own free backend, which on a plan whose
# bandwidth allowance is the thing that gets suspended is worth stopping.
#
# /search is fetched from the browser (frontend/app/search/SearchClient.tsx), so
# this list is load-bearing for that page rather than decorative: an origin
# missing from it gets a search box that fails. Hence localhost and the
# Playwright port stay in by default, and ALLOWED_ORIGINS overrides the lot.
DEFAULT_ORIGINS = (
    "https://weebblade.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3100",
)


def _allowed_origins() -> list[str]:
    configured = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not configured:
        return list(DEFAULT_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _warm_up_search_model() -> None:
    """Load the embedding model at startup rather than on the first search.

    Loading it takes seconds, and nobody should eat that latency on a live
    request - least of all here, where the first request after a wake-up is
    already paying for the container starting and the warehouse downloading.

    Best-effort: a failure leaves /search to surface a clear error on actual
    use, rather than the app refusing to start. It also logs which backend it
    got, which is the one line worth reading in a cold-start log - see
    ai/search/embed.get_query_embedder.
    """
    try:
        from ai.search.embed import get_query_embedder

        backend, _ = get_query_embedder()
        logger.info("Search model ready (%s)", backend)
    except Exception:
        logger.warning("Could not warm up the search embedding model at startup", exc_info=True)


async def _refresh_periodically() -> None:
    while True:
        await asyncio.sleep(REFRESH_HOURS * 3600)
        # to_thread, because ensure_warehouse is blocking socket and disk work
        # and this runs on the loop that is also serving requests.
        await asyncio.to_thread(warehouse.ensure_warehouse, DATA_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Before the model, deliberately: the download is what decides whether this
    # process can answer anything at all, and a health check arriving during
    # startup should wait for it rather than find an empty box.
    warehouse.ensure_warehouse(DATA_DIR)
    _warm_up_search_model()

    refresher = asyncio.create_task(_refresh_periodically()) if REFRESH_HOURS > 0 else None
    try:
        yield
    finally:
        if refresher is not None:
            refresher.cancel()


app = FastAPI(title="WeebBlade API", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(anime.router)
app.include_router(catalogue.router)
app.include_router(changes.router)
app.include_router(digest.router)
app.include_router(runs.router)
app.include_router(schedule.router)
app.include_router(search.router)


@app.get("/health")
def health():
    """Alive, and which day's catalogue it is serving.

    The tag is here because the answer stopped being obvious: the warehouse used
    to be a file on a volume someone could look at, and is now a release asset
    this process chose and downloaded. Without this, "is the site stale?" has no
    answer short of comparing counts by hand.
    """
    return {
        "status": "ok",
        "warehouse": warehouse.state["tag"],
        "warehouse_origin": warehouse.state["origin"],
    }


@app.get("/")
def root():
    return {
        "message": "WeebBlade API",
        "endpoints": [
            "/anime",
            "/anime/{wb_id}",
            "/anime/{source}/{source_id}",
            "/catalogue",
            "/changes",
            "/digest",
            "/digest/latest",
            "/runs",
            "/schedule",
            "/search",
        ],
    }
