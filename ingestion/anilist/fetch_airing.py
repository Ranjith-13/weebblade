"""AniList's episode airing schedule: when each episode airs, for countdowns.

MAL has no next-episode date, only a weekly broadcast slot, and Kitsu backfills
episode dates after they air (see ingestion/kitsu/fetch_season.py). AniList
publishes the real schedule, episode by episode, to the minute.


A WINDOW OF EPISODES, NOT A NEXT-EPISODE DATE

AniList also offers nextAiringEpisode per title, and storing that would be
simpler and wrong: it is stale the moment that episode airs, and the site
caches pages for an hour. So this stores every episode airing in the WINDOW_DAYS
after a run, and whoever reads it picks the first one still ahead. A page
rendered from yesterday's fetch still counts down to the right episode.

One query covers every airing show at once - the schedule is a list of
episodes, not a property of titles - so it reaches what the season fetch
cannot: a two-cour show filed under last season, and long-runners older than
the catalogue (One Piece, Detective Conan), which keep a place on the schedule
even without a title page here. Measured 2026-09-14: 280 episodes in 21 days,
six requests. That is cheap enough to run daily, which matters: schedules
slip, and a countdown to a delayed episode is worse than none.

Adult titles are dropped, as the season query leaves them out.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ..storage import write_raw_json
from .client import AniListClient
from .transform import _FORMATS

logger = logging.getLogger(__name__)

WINDOW_DAYS = 21
PER_PAGE = 50

AIRING_QUERY = """
query ($page: Int, $perPage: Int, $from: Int, $to: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo {
      hasNextPage
    }
    airingSchedules(airingAt_greater: $from, airingAt_lesser: $to, sort: TIME) {
      id
      episode
      airingAt
      media {
        id
        idMal
        isAdult
        format
        episodes
        title {
          romaji
          english
        }
        coverImage {
          medium
        }
      }
    }
  }
}
"""

# Typed explicitly, so a run that finds nothing still writes a file the
# warehouse view can read, rather than one with no columns at all.
SCHEMA = pa.schema(
    [
        ("anilist_id", pa.int64()),
        ("mal_id", pa.int64()),
        ("episode", pa.int32()),
        # Seconds since the epoch, UTC, as AniList gives it. Nothing is
        # converted to a timezone until something displays it.
        ("airing_at", pa.int64()),
        # Enough to draw a title the catalogue does not hold.
        ("title", pa.string()),
        ("format", pa.string()),
        ("episodes", pa.int32()),
        ("poster_url", pa.string()),
        ("fetched_on", pa.string()),
    ]
)


def fetch_airing(start: int, end: int, client: AniListClient | None = None) -> list[dict[str, Any]]:
    """Every non-adult episode airing after `start` and before `end` (epoch seconds)."""
    client = client or AniListClient()
    found: list[dict[str, Any]] = []
    seen: set[int] = set()
    page = 1
    while True:
        data = client.query(
            AIRING_QUERY, {"page": page, "perPage": PER_PAGE, "from": start, "to": end}
        )["Page"]
        for node in data["airingSchedules"]:
            media = node.get("media") or {}
            if node["id"] in seen or media.get("isAdult"):
                continue
            seen.add(node["id"])
            found.append(node)
        if not data["pageInfo"]["hasNextPage"]:
            return found
        page += 1


def flatten_airing(node: dict[str, Any], fetched_on: str) -> dict[str, Any]:
    media = node.get("media") or {}
    title = media.get("title") or {}
    return {
        "anilist_id": media.get("id"),
        "mal_id": media.get("idMal"),
        "episode": node.get("episode"),
        "airing_at": node.get("airingAt"),
        "title": title.get("english") or title.get("romaji"),
        "format": _FORMATS.get(media.get("format") or ""),
        "episodes": media.get("episodes"),
        "poster_url": (media.get("coverImage") or {}).get("medium"),
        "fetched_on": fetched_on,
    }


def land_airing(
    data_dir: Path, run_date: str, start: int, client: AniListClient | None = None
) -> int:
    """Fetch the window from `start`, land it raw and processed, return the count.

    One file per run date, so a retry rewrites the same file and a later run
    never has to merge with an earlier one: the warehouse reads the newest.
    """
    raw = fetch_airing(start, start + WINDOW_DAYS * 86400, client)
    write_raw_json(raw, data_dir / "raw" / "anilist_airing", run_date)

    out = data_dir / "processed" / "anilist_airing" / f"{run_date}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [flatten_airing(n, run_date) for n in raw]
    tmp = out.with_name(out.name + ".tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), tmp)
    tmp.replace(out)
    logger.info("AniList airing: %s episodes in the %s days from %s", len(rows), WINDOW_DAYS, run_date)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    now = datetime.now(timezone.utc)
    count = land_airing(args.data_dir, now.strftime("%Y-%m-%d"), int(now.timestamp()))
    print(f"{count} episodes airing in the next {WINDOW_DAYS} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
