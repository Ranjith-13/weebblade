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
# AniList came back in 2026-09, and its schedule carries a real airdate for every
# airing show: see ingestion/anilist/fetch_airing.py, which is where countdowns
# come from now.


def fetch_season(
    season: str, season_year: int, client: KitsuClient | None = None
) -> list[dict[str, Any]]:
    """Fetch every anime airing in a given season from Kitsu, including genre/category names.

    Kitsu's offset paging is broken, and not only in the way first noticed. The page at
    offset 20 comes back as a copy of the page at offset 0 - every time, in any sort
    order - so one walk through a season never serves a block of it. Deduplicating by id
    hid the copies but not the hole: Fall 2023 reports 235 titles and a walk returns 220,
    and every stored season came back a round multiple of 20.

    So the season is walked in one order and, if that falls short of the count Kitsu
    reports, walked again in reverse. The block one walk cannot reach sits at the far end
    of the other, and the union is complete: 235 of 235 for Fall 2023, 144 of 144 for the
    live Summer 2026, measured against the API.
    """
    client = client or KitsuClient()
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    count = None
    for sort in ("id", "-id"):
        count = _walk(client, season, season_year, sort, results, seen_ids)
        if count is not None and len(results) >= count:
            break

    if count is not None and len(results) < count:
        logger.warning(
            "Kitsu reports %s titles for %s %s but only %s could be fetched",
            count, season, season_year, len(results),
        )
    return results


def _walk(
    client: KitsuClient,
    season: str,
    season_year: int,
    sort: str,
    results: list[dict[str, Any]],
    seen_ids: set[str],
) -> int | None:
    """Follow a season's pages in one sort order, adding titles not yet seen.

    Returns the season's size as Kitsu reports it, if it does."""
    url = f"{KITSU_API_URL}/anime"
    params = {
        "filter[season]": season.lower(),
        "filter[seasonYear]": season_year,
        "page[limit]": PAGE_LIMIT,
        "sort": sort,
        "include": "categories,streamingLinks,mappings",
    }
    count = None
    while url:
        payload = client.get(url, params=params)
        count = (payload.get("meta") or {}).get("count", count)
        for item in _attach_metadata(payload, season, season_year):
            if item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            results.append(item)
        logger.info("Fetched %s titles so far", len(results))

        url = (payload.get("links") or {}).get("next")
        params = None  # the 'next' link already carries all query params
    return count


def _attach_metadata(
    payload: dict[str, Any], season: str, season_year: int
) -> list[dict[str, Any]]:
    """Kitsu doesn't echo season/seasonYear or resolved genre/category names on each
    resource (they're a separate JSON:API relationship) - stitch both back onto each
    item so transform.flatten_media can stay a pure function of a single media dict,
    matching the other sources.

    Kitsu's old "genres" relationship is present but empty for every title as of
    2026-09 - confirmed against the live API, not just docs - the taxonomy moved to
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
