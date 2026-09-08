from ingestion.jikan.transform import flatten_media


def test_flatten_media():
    media = {
        "mal_id": 38000,
        "title": "Kimetsu no Yaiba",
        "title_english": "Demon Slayer",
        "title_japanese": "鬼滅の刃",
        "images": {
            "jpg": {
                "image_url": "https://cdn.myanimelist.net/images/anime/1286/99889.jpg",
                "large_image_url": "https://cdn.myanimelist.net/images/anime/1286/99889l.jpg",
            },
            "webp": {"image_url": "https://cdn.myanimelist.net/images/anime/1286/99889.webp"},
        },
        "synopsis": "A boy named Tanjiro fights demons.",
        "type": "TV",
        "status": "Finished Airing",
        "season": "spring",
        "year": 2019,
        "episodes": 26,
        "duration": "23 min per ep",
        "genres": [{"mal_id": 1, "name": "Action"}, {"mal_id": 10, "name": "Fantasy"}],
        "source": "Manga",
        "score": 8.5,
        "popularity": 12,
        "favorites": 90000,
        "aired": {"from": "2019-04-06T00:00:00+00:00"},
        "studios": [{"mal_id": 43, "name": "ufotable"}],
    }

    row = flatten_media(media)

    assert row["source"] == "jikan"
    assert row["source_id"] == 38000
    assert row["mal_id"] == 38000
    assert row["title_english"] == "Demon Slayer"
    assert row["season"] == "SPRING"
    assert row["genres"] == ["Action", "Fantasy"]
    assert row["studios"] == ["ufotable"]
    assert row["start_year"] == 2019
    assert row["start_month"] == 4
    assert row["start_day"] == 6
    assert row["synopsis"] == "A boy named Tanjiro fights demons."
    # jpg over webp (jpg is the always-populated one), and image_url over
    # large_image_url (full-resolution is unnecessary for a grid tile).
    assert row["poster_url"] == "https://cdn.myanimelist.net/images/anime/1286/99889.jpg"


def test_flatten_media_handles_missing_optional_fields():
    media = {"mal_id": 5}

    row = flatten_media(media)

    assert row["source_id"] == 5
    assert row["season"] is None
    assert row["genres"] == []
    assert row["studios"] == []
    assert row["start_year"] is None
    assert row["poster_url"] is None
