from __future__ import annotations

from typing import Any


def flatten_media(media: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw Jikan anime object into a flat row suitable for a table/DataFrame."""
    aired_from = (media.get("aired") or {}).get("from")
    start_year = start_month = start_day = None
    if aired_from:
        date_part = aired_from.split("T")[0]
        parts = date_part.split("-")
        if len(parts) == 3:
            start_year, start_month, start_day = (int(p) for p in parts)

    return {
        "source": "jikan",
        "source_id": media.get("mal_id"),
        "mal_id": media.get("mal_id"),
        "title_romaji": media.get("title"),
        "title_english": media.get("title_english"),
        "title_native": media.get("title_japanese"),
        "format": media.get("type"),
        "status": media.get("status"),
        "season": (media.get("season") or "").upper() or None,
        "season_year": media.get("year"),
        "episodes": media.get("episodes"),
        "duration": media.get("duration"),
        "genres": [g["name"] for g in media.get("genres") or []],
        "source_material": media.get("source"),
        "average_score": media.get("score"),
        "popularity": media.get("popularity"),
        "favourites": media.get("favorites"),
        "start_year": start_year,
        "start_month": start_month,
        "start_day": start_day,
        "studios": [s["name"] for s in media.get("studios") or []],
    }
