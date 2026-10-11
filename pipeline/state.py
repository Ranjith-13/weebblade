"""Where the pipeline's state lives between runs.

A GitHub Actions runner starts empty and is destroyed afterwards, but this
pipeline is stateful: every run reads the snapshots, the identity registry and
the AniList ledgers that previous runs wrote, and a run that cannot see them
would mint a fresh identity for all 6,349 titles. So each run pulls the state,
works, and pushes it back.

It lives in GitHub release assets. Not because nothing else would do, but
because of what it does not need: no account anywhere else, no card on file, no
credentials to store or rotate (Actions' own token is enough), and no way for it
to bill anyone - GitHub's docs put no limit on the total size of a release or
its bandwidth, and the 2 GB cap is per file against our 35 MB. Cloudflare R2 is
the better object store and was the first choice until the obvious came up:
it wants a card, and its usage is not capped.

NOT actions/upload-artifact, which is the thing that looks right and is not:
artifacts count against a 500 MB quota on a private repository and expire in 90
days. Releases are a separate allowance with neither property.

The interface is deliberately four functions over tar and the gh CLI. If GitHub
ever objects, or the project outgrows this, swapping in S3 is this file and
nothing else - which is the actual insurance, rather than a promise that a free
thing stays free.

WHAT IS STATE AND WHAT IS NOT

Kept: processed/ (every source snapshot, the catalogue, the ledgers), identity/
(the registry - the one irreplaceable thing here, since a lost registry means
every title changes address), and raw/ (the archived API responses, which cost
10 MB compressed and are what makes reprocessing possible).

Not kept: warehouse.duckdb and the digests, which any run rebuilds from the
above in seconds - and which could not travel anyway, since the warehouse's
views carry the absolute path of the machine that built them.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tarfile
from pathlib import Path

logger = logging.getLogger(__name__)

# One release per run date, so history is browsable and rollback is picking an
# older tag. Both a daily and a weekly run can land on one date (Sundays), and
# the second simply replaces the assets on that day's release.
TAG_PREFIX = "state-"
STATE_ASSET = "state.tar.gz"

# What travels between runs.
KEPT = ("processed", "identity", "raw")

# How many dated releases to keep. Not a limit anyone imposes - GitHub's only
# hard cap is 2 GB per file - but an unpruned pile of 35 MB tarballs is how a
# project becomes the "significantly excessive" usage its acceptable use policy
# reserves the right to throttle.
KEEP_RELEASES = 8


def _gh(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _releases() -> list[str]:
    """Every state release, newest first."""
    out = _gh("release", "list", "--limit", "100", "--json", "tagName,createdAt")
    tags = [
        r["tagName"] for r in sorted(json.loads(out or "[]"),
                                     key=lambda r: r["createdAt"], reverse=True)
        if r["tagName"].startswith(TAG_PREFIX)
    ]
    return tags


def fetch_state(data_dir: Path) -> str | None:
    """Restore the newest published state into `data_dir`.

    Returns the tag restored, or None on the very first run, when starting from
    nothing is correct rather than fatal.
    """
    tags = _releases()
    if not tags:
        logger.warning("No published state yet - starting from an empty lake")
        return None

    tag = tags[0]
    data_dir.mkdir(parents=True, exist_ok=True)
    _gh("release", "download", tag, "--pattern", STATE_ASSET, "--dir", str(data_dir), "--clobber")

    archive = data_dir / STATE_ASSET
    with tarfile.open(archive, "r:gz") as tar:
        # filter="data" explicitly: it refuses absolute paths and links that
        # point outside the destination, and it is the default only from Python
        # 3.14. Pinning it means the runner behaves like the laptop.
        tar.extractall(data_dir, filter="data")
    archive.unlink()

    kept = [d for d in KEPT if (data_dir / d).exists()]
    logger.info("Restored state from %s (%s)", tag, ", ".join(kept))
    return tag


def publish_state(data_dir: Path, run_date: str) -> str:
    """Write the state back, as the assets of that date's release."""
    tag = f"{TAG_PREFIX}{run_date}"
    archive = data_dir / STATE_ASSET
    with tarfile.open(archive, "w:gz") as tar:
        for name in KEPT:
            path = data_dir / name
            if path.exists():
                tar.add(path, arcname=name)

    _ensure_release(tag, run_date)
    _gh("release", "upload", tag, str(archive), "--clobber")
    size = archive.stat().st_size / 1e6
    archive.unlink()
    logger.info("Published state to %s (%.1f MB)", tag, size)
    return tag


# NOT published here: warehouse.duckdb. It is derived - any run rebuilds it from
# the lake in about a second - but more to the point, publishing the one this
# pipeline builds would ship a trap. refresh_catalog bakes the ABSOLUTE path of
# each parquet file into every view at CREATE VIEW time, so a warehouse built at
# /home/runner/... resolves to nothing anywhere else, and it fails by returning
# no rows rather than by erroring. The serving artifact Phase 4 needs is a
# warehouse whose views have been materialised into tables, which is portable
# and 4-12x faster to query; that belongs with the work that consumes it.


def prune(keep: int = KEEP_RELEASES) -> list[str]:
    """Delete the oldest state releases, keeping the newest `keep`."""
    stale = _releases()[keep:]
    for tag in stale:
        _gh("release", "delete", tag, "--yes", "--cleanup-tag")
    if stale:
        logger.info("Pruned %s old state release(s): %s", len(stale), ", ".join(stale))
    return stale


def _ensure_release(tag: str, run_date: str) -> None:
    if _gh("release", "view", tag, "--json", "tagName", check=False):
        return
    _gh("release", "create", tag, "--notes",
        f"Pipeline state after the run of {run_date}. "
        "Asset: state.tar.gz - processed, identity and raw.",
        "--title", f"State {run_date}")
