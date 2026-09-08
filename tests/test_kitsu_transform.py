from ingestion.kitsu.transform import flatten_media


def test_flatten_media():
    media = {
        "id": "44042",
        "type": "anime",
        "attributes": {
            "canonicalTitle": "Kimetsu no Yaiba",
            "titles": {"en": "Demon Slayer", "en_jp": "Kimetsu no Yaiba", "ja_jp": "鬼滅の刃"},
            "synopsis": "A boy named Tanjiro fights demons.",
            "subtype": "TV",
            "status": "finished",
            "episodeCount": 26,
            "episodeLength": 23,
            "startDate": "2019-04-06",
            "averageRating": "84.5",
            "popularityRank": 15,
            "favoritesCount": 9000,
            "posterImage": {
                "tiny": "https://media.kitsu.app/anime/44042/poster_image/tiny.jpg",
                "large": "https://media.kitsu.app/anime/44042/poster_image/large.jpg",
                "original": "https://media.kitsu.app/anime/44042/poster_image/original.jpg",
            },
        },
        # attached by fetch_season._attach_metadata, not native Kitsu fields
        "_genre_names": ["Action", "Fantasy"],
        "_season": "SPRING",
        "_season_year": 2019,
    }

    row = flatten_media(media)

    assert row["source"] == "kitsu"
    assert row["source_id"] == "44042"
    assert row["title_english"] == "Demon Slayer"
    assert row["season"] == "SPRING"
    assert row["season_year"] == 2019
    assert row["genres"] == ["Action", "Fantasy"]
    assert row["average_score"] == 84.5
    assert row["start_year"] == 2019
    assert row["start_month"] == 4
    assert row["start_day"] == 6
    assert row["studios"] == []
    assert row["synopsis"] == "A boy named Tanjiro fights demons."
    # "large", not "original" - originals are full-resolution and this only renders
    # as a grid tile or detail poster.
    assert row["poster_url"] == "https://media.kitsu.app/anime/44042/poster_image/large.jpg"


def test_flatten_media_handles_missing_optional_fields():
    media = {"id": "1", "attributes": {}}

    row = flatten_media(media)

    assert row["source_id"] == "1"
    assert row["title_english"] is None
    assert row["genres"] == []
    assert row["average_score"] is None
    assert row["start_year"] is None
    assert row["poster_url"] is None
