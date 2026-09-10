"""MAL's vocabulary differs from Kitsu's for the same concepts. Left
unreconciled, the site would show "tv" and "TV" as two format chips and the
"airing now" count would miss every MAL row, because the frontend tests
`status === "current"`. These tests pin the reconciliation."""

from ingestion.mal.transform import flatten_media


def _node(**overrides):
    node = {
        "id": 59193,
        "title": "Mushoku Tensei III",
        "alternative_titles": {"en": "Jobless Reincarnation III", "ja": "無職転生III"},
        "main_picture": {"large": "https://cdn.myanimelist.net/images/anime/1.jpg"},
        "media_type": "tv",
        "status": "currently_airing",
        "start_season": {"year": 2026, "season": "summer"},
        "num_episodes": 14,
        "average_episode_duration": 1440,
        "genres": [{"name": "Fantasy"}],
        "studios": [{"name": "Studio Bind"}],
        "source": "light_novel",
        "mean": 8.45,
        "rank": 47,
        "popularity": 120,
        "num_list_users": 3268,
        "broadcast": {"day_of_the_week": "saturday", "start_time": "23:30"},
        "start_date": "2026-07-05",
    }
    node.update(overrides)
    return node


def test_media_type_is_reconciled_to_the_kitsu_vocabulary():
    """Kitsu is canonical because every stored row already uses it."""
    assert flatten_media(_node(media_type="tv"))["format"] == "TV"
    assert flatten_media(_node(media_type="ova"))["format"] == "OVA"
    assert flatten_media(_node(media_type="ona"))["format"] == "ONA"
    assert flatten_media(_node(media_type="movie"))["format"] == "movie"
    assert flatten_media(_node(media_type="music"))["format"] == "music"


def test_status_is_reconciled_so_airing_counts_include_mal_rows():
    assert flatten_media(_node(status="currently_airing"))["status"] == "current"
    assert flatten_media(_node(status="finished_airing"))["status"] == "finished"
    assert flatten_media(_node(status="not_yet_aired"))["status"] == "upcoming"


def test_episode_duration_is_converted_from_seconds_to_minutes():
    """MAL gives seconds. normalize.py pulls the leading number out of `duration`
    and calls it duration_minutes, so passing 1440 through would claim a
    24-minute episode runs for 24 hours."""
    assert flatten_media(_node(average_episode_duration=1440))["duration"] == 24
    assert flatten_media(_node(average_episode_duration=None))["duration"] is None


def test_season_is_uppercased_to_match_the_partition_vocabulary():
    row = flatten_media(_node())
    assert row["season"] == "SUMMER"
    assert row["season_year"] == 2026


def test_the_two_columns_that_are_null_for_every_stored_row_are_populated():
    """studios and source_material are 100% null today. They are the reason this
    source exists at all."""
    row = flatten_media(_node())
    assert row["studios"] == ["Studio Bind"]
    assert row["source_material"] == "light_novel"


def test_broadcast_slot_is_stored_as_a_slot_not_a_computed_date():
    """MAL has no next-episode date. The weekly slot holds for a whole cour,
    where a precomputed date would be stale within days of a weekly run."""
    row = flatten_media(_node())
    assert row["broadcast_day"] == "saturday"
    assert row["broadcast_time"] == "23:30"


def test_a_sparse_node_still_flattens():
    row = flatten_media({"id": 1, "title": "X"})
    assert row["source_id"] == "1"
    assert row["format"] is None
    assert row["studios"] == []
    assert row["broadcast_day"] is None


def test_the_score_is_converted_to_the_hundred_point_scale():
    """MAL rates 0-10, Kitsu rates 0-100, and both land in score_100.

    Stored raw, a MAL score of 8.72 rendered as "8.72 out of 100". The merge fills
    a missing Kitsu score from MAL, so it pulled Kitsu-sourced rows onto the wrong
    scale as well - 124 of 227 scored Summer titles, buried at the bottom of a
    score-sorted catalogue.
    """
    assert flatten_media({"id": 1, "mean": 8.72})["average_score"] == 87.2
    assert flatten_media({"id": 1, "mean": 10})["average_score"] == 100


def test_an_unrated_title_has_no_score_rather_than_a_zero():
    """MAL omits `mean` for titles nobody has rated. Multiplying a missing value
    into 0 would place them below every rated title instead of outside the
    ranking, and the certainty treatment would draw them as known-and-terrible
    rather than unknown."""
    assert flatten_media({"id": 1})["average_score"] is None
    assert flatten_media({"id": 1, "mean": None})["average_score"] is None


def _with_genres(*names):
    return {"id": 1, "genres": [{"id": i, "name": n} for i, n in enumerate(names)]}


def test_genres_that_mean_the_same_thing_use_kitsus_name():
    """"Sci-Fi" and "Science Fiction" were two chips on the site, and clicking
    either hid the other source's shows - 210 MAL titles invisible to anyone
    filtering on Science Fiction."""
    genres = flatten_media(_with_genres("Sci-Fi", "Anthropomorphic", "Mahou Shoujo"))["genres"]

    assert genres == ["Science Fiction", "Anthropomorphism", "Magical Girl"]


def test_two_names_landing_on_one_genre_are_counted_once():
    """MAL splits idols by gender; Kitsu cannot. A title tagged with both is one
    Idol title, and a duplicate entry would double-count it in the facet."""
    assert flatten_media(_with_genres("Idols (Female)", "Idols (Male)", "Music"))["genres"] == [
        "Idol",
        "Music",
    ]


def test_a_narrower_genre_is_left_alone_rather_than_broadened():
    """The map is synonyms only. Folding Iyashikei into Slice of Life would make a
    Slice of Life filter quietly mean something wider than it says."""
    genres = flatten_media(_with_genres("Iyashikei", "Urban Fantasy", "Gourmet"))["genres"]

    assert genres == ["Iyashikei", "Urban Fantasy", "Gourmet"]


def test_order_is_kept_so_the_leading_genre_stays_leading():
    assert flatten_media(_with_genres("Action", "Sci-Fi", "Drama"))["genres"] == [
        "Action",
        "Science Fiction",
        "Drama",
    ]
