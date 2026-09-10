"""Backfilling past seasons.

No network: each source is a stub that records what it was asked for.
"""

import argparse

import pyarrow.parquet as pq
import pytest

from ingestion.backfill import backfill, parse_season, projected_requests, seasons_between


def _stub(source, titles_per_season=3, fail_on=None):
    asked = []

    def fetch(season, year):
        asked.append((season, year))
        if fail_on == (season, year):
            raise TimeoutError("upstream timed out")
        return [{"id": f"{year}{season}{i}"} for i in range(titles_per_season)]

    def flatten(media):
        return {
            "source": source, "source_id": media["id"], "format": "TV",
            "status": "finished", "season": None, "average_score": 75.0,
        }

    return (fetch, flatten), asked


def test_seasons_run_in_broadcast_order_across_a_year_boundary():
    """Alphabetical order would put FALL before SPRING and silently skip or
    repeat seasons at the turn of a year."""
    got = seasons_between(("FALL", 2024), ("SPRING", 2025))

    assert got == [("FALL", 2024), ("WINTER", 2025), ("SPRING", 2025)]


def test_the_two_year_backfill_is_six_seasons_ending_where_the_lake_begins():
    """Fall 2024 to Winter 2026 joins onto the Spring 2026 already held, with no
    gap and no overlap - and Fall 2024 is where the missing prequels aired."""
    got = seasons_between(("FALL", 2024), ("WINTER", 2026))

    assert got[0] == ("FALL", 2024)
    assert got[-1] == ("WINTER", 2026)
    assert len(got) == 6


def test_a_backwards_range_is_refused():
    with pytest.raises(ValueError):
        seasons_between(("SPRING", 2025), ("FALL", 2024))


def test_a_malformed_season_names_the_expected_shape():
    assert parse_season("2024-fall") == ("FALL", 2024)
    with pytest.raises(argparse.ArgumentTypeError, match="YEAR-SEASON"):
        parse_season("autumn-2024")


def test_snapshots_land_under_the_season_they_describe_stamped_with_today(tmp_path):
    """A 2024 season captured on 2026-09-10 is filed under 2024-FALL and stamped
    2026-09-10. run_date means when the data is as of, everywhere in this
    project, and that is also what keeps it alive through later weekly runs."""
    mal, _ = _stub("mal")

    backfill([("FALL", 2024)], ["mal"], tmp_path, "2026-09-10", fetchers={"mal": mal})

    snapshot = tmp_path / "processed" / "mal_media" / "2024-FALL" / "2026-09-10.parquet"
    assert snapshot.exists()
    assert pq.read_table(snapshot).num_rows == 3
    assert (tmp_path / "raw" / "mal" / "2024-FALL" / "2026-09-10.json").exists()


def test_a_dry_run_fetches_and_checks_but_writes_nothing(tmp_path):
    mal, asked = _stub("mal")

    landed = backfill([("FALL", 2024)], ["mal"], tmp_path, "2026-09-10",
                      dry_run=True, fetchers={"mal": mal})

    assert asked == [("FALL", 2024)]
    assert landed[0].rows == 3
    assert not (tmp_path / "processed").exists()


def test_one_failure_does_not_abandon_the_rest(tmp_path):
    """A backfill is long and re-runnable. Throwing away every successful fetch
    because one timed out would be the wrong trade."""
    mal, _ = _stub("mal", fail_on=("WINTER", 2025))
    kitsu, _ = _stub("kitsu")

    landed = backfill(
        seasons_between(("FALL", 2024), ("SPRING", 2025)), ["mal", "kitsu"], tmp_path,
        "2026-09-10", fetchers={"mal": mal, "kitsu": kitsu},
    )

    failed = [l for l in landed if l.error]
    assert [(l.source, l.partition) for l in failed] == [("mal", "2025-WINTER")]
    assert "timed out" in failed[0].error
    assert len(landed) - len(failed) == 5


def test_rows_that_fail_the_schema_check_are_not_written(tmp_path):
    """The backfill goes through the same ingest check as the weekly run, so an
    older season with a different shape cannot slip past it into the lake."""
    fetch = lambda season, year: [{"id": str(i)} for i in range(30)]  # noqa: E731
    flatten = lambda m: {"source": "mal", "source_id": m["id"], "average_score": 8.1}  # noqa: E731

    landed = backfill([("FALL", 2024)], ["mal"], tmp_path, "2026-09-10",
                      fetchers={"mal": (fetch, flatten)})

    assert landed[0].error and "0-10 scale" in landed[0].error
    assert not (tmp_path / "processed" / "mal_media" / "2024-FALL").exists()


def test_an_unknown_source_is_refused_before_anything_is_fetched(tmp_path):
    mal, asked = _stub("mal")

    with pytest.raises(ValueError, match="unknown source"):
        backfill([("FALL", 2024)], ["anilist"], tmp_path, "2026-09-10", fetchers={"mal": mal})
    assert asked == []


def test_the_frontend_request_projection_rounds_up():
    """The ceiling this guards is 60 requests a minute; undercounting by one page
    is how it gets crossed."""
    assert projected_requests(100) == 1
    assert projected_requests(101) == 2
    assert projected_requests(2300) == 23
