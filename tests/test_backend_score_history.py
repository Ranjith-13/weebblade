"""score_history on GET /anime/{wb_id}: the longitudinal half of the warehouse.

Nothing new is fetched or stored to answer this. anime_media already holds every
dated snapshot the pipeline has written - 66,098 rows over 16 run dates on
2026-10-14 - and anime_media_latest is its top slice. The series was there the
whole time and only ever read cross-sectionally.

On the detail response rather than an endpoint of its own, so a title page costs
the same number of upstream requests it always did: the API rate-limits per IP
and every visitor of the site shares its egress addresses.
"""

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db
from backend.app.main import app
from processing.duckdb_catalog import refresh_catalog
from processing.identity import Registry, assign, save


def _snapshot(data: Path, run_date: str, rows: list[dict]) -> None:
    for row in rows:
        row.setdefault("run_date", run_date)
        row.setdefault("source", "kitsu")
        row.setdefault("format", "TV")
        row.setdefault("season", "FALL")
        row.setdefault("season_year", 2026)
    path = (data / "processed" / "anime_media_consolidated" / "_catalogue" / run_date
            / "part-0.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


@pytest.fixture
def history_for(tmp_path):
    """A client over a catalogue with several dated snapshots of one title."""

    def build(scores: dict[str, float | None]) -> tuple[TestClient, str]:
        data = tmp_path / "data"
        ids, registry, _ = assign([["kitsu:1"]], Registry(), min(scores))
        save(data, registry)
        wb_id = ids[0]
        for run_date, score in scores.items():
            _snapshot(data, run_date, [
                {"source_id": "1", "title_english": "A Show", "score_100": score,
                 "wb_id": wb_id},
            ])

        db = tmp_path / "warehouse.duckdb"
        refresh_catalog(data, db)

        def override():
            con = duckdb.connect(str(db), read_only=True)
            try:
                yield con
            finally:
                con.close()

        app.dependency_overrides[get_db] = override
        return TestClient(app), wb_id

    yield build
    app.dependency_overrides.clear()


def test_a_score_that_moved_comes_back_as_its_arc(history_for):
    client, wb_id = history_for({"2026-09-13": 79.0, "2026-09-20": 81.0, "2026-09-27": 84.0})

    history = client.get(f"/anime/{wb_id}").json()["score_history"]

    assert [(p["run_date"], p["score_100"]) for p in history] == [
        ("2026-09-13", 79.0), ("2026-09-20", 81.0), ("2026-09-27", 84.0),
    ]


def test_a_score_that_never_moved_says_so(history_for):
    """93% of the catalogue. Measured 2026-10-14: of 3,600 titles with three or
    more readings, 255 moved at all. A flat line is not a history and the
    frontend needs to be able to tell without walking the points itself."""
    client, wb_id = history_for({"2026-09-13": 84.0, "2026-09-20": 84.0, "2026-09-27": 84.0})

    history = client.get(f"/anime/{wb_id}").json()["score_history"]

    assert len(history) == 3
    assert {p["score_100"] for p in history} == {84.0}


def test_a_score_that_rose_and_fell_back_keeps_its_middle(history_for):
    """The ends are equal and the arc between them is the whole story, so the
    series is returned entire rather than reduced to first and latest."""
    client, wb_id = history_for({"2026-09-13": 80.0, "2026-09-20": 86.0, "2026-09-27": 80.0})

    history = client.get(f"/anime/{wb_id}").json()["score_history"]

    assert [p["score_100"] for p in history] == [80.0, 86.0, 80.0]


def test_runs_that_recorded_no_score_are_absent_rather_than_zero(history_for):
    """Half the catalogue has no score upstream, and a run that recorded none is
    silence, not a reading of nought. Plotting it as 0 would invent a crash."""
    client, wb_id = history_for({"2026-09-13": None, "2026-09-20": 72.0, "2026-09-27": 74.0})

    history = client.get(f"/anime/{wb_id}").json()["score_history"]

    assert [p["run_date"] for p in history] == ["2026-09-20", "2026-09-27"]


def test_a_title_with_no_score_at_all_is_an_empty_series_not_an_error(history_for):
    """Half the catalogue has no score upstream. An empty list, never a 404 and
    never a zero."""
    client, wb_id = history_for({"2026-09-13": None, "2026-09-20": None})

    body = client.get(f"/anime/{wb_id}").json()

    assert body["score_history"] == []
    assert body["score_100"] is None


def test_list_rows_do_not_carry_it(history_for):
    """Same rule as `changes`: the series is for one title being looked at, not
    for 100 rows of a season. A season page would otherwise pay for 100 arcs
    nobody asked for."""
    client, _ = history_for({"2026-09-13": 80.0, "2026-09-20": 84.0})

    [row] = client.get("/anime?limit=1").json()["items"]

    assert row["score_history"] == []
