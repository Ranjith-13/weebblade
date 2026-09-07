from __future__ import annotations

from typing import Any


def flatten_media(media: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw AniList Media object into a flat row suitable for a table/DataFrame."""
    title = media.get("title") or {}
    start_date = media.get("startDate") or {}
    studios = [s["name"] for s in (media.get("studios") or {}).get("nodes", [])]

    return {
        "source": "anilist",
        "source_id": media["id"],
        "mal_id": media.get("idMal"),
        "title_romaji": title.get("romaji"),
        "title_english": title.get("english"),
        "title_native": title.get("native"),
        "format": media.get("format"),
        "status": media.get("status"),
        "season": media.get("season"),
        "season_year": media.get("seasonYear"),
        "episodes": media.get("episodes"),
        "duration": media.get("duration"),
        "genres": media.get("genres") or [],
        "source_material": media.get("source"),
        "average_score": media.get("averageScore"),
        "mean_score": media.get("meanScore"),
        "popularity": media.get("popularity"),
        "favourites": media.get("favourites"),
        "trending": media.get("trending"),
        "start_year": start_date.get("year"),
        "start_month": start_date.get("month"),
        "start_day": start_date.get("day"),
        "studios": studios,
    }
