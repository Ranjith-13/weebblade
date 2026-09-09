from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ..text import clean_synopsis

# Streaming host -> display name. Kitsu gives a bare URL and no provider label, so
# the mapping lives here rather than in the UI: the name is data about the row, and
# deriving it once at ingest keeps every consumer (API, frontend, any future export)
# agreeing on what to call a service.
_STREAMING_SERVICES = {
    "crunchyroll.com": "Crunchyroll",
    "netflix.com": "Netflix",
    "hulu.com": "Hulu",
    "primevideo.com": "Prime Video",
    "amazon.com": "Prime Video",
    "disneyplus.com": "Disney+",
    "hidive.com": "HIDIVE",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "bilibili.tv": "Bilibili",
    "iq.com": "iQIYI",
    "tubitv.com": "Tubi",
    "retrocrush.tv": "RetroCrush",
    "midnightpulp.com": "Midnight Pulp",
    "vrv.co": "VRV",
    "funimation.com": "Funimation",
}


def _is_usable_link(url: object) -> bool:
    """Reject anything that is not an absolute http(s) URL.

    Kitsu's streaming records are user-maintained and contain junk: the live season
    carries a link whose entire url field is the string "a". Rendering that as a
    clickable "Unknown" is worse than not showing it, so it is dropped at ingest
    rather than pushed to every consumer to defend against.
    """
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def _service_name(url: str) -> str:
    """Map a streaming URL to a provider name, falling back to the bare host.

    The fallback matters: Kitsu carries long-tail regional services this map will
    never cover, and showing "anime-onegai.com" is more useful than dropping the
    link or labelling it "Other".
    """
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for domain, name in _STREAMING_SERVICES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or "Unknown"


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

    streaming_urls = [u for u in (media.get("_streaming_urls") or []) if _is_usable_link(u)]
    streaming_services = [_service_name(u) for u in streaming_urls]

    return {
        "source": "kitsu",
        "source_id": media.get("id"),
        # Carried so the consolidation step can recognise that a Kitsu row and a
        # MAL row describe the same show. Kitsu supplies it as a string.
        "mal_id": int(media["_mal_id"]) if str(media.get("_mal_id") or "").isdigit() else None,
        "title_romaji": titles.get("en_jp") or attrs.get("canonicalTitle"),
        "title_english": titles.get("en"),
        "title_native": titles.get("ja_jp"),
        # "large" rather than "original": originals are full-resolution scans (often
        # >1MB) and this only ever renders as a grid tile or detail-page poster.
        "poster_url": (attrs.get("posterImage") or {}).get("large"),
        # Measured across the FULL live season (140 titles), not a sample: 25 have
        # cover art (17%). An earlier 40-title sample suggested ~50%, which was
        # sampling bias - Kitsu's default listing order puts the popular, better
        # documented titles first. Carried anyway because it rides along free on a
        # request we already make, but consumers must treat it as a rare
        # enhancement and never as a layout assumption.
        "cover_url": (attrs.get("coverImage") or {}).get("large"),
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
        # Both RANKS (lower is better), not counts. rating_rank turns out to be no
        # denser than the score it derives from - both 29% of the season - so it is
        # not a way around the score sparsity, just a better-shaped expression of it.
        # Keeping the "rank" in the new column's name so nothing downstream repeats
        # the mistake the frontend made with `popularity`, where a rank was sorted
        # descending and returned the least popular title first.
        "popularity": attrs.get("popularityRank"),
        "rating_rank": attrs.get("ratingRank"),
        # userCount is a magnitude, not a rank, and is populated for 100% of the
        # season - unlike favourites, which tops out around 25 and carries no signal,
        # and unlike score, which only 29% of titles have. This is the densest
        # interest signal Kitsu gives us.
        "user_count": attrs.get("userCount"),
        "favourites": attrs.get("favoritesCount"),
        "age_rating": attrs.get("ageRating"),
        "slug": attrs.get("slug"),
        "trailer_id": attrs.get("youtubeVideoId"),
        # Parallel arrays: streaming_services[i] labels streaming_urls[i]. See the
        # note in processing/normalize.py for why this is not an array<struct>.
        "streaming_urls": streaming_urls,
        "streaming_services": streaming_services,
        "start_year": start_year,
        "start_month": start_month,
        "start_day": start_day,
        # Studio data requires a second JSON:API relationship hop (animeProductions ->
        # producer) — skipped for now to keep this source's scope bounded; revisit if
        # studio-level trend analysis needs Kitsu specifically.
        "studios": [],
    }
