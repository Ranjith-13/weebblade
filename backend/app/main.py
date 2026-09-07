from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .routers import anime, digest, search

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

app.include_router(anime.router)
app.include_router(digest.router)
app.include_router(search.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "message": "WeebBlade API",
        "endpoints": ["/anime", "/anime/{source}/{source_id}", "/digest", "/digest/latest", "/search"],
    }
