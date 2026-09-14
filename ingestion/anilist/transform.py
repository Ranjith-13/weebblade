from __future__ import annotations

from typing import Any

from ..text import clean_synopsis

# AniList's vocabulary mapped onto the shared one: Kitsu's words for format and
# status, MAL's for source material, the same reconciliation MAL's transform
# does. This transform was written while AniList was down and first met live
# data on 2026-09-13, when the ingest check rejected all 116 rows of the season
# for passing "MOVIE", "FINISHED" and "RELEASING" straight through.
_FORMATS = {
    "TV": "TV",
    # A series of short episodes. Neither other source has the category: of the
    # 11 live TV_SHORT titles the catalogue also held, Kitsu or MAL filed 10 as
    # TV and one as ONA. Kept apart, the same show would change format
    # depending on which source won the merge.
    "TV_SHORT": "TV",
    "MOVIE": "movie",
    "SPECIAL": "special",
    "OVA": "OVA",
    "ONA": "ONA",
    "MUSIC": "music",
}

# CANCELLED and HIATUS are not mapped. Neither Kitsu nor MAL has a word for
# either, and the nearest ones ("finished", "current") would say something
# AniList did not. Null lets the merge take the other sources' status instead.
_STATUSES = {
    "FINISHED": "finished",
    "RELEASING": "current",
    "NOT_YET_RELEASED": "upcoming",
}

# MAL is the source of this column for every stored row, and the "adapted from"
# facet shows its tokens, so AniList's are mapped onto MAL's. Unmapped, "MANGA"
# and "manga" would have been two chips. Checked against live pairs: every
# MANGA title MAL also held was manga, web_manga or 4_koma_manga to MAL, and
# every LIGHT_NOVEL one light_novel bar one novel.
#
# These are version 3 of AniList's list, which the query asks for. The default,
# version 1, has six values and files web novels, novels and picture books all
# as OTHER - 13 of the 116 live rows.
#
# Only synonyms, as with genres. NOT mapped:
#   GAME - AniList's word for games that are NOT video games. MAL's "game" is
#          the video-game one (it is what VIDEO_GAME matched), so lowercasing
#          GAME would have filed board games as video games.
#   DOUJINSHI, ANIME, LIVE_ACTION, COMIC - MAL has no word for them.
_SOURCE_MATERIAL = {
    "ORIGINAL": "original",
    "MANGA": "manga",
    "LIGHT_NOVEL": "light_novel",
    "VISUAL_NOVEL": "visual_novel",
    "VIDEO_GAME": "game",
    "NOVEL": "novel",
    "WEB_NOVEL": "web_novel",
    "PICTURE_BOOK": "picture_book",
    "MULTIMEDIA_PROJECT": "mixed_media",
    "OTHER": "other",
}

# AniList's genres are a fixed list of 19. Checked against every stored Kitsu
# snapshot, three fall outside Kitsu's vocabulary: these two, which are
# synonyms (the same mapping MAL needed), and Hentai, which Kitsu has no word
# for and the query's adult filter keeps out anyway.
_GENRES = {
    "Sci-Fi": "Science Fiction",
    "Mahou Shoujo": "Magical Girl",
}


def _genres(media: dict[str, Any]) -> list[str] | None:
    seen: dict[str, None] = {}
    for g in media.get("genres") or []:
        seen.setdefault(_GENRES.get(g, g), None)
    return list(seen) or None


def flatten_media(media: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw AniList Media object into a row of the shared schema.

    Every source emits exactly the same columns, because consolidation unions
    them by name and refuses a column one side lacks. This used to also emit
    AniList's `mean_score` and `trending`, which nothing reads, and which would
    have stopped consolidation the first time an AniList row reached it.
    """
    title = media.get("title") or {}
    start_date = media.get("startDate") or {}
    cover_image = media.get("coverImage") or {}
    studios = [s["name"] for s in (media.get("studios") or {}).get("nodes", [])]

    return {
        "source": "anilist",
        # A string like every other source's id: identities and addresses are
        # built from "source:source_id".
        "source_id": str(media["id"]),
        "mal_id": media.get("idMal"),
        "title_romaji": title.get("romaji"),
        "title_english": title.get("english"),
        "title_native": title.get("native"),
        # AniList's "large" is ~230x345, the same role Kitsu's "large" poster plays -
        # fall back to "medium" since coverImage sizes aren't guaranteed present.
        "poster_url": cover_image.get("large") or cover_image.get("medium"),
        "cover_url": None,
        "synopsis": clean_synopsis(media.get("description")),
        "format": _FORMATS.get(media.get("format") or ""),
        "status": _STATUSES.get(media.get("status") or ""),
        "season": media.get("season"),
        "season_year": media.get("seasonYear"),
        "episodes": media.get("episodes"),
        # Minutes already, like Kitsu's episodeLength.
        "duration": media.get("duration"),
        "genres": _genres(media),
        "source_material": _SOURCE_MATERIAL.get(media.get("source") or ""),
        # 0-100 already, the scale of the column.
        "average_score": media.get("averageScore"),
        # AniList's `popularity` is a COUNT - how many users have the title on
        # their list. The shared `popularity` column is a RANK, lower being more
        # popular, and the site shows it as "Popularity rank #N" and sorts it
        # that way. Stored there, a title on 500,000 lists would have shown as
        # rank #500,000. The count is what Kitsu's userCount and MAL's
        # num_list_users are, so that is where it goes.
        "popularity": None,
        "rating_rank": None,
        "user_count": media.get("popularity"),
        "favourites": media.get("favourites"),
        "age_rating": None,
        "broadcast_day": None,
        "broadcast_time": None,
        "slug": None,
        "trailer_id": None,
        "streaming_services": None,
        "streaming_urls": None,
        "start_year": start_date.get("year"),
        "start_month": start_date.get("month"),
        "start_day": start_date.get("day"),
        "studios": studios or None,
    }
