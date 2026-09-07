from ingestion.anilist.transform import flatten_media


def test_flatten_media():
    media = {
        "id": 1,
        "idMal": 1,
        "title": {"romaji": "Kimetsu no Yaiba", "english": "Demon Slayer", "native": "鬼滅の刃"},
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
        "meanScore": 84,
        "popularity": 500000,
        "favourites": 30000,
        "trending": 100,
        "startDate": {"year": 2019, "month": 4, "day": 6},
        "studios": {"nodes": [{"name": "ufotable"}]},
    }

    row = flatten_media(media)

    assert row["source"] == "anilist"
    assert row["source_id"] == 1
    assert row["title_english"] == "Demon Slayer"
    assert row["source_material"] == "MANGA"
    assert row["studios"] == ["ufotable"]
    assert row["start_year"] == 2019
    assert row["synopsis"] == "A boy named Tanjiro fights demons."


def test_flatten_media_handles_missing_optional_fields():
    media = {"id": 2, "title": {}, "startDate": {}}

    row = flatten_media(media)

    assert row["source_id"] == 2
    assert row["title_english"] is None
    assert row["studios"] == []
    assert row["synopsis"] is None
