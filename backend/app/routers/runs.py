from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Query

from ..schemas import RunCheck

router = APIRouter(prefix="/runs", tags=["runs"])
logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
RUNS_DIR = DATA_DIR / "processed" / "runs"


@router.get("", response_model=list[RunCheck])
def runs(
    dag: str | None = Query(None, description="anime_seasonal_pipeline or anilist_airing"),
    limit: int = Query(10, ge=1, le=100),
) -> list[RunCheck]:
    """What recent pipeline runs checked about their own output, newest first:
    their numbers, and what failed them if anything did. Written by each DAG's
    last task; see processing/run_checks.py."""
    pattern = f"{dag}/*.json" if dag else "*/*.json"
    files = sorted(RUNS_DIR.glob(pattern), key=lambda p: (p.stem, p.parent.name), reverse=True) if RUNS_DIR.exists() else []
    out: list[RunCheck] = []
    for path in files:
        if len(out) == limit:
            break
        try:
            out.append(RunCheck(**json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            # One unreadable record costs its own entry, not the list.
            logger.warning("Could not read run record %s", path, exc_info=True)
    return out
