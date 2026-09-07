from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..schemas import DigestResponse

router = APIRouter(prefix="/digest", tags=["digest"])

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DIGESTS_DIR = DATA_DIR / "digests"


@router.get("", response_model=list[str])
def list_digests() -> list[str]:
    if not DIGESTS_DIR.exists():
        return []
    return sorted((p.stem for p in DIGESTS_DIR.glob("*.md")), reverse=True)


@router.get("/latest", response_model=DigestResponse)
def latest_digest() -> DigestResponse:
    # Registered before /{run_date} so "latest" isn't swallowed by that path param.
    files = sorted(DIGESTS_DIR.glob("*.md"), reverse=True) if DIGESTS_DIR.exists() else []
    if not files:
        raise HTTPException(503, "No digest generated yet")
    return DigestResponse(run_date=files[0].stem, content=files[0].read_text(encoding="utf-8"))


@router.get("/{run_date}", response_model=DigestResponse)
def get_digest(run_date: str) -> DigestResponse:
    path = DIGESTS_DIR / f"{run_date}.md"
    if not path.exists():
        raise HTTPException(404, f"No digest found for {run_date}")
    return DigestResponse(run_date=run_date, content=path.read_text(encoding="utf-8"))
