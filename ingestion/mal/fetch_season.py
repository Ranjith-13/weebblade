from __future__ import annotations

import logging
from typing import Any

from ..seasons import season_for_month
from .client import MAL_API_URL, MalClient

logger = logging.getLogger(__name__)

PAGE_LIMIT = 100

# Requested explicitly because MAL returns only id/title/main_picture otherwise.
# Everything here maps onto a column this project already has, or fills one that
# is currently null for every row:
#   studios, source      -> 100% null today; the whole reason for adding MAL
#   broadcast            -> weekly slot, the closest thing to a schedule MAL has
#   mean, rank           -> scores for titles Kitsu does not rate
#   num_list_users       -> a dense interest magnitude, like Kitsu's userCount
FIELDS = ",".join(
    [
        "id",
        "title",
        "alternative_titles",
        "main_picture",
        "synopsis",
        "start_date",
        "media_type",
        "status",
        "num_episodes",
        "start_season",
        "broadcast",
        "source",
        "average_episode_duration",
        "rating",
        "mean",
        "rank",
        "popularity",
        "num_list_users",
        "num_favorites",
        "genres",
        "studios",
    ]
)


def fetch_season(
    season: str, season_year: int, client: MalClient | None = None
) -> list[dict[str, Any]]:
    """Fetch every anime in a season from the official MyAnimeList API v2.

    MAL wraps each entry as {"node": {...}} and paginates via an absolute
    `paging.next` URL, so the loop follows that rather than computing offsets -
    the same shape the Kitsu fetcher uses.

    Deduplicated by id for the same reason Kitsu's is: trusting page boundaries
    blindly has already silently doubled rows once in this project.
    """
    client = client or MalClient()
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    url = f"{MAL_API_URL}/anime/season/{season_year}/{season.lower()}"
    params: dict[str, Any] | None = {
        "limit": PAGE_LIMIT,
        "fields": FIELDS,
        # "anime_score" rather than the default: MAL's default sort for a season
        # is by member count, which buries newly added titles entirely.
        "sort": "anime_num_list_users",
    }

    while url:
        payload = client.get(url, params=params)
        for entry in payload.get("data", []):
            node = entry.get("node") or {}
            node_id = str(node.get("id"))
            if not node_id or node_id in seen_ids:
                continue
            seen_ids.add(node_id)
            results.append(node)
        logger.info("Fetched %s titles so far", len(results))

        url = (payload.get("paging") or {}).get("next")
        params = None  # the 'next' link already carries limit, fields and sort

    return results


if __name__ == "__main__":
    import sys
    from datetime import datetime, timezone

    logging.basicConfig(level=logging.INFO)

    now = datetime.now(timezone.utc)
    season = sys.argv[1] if len(sys.argv) > 1 else season_for_month(now.month)
    year = int(sys.argv[2]) if len(sys.argv) > 2 else now.year

    print(f"Fetching {season} {year} from MyAnimeList...")
    titles = fetch_season(season, year)
    print(f"Fetched {len(titles)} titles")
