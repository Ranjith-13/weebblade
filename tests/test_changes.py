"""What changed about each title between a source's snapshots. Pure Python over
parquet written to tmp_path, so these run anywhere."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from processing import identity
from processing.changes import _score, record_changes, record_history


def _row(source_id, **fields):
    row = {"source_id": str(source_id), "title_english": f"Title {source_id}", "status": "current",
           "episodes": 12, "average_score": 72.0, "season": "SUMMER", "season_year": 2026,
           "start_year": 2026, "start_month": 7, "start_day": 5, "trailer_id": None,
           "streaming_urls": [], "user_count": 1000, "popularity": 50, "rating_rank": 400,
           "poster_url": f"https://cdn/{source_id}.jpg"}
    row.update(fields)
    return row


def _snapshot(data: Path, run_date: str, rows, source="kitsu", partition="2026-SUMMER", drop=()):
    path = data / "processed" / f"{source}_media" / partition / f"{run_date}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{k: v for k, v in r.items() if k not in drop} for r in rows]
    pq.write_table(pa.Table.from_pylist(rows), path)


def _registry(data: Path, *keys):
    ids, registry, _ = identity.assign([[k] for k in keys], identity.Registry(), "2026-09-06")
    identity.save(data, registry)
    return dict(zip(keys, ids))


def _changes(data: Path, run_date: str):
    return pq.read_table(data / "processed" / "changes" / f"{run_date}.parquet").to_pylist()


def _brief(changes):
    return sorted((c["source_id"], c["field"], c["old"], c["new"]) for c in changes)


def test_a_status_change_is_recorded_with_its_source_title_and_both_dates(tmp_path):
    ids = _registry(tmp_path, "kitsu:1")
    _snapshot(tmp_path, "2026-09-06", [_row(1)])
    _snapshot(tmp_path, "2026-09-13", [_row(1, status="finished")])

    record_changes(tmp_path, "2026-09-13")

    assert _changes(tmp_path, "2026-09-13") == [{
        "wb_id": ids["kitsu:1"], "source": "kitsu", "source_id": "1", "field": "status",
        "old": "current", "new": "finished", "label": None, "run_date": "2026-09-13", "since": "2026-09-06",
        "partition": "2026-SUMMER"}]


def test_member_counts_ranks_and_poster_urls_are_not_news(tmp_path):
    _snapshot(tmp_path, "2026-09-06", [_row(1)])
    _snapshot(tmp_path, "2026-09-13", [_row(1, user_count=1500, popularity=40, rating_rank=350,
                                            poster_url="https://cdn/1.jpg?v=2")])

    record_changes(tmp_path, "2026-09-13")

    assert _changes(tmp_path, "2026-09-13") == []


def test_a_score_counts_only_when_the_page_would_print_it_differently(tmp_path):
    _snapshot(tmp_path, "2026-09-06", [_row(1, average_score=72.31), _row(2, average_score=72.3)])
    _snapshot(tmp_path, "2026-09-13", [_row(1, average_score=72.34), _row(2, average_score=73.4)])

    record_changes(tmp_path, "2026-09-13")

    assert _brief(_changes(tmp_path, "2026-09-13")) == [("2", "score", "7.2", "7.3")]


def test_a_score_reads_as_the_page_prints_it():
    """Stored out of 100, shown out of 10, one decimal - whichever source it
    came from. Jikan stored out of 10 and was scaled here; its public API was
    discontinued on 1 October 2026 and the special case went with it, so the
    thing worth pinning now is that every source reads the same way."""
    assert _score({"source": "kitsu", "average_score": 78.4}) == "7.8"
    assert _score({"source": "mal", "average_score": 78.4}) == "7.8"
    assert _score({"source": "anilist", "average_score": 78.4}) == "7.8"
    assert _score({"source": "kitsu", "average_score": None}) is None


def test_an_entry_the_source_created_is_listed_but_an_old_one_a_better_fetch_found_is_not(tmp_path):
    """Kitsu's paging fix served 112 entries for the first time; only the two
    created that week had ids above every one listed before."""
    _snapshot(tmp_path, "2026-09-06", [_row(100), _row(101)])
    _snapshot(tmp_path, "2026-09-13", [_row(100), _row(101), _row(57), _row(102)])

    record_changes(tmp_path, "2026-09-13")

    assert _brief(_changes(tmp_path, "2026-09-13")) == [("102", "listed", None, None)]


def test_a_new_seasons_first_fetch_lists_only_what_was_created_since_the_last_fetch(tmp_path):
    _snapshot(tmp_path, "2026-09-27", [_row(100), _row(101)])
    _snapshot(tmp_path, "2026-10-04", [_row(90), _row(102)], partition="2026-FALL")

    record_changes(tmp_path, "2026-10-04")

    assert [c["since"] for c in _changes(tmp_path, "2026-10-04")] == ["2026-09-27"]
    assert _brief(_changes(tmp_path, "2026-10-04")) == [("102", "listed", None, None)]


def test_a_title_moving_season_is_a_season_change(tmp_path):
    """A delay reaches the snapshots as a row leaving one season's listing and
    joining the next one's."""
    _snapshot(tmp_path, "2026-09-27", [_row(5)])
    _snapshot(tmp_path, "2026-10-04", [_row(5, season="FALL", start_month=10, start_day=11)], partition="2026-FALL")

    record_changes(tmp_path, "2026-10-04")

    assert _brief(_changes(tmp_path, "2026-10-04")) == [
        ("5", "premiere", "2026-07-05", "2026-10-11"), ("5", "season", "SUMMER 2026", "FALL 2026")]


