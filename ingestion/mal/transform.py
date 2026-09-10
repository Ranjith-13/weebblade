from __future__ import annotations

from typing import Any

from ..text import clean_synopsis

# MAL and Kitsu describe the same concepts with different vocabularies. Left
# unreconciled, the site would show "tv" and "TV" as two separate format chips
# and the "airing now" count would silently miss every MAL row, because the
# frontend tests `status === "current"`.
#
# The canonical vocabulary is Kitsu's, purely because Kitsu is the source that
# has been live throughout and every stored row already uses it. Changing that
# now would mean rewriting history for no gain.
_MEDIA_TYPES = {
    "tv": "TV",
    "tv_special": "special",
    "ova": "OVA",
    "ona": "ONA",
    "movie": "movie",
    "special": "special",
    "music": "music",
    "cm": "music",
    "pv": "music",
}

_STATUSES = {
    "currently_airing": "current",
    "finished_airing": "finished",
    "not_yet_aired": "upcoming",
}


def flatten_media(media: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw MAL API v2 anime node into a flat row."""
    alt = media.get("alternative_titles") or {}
    start_date = media.get("start_date")
    start_year = start_month = start_day = None
    if start_date:
        parts = start_date.split("-")
        if len(parts) == 3:
            start_year, start_month, start_day = (int(p) for p in parts)

    start_season = media.get("start_season") or {}
    broadcast = media.get("broadcast") or {}

    # MAL gives episode length in SECONDS. normalize.py pulls the leading number
    # out of `duration` and calls the result duration_minutes, so handing it 1440
    # would claim a 24-minute episode runs for 24 hours.
    duration_seconds = media.get("average_episode_duration")
    duration_minutes = round(duration_seconds / 60) if duration_seconds else None

    mean = media.get("mean")

    return {
        "source": "mal",
        "source_id": str(media.get("id")),
        "mal_id": media.get("id"),
        "title_romaji": media.get("title"),
        "title_english": alt.get("en") or None,
        "title_native": alt.get("ja") or None,
        "poster_url": (media.get("main_picture") or {}).get("large")
        or (media.get("main_picture") or {}).get("medium"),
        "cover_url": None,
        "synopsis": clean_synopsis(media.get("synopsis")),
        "format": _MEDIA_TYPES.get((media.get("media_type") or "").lower()),
        "status": _STATUSES.get((media.get("status") or "").lower()),
        "season": (start_season.get("season") or "").upper() or None,
        "season_year": start_season.get("year"),
        "episodes": media.get("num_episodes") or None,
        "duration": duration_minutes,
        "genres": [g["name"] for g in media.get("genres") or []],
        # The two columns that are null for 100% of rows today. Kitsu exposes
        # neither without extra relationship hops that came back empty; this is
        # the main reason MAL is worth a source slot at all.
        "source_material": media.get("source"),
        "studios": [s["name"] for s in media.get("studios") or []],
        # MAL's `mean` is a 0-10 rating; Kitsu's averageRating is 0-100, and the
        # column these both land in is literally called score_100. Stored raw, a
        # MAL score of 8.7 rendered on the site as "8.7 out of 100" - and because
        # the merge fills a missing Kitsu score from MAL, it dragged Kitsu-sourced
        # rows onto the wrong scale too: 124 of 227 scored Summer titles, sorted
        # to the bottom of a score-ranked catalogue and drawn as near-worthless by
        # a design whose whole subject is how much is known about a title.
        #
        # Same class of miss as average_episode_duration above, which is in
        # seconds. Reconciling MAL's vocabulary covered the words and skipped the
        # units.
        "average_score": mean * 10 if mean is not None else None,
        # MAL's `popularity` is a RANK, like Kitsu's popularityRank, so the two
        # sources agree on direction here: lower is more popular.
        "popularity": media.get("popularity"),
        "rating_rank": media.get("rank"),
        "user_count": media.get("num_list_users"),
        "favourites": media.get("num_favorites"),
        "age_rating": media.get("rating"),
        # MAL has no next-episode date - checked against the spec, not assumed.
        # What it does have is the weekly broadcast slot, from which the next
        # airing is derived at read time. Stored as the slot rather than a
        # computed date for the same reason schedules were always going to be:
        # the pipeline runs weekly, so anything precomputed here is stale within
        # days, and a slot stays true for a whole cour.
        "broadcast_day": broadcast.get("day_of_the_week"),
        "broadcast_time": broadcast.get("start_time"),
        "slug": None,
        "trailer_id": None,
        # None rather than [], for the same reason Kitsu's studios are None: an
        # empty list reads as a real value to the merge and would beat another
        # source's populated one.
        "streaming_services": None,
        "streaming_urls": None,
        "start_year": start_year,
        "start_month": start_month,
        "start_day": start_day,
    }
