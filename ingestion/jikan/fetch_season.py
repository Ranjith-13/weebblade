from __future__ import annotations

import logging
from typing import Any

from ..seasons import season_for_month
from .client import JikanClient

logger = logging.getLogger(__name__)


def fetch_season(
    season: str, season_year: int, client: JikanClient | None = None
) -> list[dict[str, Any]]:
    """Fetch every anime airing in a given season from Jikan (MyAnimeList wrapper)."""
    client = client or JikanClient()
    results: list[dict[str, Any]] = []
    page = 1

    while True:
        payload = client.get(f"/seasons/{season_year}/{season.lower()}", params={"page": page})
        results.extend(payload["data"])
        logger.info("Fetched page %s (%s titles so far)", page, len(results))

        if not payload.get("pagination", {}).get("has_next_page"):
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

    print(f"Fetching {season} {year} from Jikan...")
    titles = fetch_season(season, year)
    print(f"Fetched {len(titles)} titles")
