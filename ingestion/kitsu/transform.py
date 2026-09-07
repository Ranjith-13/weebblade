from __future__ import annotations

from typing import Any

from ..text import clean_synopsis


def flatten_media(media: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw Kitsu anime resource (as returned by fetch_season) into a flat row."""
    attrs = media.get("attributes") or {}
    titles = attrs.get("titles") or {}
    start_date = attrs.get("startDate")
    start_year = start_month = start_day = None
    if start_date:
        parts = start_date.split("-")
        if len(parts) == 3:
            start_year, start_month, start_day = (int(p) for p in parts)

    average_rating = attrs.get("averageRating")

    return {
        "source": "kitsu",
        "source_id": media.get("id"),
        "mal_id": None,
        "title_romaji": titles.get("en_jp") or attrs.get("canonicalTitle"),
        "title_english": titles.get("en"),
        "title_native": titles.get("ja_jp"),
        "synopsis": clean_synopsis(attrs.get("synopsis")),
        "format": attrs.get("subtype"),
        "status": attrs.get("status"),
        "season": media.get("_season"),
        "season_year": media.get("_season_year"),
        "episodes": attrs.get("episodeCount"),
        "duration": attrs.get("episodeLength"),
        "genres": media.get("_genre_names") or [],
        "source_material": None,
        "average_score": float(average_rating) if average_rating is not None else None,
        "popularity": attrs.get("popularityRank"),
        "favourites": attrs.get("favoritesCount"),
        "start_year": start_year,
        "start_month": start_month,
        "start_day": start_day,
        # Studio data requires a second JSON:API relationship hop (animeProductions ->
        # producer) — skipped for now to keep this source's scope bounded; revisit if
        # studio-level trend analysis needs Kitsu specifically.
        "studios": [],
    }
