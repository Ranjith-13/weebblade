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
