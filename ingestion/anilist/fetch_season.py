from __future__ import annotations

import logging
from typing import Any

from .client import AniListClient
from .queries import SEASONAL_MEDIA_QUERY

logger = logging.getLogger(__name__)

PER_PAGE = 50


def season_for_month(month: int) -> str:
    """Map a calendar month to AniList's quarterly season enum (WINTER = Jan-Mar)."""
    if month in (1, 2, 3):
        return "WINTER"
    if month in (4, 5, 6):
        return "SPRING"
    if month in (7, 8, 9):
        return "SUMMER"
    return "FALL"


def fetch_season(
    season: str, season_year: int, client: AniListClient | None = None
) -> list[dict[str, Any]]:
    """Fetch every anime airing in a given AniList season, paginating until exhausted."""
    client = client or AniListClient()
    results: list[dict[str, Any]] = []
    page = 1

    while True:
        data = client.query(
            SEASONAL_MEDIA_QUERY,
            {"season": season, "seasonYear": season_year, "page": page, "perPage": PER_PAGE},
        )
        media_page = data["Page"]
        results.extend(media_page["media"])
        logger.info("Fetched page %s (%s titles so far)", page, len(results))

        if not media_page["pageInfo"]["hasNextPage"]:
            break
        page += 1

    return results


if __name__ == "__main__":
    import sys
    from datetime import datetime, timezone

    logging.basicConfig(level=logging.INFO)

    now = datetime.now(timezone.utc)
    season = sys.argv[1] if len(sys.argv) > 1 else season_for_month(now.month)
    year = int(sys.argv[2]) if len(sys.argv) > 2 else now.year

    print(f"Fetching {season} {year}...")
    titles = fetch_season(season, year)
    print(f"Fetched {len(titles)} titles")
