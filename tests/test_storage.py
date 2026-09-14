"""The files a daily fetch leaves: its dated history, and the one that is served."""

import pyarrow as pa
import pyarrow.parquet as pq

from ingestion.storage import write_daily

SCHEMA = pa.schema([("n", pa.int64()), ("fetched_on", pa.string())])


def _current(data):
    return pq.read_table(data / "processed" / "current" / "x.parquet").to_pylist()


def test_each_day_is_kept_and_the_newest_is_served(tmp_path):
    write_daily([{"n": 1, "fetched_on": "2026-09-13"}], SCHEMA, tmp_path, "x", "2026-09-13")
    write_daily([{"n": 2, "fetched_on": "2026-09-14"}], SCHEMA, tmp_path, "x", "2026-09-14")

    assert sorted(p.name for p in (tmp_path / "processed" / "x").iterdir()) == ["2026-09-13.parquet", "2026-09-14.parquet"]
    assert _current(tmp_path) == [{"n": 2, "fetched_on": "2026-09-14"}]


def test_rerunning_an_older_day_does_not_put_it_back_in_service(tmp_path):
    write_daily([{"n": 2, "fetched_on": "2026-09-14"}], SCHEMA, tmp_path, "x", "2026-09-14")
    write_daily([{"n": 1, "fetched_on": "2026-09-13"}], SCHEMA, tmp_path, "x", "2026-09-13")

    assert _current(tmp_path) == [{"n": 2, "fetched_on": "2026-09-14"}]
    assert (tmp_path / "processed" / "x" / "2026-09-13.parquet").exists()


def test_a_day_that_found_nothing_still_replaces_the_day_before(tmp_path):
    """An empty answer is an answer: nothing airing is not yesterday's schedule."""
    write_daily([{"n": 1, "fetched_on": "2026-09-13"}], SCHEMA, tmp_path, "x", "2026-09-13")
    write_daily([], SCHEMA, tmp_path, "x", "2026-09-14")

    assert _current(tmp_path) == []