def test_a_field_an_older_snapshot_does_not_have_is_not_compared(tmp_path):
    _snapshot(tmp_path, "2026-09-06", [_row(1)], drop=("trailer_id",))
    _snapshot(tmp_path, "2026-09-13", [_row(1, trailer_id="dQw4w9WgXcQ")])

    record_changes(tmp_path, "2026-09-13")

    assert _changes(tmp_path, "2026-09-13") == []


def test_most_of_a_listing_gaining_a_field_at_once_is_the_pipeline_not_news(tmp_path):
    """A fetch that starts asking for trailers fills them for every row in one go."""
    before = [_row(i) for i in range(1, 21)]
    _snapshot(tmp_path, "2026-09-06", before)
    _snapshot(tmp_path, "2026-09-13", [_row(i, trailer_id=f"yt{i}") for i in range(1, 21)])

    report = record_changes(tmp_path, "2026-09-13")

    assert _changes(tmp_path, "2026-09-13") == []
    assert report.filled == ["kitsu 2026-SUMMER trailer (20 of 20 since 2026-09-06)"]


def test_one_title_gaining_a_field_is_news(tmp_path):
    _snapshot(tmp_path, "2026-09-06", [_row(i) for i in range(1, 21)])
    _snapshot(tmp_path, "2026-09-13", [_row(i, trailer_id="yt1" if i == 1 else None) for i in range(1, 21)])

    record_changes(tmp_path, "2026-09-13")

    assert _brief(_changes(tmp_path, "2026-09-13")) == [("1", "trailer", None, "yt1")]


def test_most_of_a_season_finishing_in_one_week_is_still_recorded(tmp_path):
    """Only a field going from nothing to something at once is the pipeline. A
    season's shows finishing together is real."""
    _snapshot(tmp_path, "2026-09-20", [_row(i) for i in range(1, 21)])
    _snapshot(tmp_path, "2026-09-27", [_row(i, status="finished") for i in range(1, 21)])

    record_changes(tmp_path, "2026-09-27")

    assert len(_changes(tmp_path, "2026-09-27")) == 20


