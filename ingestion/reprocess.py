"""Re-run a source's transform over the raw responses already stored.

Every fetch writes the unmodified API response to data/raw/ before flattening
it. This is what that is for. When a transform changes - a genre synonym map, a
unit conversion - the fix belongs in every stored season, not only the ones
fetched after it shipped, and re-downloading years of seasons to get it would
mean hundreds of API calls for data already on disk.

So this reads each stored raw file, flattens it with the CURRENT transform,
checks it, and rewrites the matching processed snapshot under the same partition
and run_date. Nothing else changes: the snapshot keeps its capture date, so it
means exactly what it meant before, just transformed correctly.

What this re-applies is the TRANSFORM, not the fetch. Filtering that happens at
fetch time - MAL's rule dropping entries that start in another season - is baked
into what the raw file holds. A raw file written before such a rule existed would
need refetching, not reprocessing.

Processed snapshots are derived data, so overwriting one is safe; the raw file
it is rebuilt from is never touched. Each file is validated before it replaces
anything, so a transform that produces bad rows leaves the old snapshot in place.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .storage import write_parquet
from .validate import validate_rows

logger = logging.getLogger(__name__)

Flattener = Callable[[dict[str, Any]], dict[str, Any]]


def _flatteners() -> dict[str, Flattener]:
    from .kitsu.transform import flatten_media as kitsu_flatten
    from .mal.transform import flatten_media as mal_flatten

    return {"mal": mal_flatten, "kitsu": kitsu_flatten}


@dataclass
class Rewritten:
    partition: str
    run_date: str
    rows: int
    error: str | None = None


def reprocess(
    source: str,
    data_dir: Path,
    *,
    dry_run: bool = False,
    flatteners: dict[str, Flattener] | None = None,
) -> list[Rewritten]:
    """Rebuild every processed snapshot of `source` from its stored raw response."""
    flatteners = flatteners if flatteners is not None else _flatteners()
    if source not in flatteners:
        raise ValueError(f"no transform for {source!r}; available: {sorted(flatteners)}")
    flatten = flatteners[source]

    out: list[Rewritten] = []
    for raw_path in sorted((data_dir / "raw" / source).glob("*/*.json")):
        partition, run_date = raw_path.parent.name, raw_path.stem
        try:
            rows = [flatten(m) for m in json.loads(raw_path.read_text())]
            validate_rows(rows, source)
            if not dry_run:
                write_parquet(rows, data_dir / "processed" / f"{source}_media" / partition, run_date)
            out.append(Rewritten(partition, run_date, len(rows)))
        except Exception as exc:  # recorded so one bad file does not stop the rest
            out.append(Rewritten(partition, run_date, 0, f"{type(exc).__name__}: {exc}"))
            logger.error("%s %s/%s failed, snapshot left as it was: %s", source, partition, run_date, exc)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", help="mal or kitsu")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    done = reprocess(args.source, args.data_dir, dry_run=args.dry_run)
    failed = [d for d in done if d.error]
    for d in done:
        print(f"  {'FAILED ' if d.error else ''}{args.source} {d.partition}/{d.run_date}: "
              f"{d.error or f'{d.rows} rows'}")
    print(f"{len(done) - len(failed)} snapshot(s) rebuilt, {len(failed)} failed"
          f"{' - DRY RUN, nothing written' if args.dry_run else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
