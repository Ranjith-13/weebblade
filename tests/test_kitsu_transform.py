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


def test_service_name_maps_known_hosts_and_falls_back_to_the_bare_host():
    from ingestion.kitsu.transform import _service_name

    assert _service_name("https://www.crunchyroll.com/series/GR9P57W96/x") == "Crunchyroll"
    assert _service_name("https://www.netflix.com/title/81698957") == "Netflix"
    # Subdomains must resolve to the same provider, not fall through to the host.
    assert _service_name("https://beta.crunchyroll.com/series/abc") == "Crunchyroll"
    # Long-tail regional services have no entry; showing the host beats dropping
    # the link or labelling everything "Other".
    assert _service_name("https://www.anime-onegai.com/anime/123") == "anime-onegai.com"
    assert _service_name("not a url") == "Unknown"


def test_flatten_media_carries_streaming_links_as_parallel_arrays():
    from ingestion.kitsu.transform import flatten_media

    row = flatten_media(
        {
            "id": "1",
            "attributes": {"canonicalTitle": "X", "titles": {}},
            "_streaming_urls": [
                "https://www.crunchyroll.com/series/a",
                "https://www.netflix.com/title/1",
            ],
        }
    )

    # Parallel arrays: index i in one lines up with index i in the other.
    assert row["streaming_urls"] == [
        "https://www.crunchyroll.com/series/a",
        "https://www.netflix.com/title/1",
    ]
    assert row["streaming_services"] == ["Crunchyroll", "Netflix"]
    assert len(row["streaming_services"]) == len(row["streaming_urls"])


def test_flatten_media_keeps_the_fields_the_transform_used_to_discard():
    from ingestion.kitsu.transform import flatten_media

    row = flatten_media(
        {
            "id": "49444",
            "attributes": {
                "canonicalTitle": "X",
                "titles": {},
                "youtubeVideoId": "DLRjhptssns",
                "slug": "bleach-x",
                "ratingRank": 28,
                "userCount": 1262,
                "ageRating": "R",
                "coverImage": {"large": "https://media.kitsu.app/cover.jpg"},
            },
        }
    )

    assert row["trailer_id"] == "DLRjhptssns"
    assert row["slug"] == "bleach-x"
    assert row["rating_rank"] == 28
    assert row["user_count"] == 1262
    assert row["age_rating"] == "R"
    assert row["cover_url"] == "https://media.kitsu.app/cover.jpg"


def test_flatten_media_tolerates_every_new_field_being_absent():
    """Most of these are sparse: cover art is on 17% of the season, trailers 57%.
    A row missing all of them must still flatten rather than raise."""
    from ingestion.kitsu.transform import flatten_media

    row = flatten_media({"id": "1", "attributes": {"canonicalTitle": "X", "titles": {}}})

    assert row["trailer_id"] is None
    assert row["cover_url"] is None
    assert row["rating_rank"] is None
    assert row["streaming_urls"] == []
    assert row["streaming_services"] == []


def test_youtube_short_domain_maps_to_youtube():
    from ingestion.kitsu.transform import _service_name

    # Kitsu uses both forms; they are the same service and must not appear as two.
    assert _service_name("https://youtu.be/P31CxorjHjI") == "YouTube"
    assert _service_name("https://www.youtube.com/watch?v=P31CxorjHjI") == "YouTube"


def test_unusable_streaming_links_are_dropped():
    """Kitsu's streaming records are user-maintained and contain junk. The live
    season carries one whose entire url field is the string "a"."""
    from ingestion.kitsu.transform import flatten_media

    row = flatten_media(
        {
            "id": "1",
            "attributes": {"canonicalTitle": "X", "titles": {}},
            "_streaming_urls": ["a", "", None, "ftp://x.test/a", "https://www.hidive.com/season/36240"],
        }
    )

    assert row["streaming_urls"] == ["https://www.hidive.com/season/36240"]
    assert row["streaming_services"] == ["HIDIVE"]
