from __future__ import annotations

import logging
from typing import Any

from ..seasons import season_for_month
from .client import KITSU_API_URL, KitsuClient

logger = logging.getLogger(__name__)

PAGE_LIMIT = 20

# WHY THERE IS NO EPISODE SCHEDULE HERE
#
# Air dates and countdowns are the headline feature on LiveChart and AniChart,
# and they are not buildable from Kitsu. This was implemented and then reverted
# after measuring, so the numbers are recorded rather than the conclusion alone.
#
# Kitsu's `nextRelease` attribute is null for every title in the live season.
# The /anime/{id}/episodes endpoint does carry per-episode `airdate`, but Kitsu
# BACKFILLS those after an episode airs: future episodes exist as rows with a
# null airdate. Measured across all 83 currently-airing titles in Summer 2026:
#
#     8 of 83 had any dated episode at all  (episode progress: 10% coverage)
#     1 of 83 had a date in the future      (a countdown: 1% coverage)
#
# That single title is BLEACH, where someone entered dates by hand.
#
# The cost side, for whoever revisits this: episodes are one request per title,
# the endpoint caps page[limit] at 20 (21 returns 400), and `sort=-number` is
# silently ignored, so reaching the tail needs page[offset] = episodeCount - 20.
# Roughly 83 extra requests per weekly run to populate a feature on one title.
#
# This becomes viable if AniList returns - its nextAiringEpisode carries a real
# countdown for every airing show. AniList is currently 403 with "temporarily
# disabled due to severe stability issues", and Jikan 504s behind MAL.


def fetch_season(
    season: str, season_year: int, client: KitsuClient | None = None
) -> list[dict[str, Any]]:
    """Fetch every anime airing in a given season from Kitsu, including genre/category names.

    Deduplicates by id across pages - confirmed live that Kitsu's own pagination is not
    reliable (an offset=20 request returned byte-identical data to offset=0 for the
    same query), so trusting page boundaries alone silently doubles some rows.
    """
    client = client or KitsuClient()
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    url = f"{KITSU_API_URL}/anime"
    params = {
        "filter[season]": season.lower(),
        "filter[seasonYear]": season_year,
        "page[limit]": PAGE_LIMIT,
        "include": "categories,streamingLinks,mappings",
    }

    while url:
        payload = client.get(url, params=params)
        for item in _attach_metadata(payload, season, season_year):
            if item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            results.append(item)
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
    included = payload.get("included", [])
    categories_by_id = {
        item["id"]: item["attributes"]["title"]
        for item in included
        if item["type"] == "categories"
    }
    streaming_by_id = {
        item["id"]: (item.get("attributes") or {}).get("url")
        for item in included
        if item["type"] == "streamingLinks"
    }
    # The cross-source join key. Kitsu and MAL describe the same shows under
    # different ids, so without this every popular title would appear twice once
    # MAL is consolidated in. Rides along on the request we already make.
    mal_by_mapping_id = {
        item["id"]: (item.get("attributes") or {}).get("externalId")
        for item in included
        if item["type"] == "mappings"
        and (item.get("attributes") or {}).get("externalSite") == "myanimelist/anime"
    }

    items = []
    for item in payload["data"]:
        category_refs = (
            item.get("relationships", {}).get("categories", {}).get("data")
        ) or []
        item["_genre_names"] = [
            categories_by_id[c["id"]] for c in category_refs if c["id"] in categories_by_id
        ]
        streaming_refs = (
            item.get("relationships", {}).get("streamingLinks", {}).get("data")
        ) or []
        item["_streaming_urls"] = [
            streaming_by_id[s["id"]]
            for s in streaming_refs
            if streaming_by_id.get(s["id"])
        ]
        mapping_refs = (
            item.get("relationships", {}).get("mappings", {}).get("data")
        ) or []
        item["_mal_id"] = next(
            (
                mal_by_mapping_id[m["id"]]
                for m in mapping_refs
                if mal_by_mapping_id.get(m["id"])
            ),
            None,
        )
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
