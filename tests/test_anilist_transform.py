import itertools

import pytest

from ingestion.anilist.transform import flatten_media
from ingestion.validate import validate_rows


def test_flatten_media():
    media = {
        "id": 1,
        "idMal": 1,
        "title": {"romaji": "Kimetsu no Yaiba", "english": "Demon Slayer", "native": "鬼滅の刃"},
        "coverImage": {
            "large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/1.jpg",
            "medium": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/1.jpg",
        },
        "description": "A boy named Tanjiro<br>fights demons.",
        "format": "TV",
        "status": "FINISHED",
        "season": "SPRING",
        "seasonYear": 2019,
        "episodes": 26,
        "duration": 24,
        "genres": ["Action", "Fantasy"],
        "source": "MANGA",
        "averageScore": 84,
        "popularity": 500000,
        "favourites": 30000,
        "startDate": {"year": 2019, "month": 4, "day": 6},
        "studios": {"nodes": [{"name": "ufotable"}]},
    }

    row = flatten_media(media)

    assert row["source"] == "anilist"
    assert row["source_id"] == "1"
    assert row["title_english"] == "Demon Slayer"
    assert (row["format"], row["status"], row["source_material"]) == ("TV", "finished", "manga")
    assert row["studios"] == ["ufotable"]
    assert row["start_year"] == 2019
    assert row["synopsis"] == "A boy named Tanjiro fights demons."
    assert row["poster_url"] == "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/1.jpg"


def test_flatten_media_falls_back_to_medium_cover():
    """coverImage sizes aren't guaranteed present - don't lose the poster entirely
    just because the large variant is missing."""
    media = {
        "id": 3,
        "title": {},
        "startDate": {},
        "coverImage": {"medium": "https://s4.anilist.co/medium/3.jpg"},
    }

    assert flatten_media(media)["poster_url"] == "https://s4.anilist.co/medium/3.jpg"


def test_flatten_media_handles_missing_optional_fields():
    media = {"id": 2, "title": {}, "startDate": {}}

    row = flatten_media(media)

    assert row["source_id"] == "2"
    assert row["title_english"] is None
    # None, not []: "this source has none" rather than "this title has none".
    assert (row["studios"], row["genres"]) == (None, None)
    assert row["synopsis"] is None
    assert row["poster_url"] is None
    assert (row["format"], row["status"], row["source_material"]) == (None, None, None)


def test_the_season_the_ingest_check_rejected_now_passes_it():
    """The first live AniList response, Summer 2026 on 2026-09-13, failed with
    four problems: MOVIE, SPECIAL and FINISHED differing from the shared words only
    in case, and RELEASING and NOT_YET_RELEASED on 72% of rows. These are the
    values it held, in its proportions."""
    formats = ["TV"] * 52 + ["ONA"] * 21 + ["MOVIE"] * 14 + ["TV_SHORT"] * 13 + ["OVA"] * 12 + ["SPECIAL"] * 4
    statuses = ["RELEASING"] * 79 + ["FINISHED"] * 33 + ["NOT_YET_RELEASED"] * 4
    sources = itertools.cycle(["MANGA", "LIGHT_NOVEL", "ORIGINAL", "OTHER", "VIDEO_GAME", "VISUAL_NOVEL"])
    raw = [
        {"id": i, "title": {}, "startDate": {}, "format": f, "status": s, "source": next(sources),
         "season": "SUMMER", "averageScore": 60 + i % 30, "duration": 24}
        for i, (f, s) in enumerate(zip(formats, statuses))
    ]

    validate_rows([flatten_media(m) for m in raw], "anilist")


def test_a_short_series_is_tv_as_the_other_sources_file_it():
    """Of 11 live TV_SHORT titles the catalogue also held, the other sources
    called 10 of them TV. A format of its own would flip with the merge winner."""
    row = flatten_media({"id": 1, "title": {}, "startDate": {}, "format": "TV_SHORT"})

    assert row["format"] == "TV"


def test_cancelled_and_hiatus_are_left_for_the_other_sources_to_say():
    """No shared word for either; "finished" or "current" would be a claim AniList
    did not make."""
    for status in ("CANCELLED", "HIATUS"):
        assert flatten_media({"id": 1, "title": {}, "startDate": {}, "status": status})["status"] is None


def test_popularity_is_a_count_so_it_is_not_put_in_the_rank_column():
    """AniList's popularity is how many users list the title. The shared column
    is a rank the site shows as "Popularity rank #N": stored there, 500,000
    followers would have read as rank #500,000."""
    row = flatten_media({"id": 1, "title": {}, "startDate": {}, "popularity": 500000})

    assert row["popularity"] is None
    assert row["user_count"] == 500000


def test_genres_arrive_under_the_names_kitsu_uses():
    row = flatten_media({"id": 1, "title": {}, "startDate": {},
                         "genres": ["Sci-Fi", "Mahou Shoujo", "Slice of Life"]})

    assert row["genres"] == ["Science Fiction", "Magical Girl", "Slice of Life"]


def test_source_material_arrives_as_mals_tokens():
    def source(value):
        return flatten_media({"id": 1, "title": {}, "startDate": {}, "source": value})["source_material"]

    assert [source(v) for v in ("LIGHT_NOVEL", "VIDEO_GAME", "WEB_NOVEL", "MULTIMEDIA_PROJECT")] == [
        "light_novel", "game", "web_novel", "mixed_media"]
    # AniList's GAME is a game that is NOT a video game. MAL's "game" is the video
    # game one, so the obvious lowercasing would have changed what it means.
    assert source("GAME") is None


def test_every_source_emits_only_columns_the_merge_knows():
    """Consolidation unions sources by name, and a column one source has and
    the others do not stops it: standardize_schema adds a shared column a
    source lacks, but cannot remove one it has never heard of. AniList emitted
    mean_score and trending, and would have stopped consolidation the first
    time one of its rows reached it."""
    pytest.importorskip("pyspark", reason="normalize imports PySpark")
    from ingestion.kitsu.transform import flatten_media as kitsu_flatten
    from ingestion.mal.transform import flatten_media as mal_flatten
    from processing import normalize

    shared = set(normalize._STRING_COLUMNS + normalize._INT_COLUMNS + normalize._DOUBLE_COLUMNS
                 + normalize._ARRAY_COLUMNS) | {"mal_id", "duration", "average_score"}
    rows = {
        "anilist": flatten_media({"id": 1, "title": {}, "startDate": {}}),
        "mal": mal_flatten({"id": 1}),
        "kitsu": kitsu_flatten({"id": "1", "attributes": {}}),
    }

    assert {source: set(row) - shared for source, row in rows.items()} == {
        "anilist": set(), "mal": set(), "kitsu": set()}
