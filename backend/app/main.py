from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .limiter import limiter
from .routers import anime, catalogue, digest, search

logger = logging.getLogger(__name__)


def _warm_up_search_model() -> None:
    """Pre-load the sentence-transformers model at startup rather than on the first
    search request - loading it takes several seconds, and nobody should eat that
    latency on a live request. Best-effort: if it fails, /search will surface a
    clear error on actual use rather than the app refusing to start.
    """
    try:
        from ai.search.embed import get_embedder

        get_embedder()
    except Exception:
        logger.warning("Could not warm up the search embedding model at startup", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warm_up_search_model()
    yield


app = FastAPI(title="WeebBlade API", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Wide open deliberately, not an oversight: this is a fully public, unauthenticated,
# read-only JSON API (no cookies, no sessions, nothing CORS would meaningfully be
# protecting here) and the eventual frontend's origin isn't decided yet (Vercel?
# GitHub Pages? something else?). Tighten to a specific origin once that's settled,
# and definitely before any endpoint ever handles credentials or mutations.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(anime.router)
app.include_router(catalogue.router)
app.include_router(digest.router)
app.include_router(search.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "message": "WeebBlade API",
        "endpoints": [
            "/anime",
            "/anime/{wb_id}",
            "/anime/{source}/{source_id}",
            "/catalogue",
            "/digest",
            "/digest/latest",
            "/search",
        ],
    }
