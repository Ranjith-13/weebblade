from ingestion.seasons import season_for_month


def test_season_for_month():
    assert season_for_month(1) == "WINTER"
    assert season_for_month(3) == "WINTER"
    assert season_for_month(4) == "SPRING"
    assert season_for_month(8) == "SUMMER"
    assert season_for_month(12) == "FALL"


from datetime import datetime

from ingestion.seasons import capture_for, partition_for


def test_capture_uses_the_moment_the_run_fires_not_the_interval_start():
    """The bug this exists to prevent.

    Airflow's logical_date for a weekly schedule is the START of the data
    interval, so the run created on 2026-09-13 carries 2026-09-06. run_date is
    what anime_media_latest ranks by, so a run stamped a week in the past loses
    to anything newer already in the warehouse - it fetches, consolidates, writes,
    reports success and changes nothing visible. Passing data_interval_end is what
    makes the stamp match the day the data was actually captured.
    """
    _, _, run_date, _ = capture_for(datetime(2026, 9, 13))

    assert run_date == "2026-09-13"


def test_capture_derives_season_year_and_partition_together():
    season, year, run_date, partition = capture_for(datetime(2026, 9, 13))

    assert (season, year) == ("SUMMER", 2026)
    assert partition == "2026-SUMMER"
    assert run_date == "2026-09-13"


def test_the_season_follows_the_capture_instant_across_a_quarter_boundary():
    """A weekly interval can straddle a season change. What is airing is decided
    by when the fetch happens, so an interval ending on 4 October is a Fall run
    even though it started in September."""
    season, year, _, partition = capture_for(datetime(2026, 10, 4))

    assert season == "FALL"
    assert partition == "2026-FALL"


def test_partition_for_matches_the_directories_already_on_disk():
    """Snapshots live under 2026-SUMMER / 2026-SPRING. Changing this shape orphans
    every snapshot already written."""
    assert partition_for("SUMMER", 2026) == "2026-SUMMER"
    assert partition_for("WINTER", 2027) == "2027-WINTER"