def test_each_streaming_link_added_is_one_change_and_a_removed_one_none(tmp_path):
    _snapshot(tmp_path, "2026-09-06", [_row(1, streaming_urls=["https://crunchyroll.com/a", "https://hidive.com/a"])])
    _snapshot(tmp_path, "2026-09-13", [_row(1, streaming_urls=["https://crunchyroll.com/a", "https://netflix.com/a",
                                                               "https://max.com/a"])])

    record_changes(tmp_path, "2026-09-13")

    changes = _changes(tmp_path, "2026-09-13")
    assert _brief(changes) == [
        ("1", "streaming", None, "https://max.com/a"), ("1", "streaming", None, "https://netflix.com/a")]
    assert sorted(c["label"] for c in changes) == ["Max", "Netflix"]


def test_a_listing_that_gains_streaming_links_all_at_once_is_the_pipeline(tmp_path):
    _snapshot(tmp_path, "2026-09-06", [_row(i) for i in range(1, 21)])
    _snapshot(tmp_path, "2026-09-13", [_row(i, streaming_urls=[f"https://crunchyroll.com/{i}"]) for i in range(1, 21)])

    report = record_changes(tmp_path, "2026-09-13")

    assert _changes(tmp_path, "2026-09-13") == []
    assert report.filled == ["kitsu 2026-SUMMER streaming (20 of 20 since 2026-09-06)"]


def test_a_value_a_source_stops_giving_is_not_a_change(tmp_path):
    _snapshot(tmp_path, "2026-09-06", [_row(1)])
    _snapshot(tmp_path, "2026-09-13", [_row(1, episodes=None, average_score=None)])

    record_changes(tmp_path, "2026-09-13")

    assert _changes(tmp_path, "2026-09-13") == []


def test_a_row_missing_from_the_last_snapshot_is_compared_with_the_one_before(tmp_path):
    """Kitsu's paging dropped rows from a week's listing; the row that returns
    is compared with the last snapshot that held it, and is not new."""
    _snapshot(tmp_path, "2026-08-30", [_row(1), _row(2)])
    _snapshot(tmp_path, "2026-09-06", [_row(1)])
    _snapshot(tmp_path, "2026-09-13", [_row(1), _row(2, status="finished")])

    record_changes(tmp_path, "2026-09-13")

    assert [(c["source_id"], c["field"], c["since"]) for c in _changes(tmp_path, "2026-09-13")] == [
        ("2", "status", "2026-08-30")]


def test_a_week_with_nothing_new_still_writes_a_readable_file_and_a_rerun_replaces_it(tmp_path):
    _snapshot(tmp_path, "2026-09-06", [_row(1)])
    _snapshot(tmp_path, "2026-09-13", [_row(1)])

    record_changes(tmp_path, "2026-09-13")
    assert _changes(tmp_path, "2026-09-13") == []

    _snapshot(tmp_path, "2026-09-13", [_row(1, status="finished")])
    record_changes(tmp_path, "2026-09-13")
    assert len(_changes(tmp_path, "2026-09-13")) == 1


def test_sources_are_compared_only_with_themselves(tmp_path):
    _snapshot(tmp_path, "2026-09-06", [_row(1, status="current")], source="kitsu")
    _snapshot(tmp_path, "2026-09-13", [_row(1, status="finished")], source="mal")

    record_changes(tmp_path, "2026-09-13")

    assert _changes(tmp_path, "2026-09-13") == []


def test_the_history_is_rebuilt_one_file_per_date(tmp_path):
    _snapshot(tmp_path, "2026-08-30", [_row(1)])
    _snapshot(tmp_path, "2026-09-06", [_row(1, episodes=13)])
    _snapshot(tmp_path, "2026-09-13", [_row(1, episodes=13, status="finished")])

    record_history(tmp_path)

    assert _brief(_changes(tmp_path, "2026-09-06")) == [("1", "episodes", "12", "13")]
    assert _brief(_changes(tmp_path, "2026-09-13")) == [("1", "status", "current", "finished")]
    assert _changes(tmp_path, "2026-08-30") == []
