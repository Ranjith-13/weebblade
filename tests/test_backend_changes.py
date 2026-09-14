"""GET /changes, and a title's changes on GET /anime/{wb_id} - recorded from the
sources' snapshots by processing/changes.py, read through the warehouse view."""

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db
from backend.app.main import app
from processing import identity
from processing.changes import record_history
from processing.duckdb_catalog import refresh_catalog


def _row(source_id, **fields):
    row = {"source_id": str(source_id), "status": "current", "episodes": 12, "average_score": 72.0,
           "season": "SUMMER", "season_year": 2026, "start_year": 2026, "start_month": 7, "start_day": 5,
           "trailer_id": None, "streaming_urls": []}
    row.update(fields)
    return row


def _snapshot(data, source, run_date, rows):
    path = data / "processed" / f"{source}_media" / "2026-SUMMER" / f"{run_date}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _catalogue(data, ids, keys):
    rows = [{"source": k[0].split(":")[0], "source_id": k[0].split(":")[1], "wb_id": wb_id, "source_keys": k,
             "title_english": f"Title {n}", "title_romaji": None, "format": "TV", "poster_url": f"https://p/{n}.jpg",
             "score_100": 72.0, "status": "current", "season": "SUMMER", "season_year": 2026, "run_date": "2026-09-13"}
            for n, (wb_id, k) in enumerate(zip(ids, keys), start=1)]
    path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-13" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _serve(db):
    def override():
        con = duckdb.connect(str(db), read_only=True)
        try:
            yield con
        finally:
            con.close()
    app.dependency_overrides[get_db] = override


KEYS = [["kitsu:1", "mal:1"], ["kitsu:2"], ["kitsu:3"]]


@pytest.fixture
def world(tmp_path):
    """Three titles over three weekly fetches. Title 1 finishes, told by Kitsu
    and MAL alike, and MAL announces its episode count; title 2 got a thirteenth
    episode a week earlier and a better score this week; Kitsu created title 3
    this week."""
    data = tmp_path / "data"
    ids, registry, _ = identity.assign(KEYS, identity.Registry(), "2026-08-30")
    identity.save(data, registry)
    _catalogue(data, ids, KEYS)

    _snapshot(data, "kitsu", "2026-08-30", [_row(1), _row(2)])
    _snapshot(data, "kitsu", "2026-09-06", [_row(1), _row(2, episodes=13)])
    _snapshot(data, "kitsu", "2026-09-13", [_row(1, status="finished"), _row(2, episodes=13, average_score=74.0), _row(3)])
    _snapshot(data, "mal", "2026-09-06", [_row(1, episodes=None)])
    _snapshot(data, "mal", "2026-09-13", [_row(1, status="finished")])
    record_history(data)

    db = tmp_path / "warehouse.duckdb"
    refresh_catalog(data, db)
    _serve(db)
    yield TestClient(app), ids, data, db
    app.dependency_overrides.clear()


def _brief(changes):
    return [(c["field"], c["old"], c["new"], c["run_date"], c["sources"]) for c in changes]


def test_a_title_carries_its_changes_and_one_change_told_twice_is_one(world):
    client, ids, _, _ = world

    changes = client.get(f"/anime/{ids[0]}").json()["changes"]

    assert _brief(changes) == [
        ("status", "current", "finished", "2026-09-13", ["kitsu", "mal"]),
        ("episodes", None, "12", "2026-09-13", ["mal"]),
    ]


def test_a_titles_changes_run_newest_first_across_fetches(world):
    client, ids, _, _ = world

    changes = client.get(f"/anime/{ids[1]}").json()["changes"]

    assert _brief(changes) == [
        ("score", "7.2", "7.4", "2026-09-13", ["kitsu"]),
        ("episodes", "12", "13", "2026-09-06", ["kitsu"]),
    ]
    assert changes[0]["since"] == "2026-09-06"


def test_the_feed_is_the_newest_weeks_changes_with_their_titles(world):
    client, ids, _, _ = world

    body = client.get("/changes").json()

    assert (body["since"], body["until"]) == ("2026-09-06", "2026-09-13")
    assert [(c["field"], c["wb_id"], c["title"]) for c in body["changes"]] == [
        ("status", ids[0], "Title 1"), ("episodes", ids[0], "Title 1"),
        ("score", ids[1], "Title 2"), ("listed", ids[2], "Title 3"),
    ]
    assert body["changes"][0]["poster_url"] == "https://p/1.jpg"


def test_the_feed_reaches_back_as_many_days_as_asked(world):
    client, _, _, _ = world

    fields = [(c["field"], c["run_date"]) for c in client.get("/changes?days=14").json()["changes"]]

    assert ("episodes", "2026-09-06") in fields


def test_a_change_follows_its_title_when_the_title_is_merged_into_another(world):
    """Title 3 turns out to be title 1. Its history goes with it."""
    client, ids, data, db = world
    registry = identity.load(data)
    _, registry, report = identity.assign([["kitsu:1", "mal:1", "kitsu:3"], ["kitsu:2"]], registry, "2026-09-20")
    identity.save(data, registry)
    refresh_catalog(data, db)
    assert report.merged == 1

    fields = [c["field"] for c in client.get(f"/anime/{ids[0]}").json()["changes"]]

    assert fields == ["status", "episodes", "listed"]


def test_lists_carry_no_changes(world):
    client, _, _, _ = world

    assert all(t["changes"] == [] for t in client.get("/anime?limit=10").json()["items"])


def test_before_any_change_is_recorded_nothing_breaks(tmp_path):
    data = tmp_path / "data"
    ids, registry, _ = identity.assign(KEYS, identity.Registry(), "2026-08-30")
    identity.save(data, registry)
    _catalogue(data, ids, KEYS)
    db = tmp_path / "warehouse.duckdb"
    refresh_catalog(data, db)
    _serve(db)
    try:
        client = TestClient(app)
        assert client.get("/changes").json() == {"since": None, "until": None, "changes": []}
        assert client.get(f"/anime/{ids[0]}").json()["changes"] == []
    finally:
        app.dependency_overrides.clear()
