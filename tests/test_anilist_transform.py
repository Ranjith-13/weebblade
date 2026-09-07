from ingestion.anilist.fetch_season import season_for_month
from ingestion.anilist.transform import flatten_media


def test_season_for_month():
    assert season_for_month(1) == "WINTER"
    assert season_for_month(3) == "WINTER"
    assert season_for_month(4) == "SPRING"
    assert season_for_month(8) == "SUMMER"
    assert season_for_month(12) == "FALL"


def test_flatten_media():
    media = {
        "id": 1,
        "idMal": 1,
        "title": {"romaji": "Kimetsu no Yaiba", "english": "Demon Slayer", "native": "鬼滅の刃"},
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

    assert row["id"] == 1
    assert row["title_english"] == "Demon Slayer"
    assert row["studios"] == ["ufotable"]
    assert row["start_year"] == 2019


def test_flatten_media_handles_missing_optional_fields():
    media = {"id": 2, "title": {}, "startDate": {}}

    row = flatten_media(media)

    assert row["id"] == 2
    assert row["title_english"] is None
    assert row["studios"] == []
