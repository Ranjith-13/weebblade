from __future__ import annotations

import logging
from typing import Any

from ..seasons import season_for_month
from .client import KITSU_API_URL, KitsuClient

logger = logging.getLogger(__name__)

PAGE_LIMIT = 20


def fetch_season(
    season: str, season_year: int, client: KitsuClient | None = None
) -> list[dict[str, Any]]:
    """Fetch every anime airing in a given season from Kitsu, including genre/category names."""
    client = client or KitsuClient()
    results: list[dict[str, Any]] = []

    url = f"{KITSU_API_URL}/anime"
    params = {
        "filter[season]": season.lower(),
        "filter[seasonYear]": season_year,
        "page[limit]": PAGE_LIMIT,
        "include": "categories",
    }

    while url:
        payload = client.get(url, params=params)
        results.extend(_attach_metadata(payload, season, season_year))
        logger.info("Fetched %s titles so far", len(results))

        url = (payload.get("links") or {}).get("next")
        params = None  # the 'next' link already carries all query params

    return results


def _attach_metadata(
    payload: dict[str, Any], season: str, season_year: int
) -> list[dict[str, Any]]:
    """Kitsu doesn't echo season/seasonYear or resolved genre/category names on each
    resource (they're a separate JSON:API relationship) — stitch both back onto each
    item so transform.flatten_media can stay a pure function of a single media dict,
    matching the other sources.

    Kitsu's old "genres" relationship is present but empty for every title as of
    2026-09 — confirmed against the live API, not just docs — the taxonomy moved to
    "categories" instead (a broader tag set covering genre, setting, and theme).
    """
    categories_by_id = {
        item["id"]: item["attributes"]["title"]
        for item in payload.get("included", [])
        if item["type"] == "categories"
    }

    items = []
    for item in payload["data"]:
        category_refs = (
            item.get("relationships", {}).get("categories", {}).get("data")
        ) or []
        item["_genre_names"] = [
            categories_by_id[c["id"]] for c in category_refs if c["id"] in categories_by_id
        ]
        item["_season"] = season.upper()
        item["_season_year"] = season_year
        items.append(item)
    return items


if __name__ == "__main__":
    import sys
    from datetime import datetime, timezone

    logging.basicConfig(level=logging.INFO)

    now = datetime.now(timezone.utc)
    season = sys.argv[1] if len(sys.argv) > 1 else season_for_month(now.month)
    year = int(sys.argv[2]) if len(sys.argv) > 2 else now.year

    print(f"Fetching {season} {year} from Kitsu...")
    titles = fetch_season(season, year)
    print(f"Fetched {len(titles)} titles")
