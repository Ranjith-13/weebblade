"""Backfill past seasons into the lake.

The weekly pipeline only ever fetches the season it is running in, so the lake
holds exactly as much history as the pipeline has lived through: two seasons, all
of 2026. That is enough to browse a season and nothing more. Every direction this
project is heading needs depth - a franchise page needs the prequels, a "watch
tonight" filter needs finished shows, a creator page needs earlier work - and a
live check found the direct prequel of two airing shows (Re:Zero S3, BLEACH TYBW
Part 3, both Fall 2024) simply absent.

This fetches named past seasons through the SAME fetch, flatten and validate path
the DAG uses, and writes them as ordinary dated snapshots. Nothing downstream
needs to know a backfill happened: consolidate_catalogue already reads every
partition, the catalogue-wide merge already reconciles titles the sources file
under different seasons, and the identity registry mints the new titles while
reusing every existing one.


RUN DATE IS TODAY, THE PARTITION IS THE PAST

A backfilled snapshot is written under the season it describes (2024-FALL) but
stamped with the day it was captured. That is what run_date means everywhere
else: when the data is as of, not what it is about. It also means the next weekly
run keeps it - _current_state reads every snapshot up to its own date, and a
past partition's single snapshot is always earlier.

Past seasons are then frozen at capture. The weekly run only refreshes the
current season, so a 2024 title's score is as of the day it was backfilled.
That is the right trade for finished shows, whose scores barely move, and it is
why this is a command rather than something the DAG does every week.


HOW DEEP

Depth used to be capped by the frontend, which fetched the whole catalogue on
every render, 100 titles a request, against an API that allows 60 requests a
minute per IP. At 2,755 titles that was 28 requests and a 6.6s render; five
years back (~6,500) would have gone over the limit and taken the site down.
That is why the first backfill stopped at two years.

The frontend now reads one season at a time: the season list from GET
/catalogue, then the season on screen (see getSeason in frontend/lib/api.ts).
A render costs one request per 100 titles in that season plus one, however
many seasons are stored, so depth no longer moves it. What can still move it is
the size of a single season, and that is what the command reports.

The second backfill (2026-09-11) went to Fall 2021: twenty seasons, 6,102
titles, the largest season 367 titles and five requests to render. Of fifteen
currently airing sequels sampled, 11 now have their prequel in the catalogue,
up from 7 at two years. The four still missing are older than five years - two
films from 2018 and 2019, a short from Winter 2021, a series from 1991 - so
the next step there is a lookup of specific prequels, not another decade of
whole seasons.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .seasons import partition_for
from .storage import write_parquet, write_raw_json
from .validate import validate_rows

logger = logging.getLogger(__name__)

_ORDER = ["WINTER", "SPRING", "SUMMER", "FALL"]

# Titles per page the frontend requests when it reads a season, and the API's
# per-IP ceiling. Mirrors frontend/lib/api.ts and backend/app/limiter.py; if
# either moves, this check is what goes stale.
_FRONTEND_PAGE = 100
_API_REQUESTS_PER_MINUTE = 60

Fetcher = Callable[[str, int], list[dict[str, Any]]]
Flattener = Callable[[dict[str, Any]], dict[str, Any]]


def _live_sources() -> dict[str, tuple[Fetcher, Flattener]]:
    """The sources that actually answer. Imported lazily so the tests can run
    without network clients, and so a missing MAL client id fails only when MAL
    is asked for.

    Jikan is deliberately absent: it has failed upstream for this project's
    whole life, and a backfill that spends an hour retrying it to land nothing
    is worse than one that does not try. AniList was absent for the same reason
    until it came back on 2026-09-13.
    """
    from .anilist.fetch_season import fetch_season as anilist_fetch
    from .anilist.transform import flatten_media as anilist_flatten
    from .kitsu.fetch_season import fetch_season as kitsu_fetch
    from .kitsu.transform import flatten_media as kitsu_flatten
    from .mal.fetch_season import fetch_season as mal_fetch
    from .mal.transform import flatten_media as mal_flatten

    return {
        "mal": (mal_fetch, mal_flatten),
        "kitsu": (kitsu_fetch, kitsu_flatten),
        "anilist": (anilist_fetch, anilist_flatten),
    }


def parse_season(value: str) -> tuple[str, int]:
    """"2024-FALL" -> ("FALL", 2024)."""
    try:
        year, season = value.split("-")
        season = season.upper()
        if season not in _ORDER:
            raise ValueError
        return season, int(year)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a season - expected YEAR-SEASON, e.g. 2024-FALL"
        ) from None


def seasons_between(start: tuple[str, int], end: tuple[str, int]) -> list[tuple[str, int]]:
    """Every season from start to end inclusive, in broadcast order.

    Quarterly order rather than alphabetical, which would run FALL before SPRING
    and silently skip or repeat seasons across a year boundary.
    """
    index = lambda s: s[1] * 4 + _ORDER.index(s[0])  # noqa: E731
    first, last = index(start), index(end)
    if last < first:
        raise ValueError(f"{end[1]}-{end[0]} is before {start[1]}-{start[0]}")
    return [(_ORDER[i % 4], i // 4) for i in range(first, last + 1)]


@dataclass
class Landed:
    source: str
    partition: str
    rows: int
    error: str | None = None


def backfill(
    seasons: list[tuple[str, int]],
    sources: list[str],
    data_dir: Path,
    run_date: str,
    *,
    dry_run: bool = False,
    fetchers: dict[str, tuple[Fetcher, Flattener]] | None = None,
) -> list[Landed]:
    """Fetch, check and write each (source, season). Returns what landed.

    A failure on one pair is recorded and the rest carry on. A backfill is long,
    re-runnable and writes nothing it cannot overwrite, so abandoning thirty
    successful fetches because the thirty-first timed out would be the wrong
    call. Reruns overwrite the same run_date files, so repeating is safe.
    """
    fetchers = fetchers if fetchers is not None else _live_sources()
    unknown = [s for s in sources if s not in fetchers]
    if unknown:
        raise ValueError(f"unknown source(s) {unknown}; available: {sorted(fetchers)}")

    landed: list[Landed] = []
    for season, year in seasons:
        partition = partition_for(season, year)
        for source in sources:
            fetch, flatten = fetchers[source]
            try:
                raw = fetch(season, year)
                rows = [flatten(m) for m in raw]
                validate_rows(rows, source)
                if not dry_run:
                    write_raw_json(raw, data_dir / "raw" / source / partition, run_date)
                    write_parquet(
                        rows, data_dir / "processed" / f"{source}_media" / partition, run_date
                    )
                landed.append(Landed(source, partition, len(rows)))
                logger.info("%s %s: %s titles%s", source, partition, len(rows),
                            " (dry run, not written)" if dry_run else "")
            except Exception as exc:  # recorded, not raised - see docstring
                landed.append(Landed(source, partition, 0, f"{type(exc).__name__}: {exc}"))
                logger.error("%s %s failed: %s", source, partition, exc)
    return landed


def projected_requests(titles: int) -> int:
    return -(-titles // _FRONTEND_PAGE)  # ceiling division


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("start", type=parse_season, help="first season, e.g. 2024-FALL")
    parser.add_argument("end", type=parse_season, help="last season, e.g. 2026-WINTER")
    parser.add_argument("--sources", default="mal,kitsu,anilist")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--run-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="the capture date to stamp; defaults to today (UTC)",
    )
    parser.add_argument("--dry-run", action="store_true", help="fetch and check, write nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    seasons = seasons_between(args.start, args.end)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    print(f"{len(seasons)} season(s) x {len(sources)} source(s), stamped {args.run_date}"
          f"{' - DRY RUN' if args.dry_run else ''}")

    landed = backfill(seasons, sources, args.data_dir, args.run_date, dry_run=args.dry_run)

    failed = [l for l in landed if l.error]
    fetched = sum(l.rows for l in landed)
    # Source rows overcount titles: the same show arrives from several sources and
    # the merge collapses them. The live ratio has been about 0.7 titles per row.
    estimate = round(fetched * 0.7)
    print(f"\nfetched {fetched} source rows across {len(landed) - len(failed)} snapshot(s); "
          f"roughly {estimate} titles once merged")
    per_season: dict[str, int] = {}
    for l in landed:
        per_season[l.partition] = per_season.get(l.partition, 0) + l.rows
    if per_season:
        largest = max(per_season, key=per_season.get)
        titles = round(per_season[largest] * 0.7)
        # +1: the season list, fetched alongside the season itself.
        print(f"the largest, {largest} at ~{titles} titles, takes ~{projected_requests(titles) + 1} "
              f"requests to render, against a limit of {_API_REQUESTS_PER_MINUTE} a minute")
    for l in failed:
        print(f"  FAILED {l.source} {l.partition}: {l.error}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
