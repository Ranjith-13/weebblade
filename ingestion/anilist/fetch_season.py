from __future__ import annotations

import logging
from typing import Any

from ..seasons import season_for_month
from .client import AniListClient
from .queries import SEASONAL_MEDIA_QUERY

logger = logging.getLogger(__name__)

PER_PAGE = 50

__all__ = ["fetch_season", "season_for_month"]


def fetch_season(
    season: str, season_year: int, client: AniListClient | None = None
) -> list[dict[str, Any]]:
    """Fetch every anime airing in a given AniList season, paginating until exhausted.

    Deduplicates by id across pages as a defensive measure - Kitsu's pagination was
    confirmed to return duplicate pages live (see ingestion/kitsu/fetch_season.py), so
    this doesn't assume any external API's page boundaries are perfectly reliable.
    """
    client = client or AniListClient()
    results: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    page = 1

    while True:
        data = client.query(
            SEASONAL_MEDIA_QUERY,
            {"season": season, "seasonYear": season_year, "page": page, "perPage": PER_PAGE},
        )
        media_page = data["Page"]
        for media in media_page["media"]:
            if media["id"] in seen_ids:
                continue
            seen_ids.add(media["id"])
            results.append(media)
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

    print(f"Fetching {season} {year} from AniList...")
    titles = fetch_season(season, year)
    print(f"Fetched {len(titles)} titles")
