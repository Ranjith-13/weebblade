"""GET /schedule, and a title's upcoming episodes - both from AniList's airing schedule."""

from datetime import datetime, timedelta, timezone

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db
from backend.app.main import app
from backend.app.routers import schedule as schedule_module
from ingestion.anilist.fetch_airing import SCHEMA
from processing.duckdb_catalog import refresh_catalog
from processing.identity import Registry, assign, save

JST = timezone(timedelta(hours=9))
# Monday 14 September 2026, 21:00 in Tokyo.
NOW = datetime(2026, 9, 14, 21, 0, tzinfo=JST)


def _at(day, hour, minute=0):
    """Epoch seconds for a September 2026 time in Tokyo."""
    return int(datetime(2026, 9, day, hour, minute, tzinfo=JST).timestamp())


def _episode(anilist_id, episode, at, mal=None, title=None, fetched_on="2026-09-14"):
    return {"anilist_id": anilist_id, "mal_id": mal, "episode": episode, "airing_at": at,
            "title": title or f"AniList {anilist_id}", "format": "TV", "episodes": 12,
            "poster_url": f"https://s4.anilist.co/{anilist_id}.jpg", "fetched_on": fetched_on}


def _write_airing(data, fetched_on, episodes):
    path = data / "processed" / "anilist_airing" / f"{fetched_on}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(episodes, schema=SCHEMA), path)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two catalogue titles - one AniList knows by its own id, one only by its
    MAL id - and a long-runner the catalogue does not hold."""
    monkeypatch.setattr(schedule_module, "now", lambda: NOW.timestamp())
    data = tmp_path / "data"
    ids, registry, _ = assign([["anilist:1", "kitsu:1"], ["kitsu:2", "mal:20"]], Registry(), "2026-09-14")
    save(data, registry)
    catalogue = [
        {"source": "kitsu", "source_id": "1", "wb_id": ids[0], "source_keys": ["anilist:1", "kitsu:1"],
         "title_english": "Frieren", "title_romaji": "Sousou no Frieren", "format": "TV", "poster_url": "https://kitsu/1.jpg", "score_100": 90.0,
         "season": "FALL", "season_year": 2026, "run_date": "2026-09-14"},
        {"source": "kitsu", "source_id": "2", "wb_id": ids[1], "source_keys": ["kitsu:2", "mal:20"],
         "title_english": "Only By MAL", "title_romaji": None, "format": "ONA", "poster_url": "https://kitsu/2.jpg", "score_100": None,
         "season": "FALL", "season_year": 2026, "run_date": "2026-09-14"},
    ]
    path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-14" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(catalogue), path)

    # Yesterday's fetch had Frieren's episode 5 an hour later; today's is right.
    _write_airing(data, "2026-09-13", [_episode(1, 5, _at(14, 3), fetched_on="2026-09-13")])
    _write_airing(data, "2026-09-14", [
        _episode(1, 4, _at(13, 23)),            # yesterday in Tokyo: not on today's schedule
        _episode(1, 5, _at(14, 2)),             # this morning: aired, but still today's
        _episode(2, 3, _at(16, 23, 30), mal=20),  # placed by its MAL id alone
        _episode(21, 1150, _at(20, 9, 30), mal=21, title="ONE PIECE"),  # not in the catalogue
        _episode(1, 6, _at(21, 2)),             # next Monday: past the seven days
        _episode(1, 7, _at(28, 2)),
        _episode(1, 8, _at(30, 2)),
        _episode(1, 9, _at(30, 3)),
        _episode(1, 10, _at(30, 4)),
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
    yield TestClient(app), ids, data
    app.dependency_overrides.clear()


def test_the_schedule_runs_from_midnight_today_in_tokyo_for_the_days_asked(world):
    client, ids, _ = world

    body = client.get("/schedule?days=7").json()

    assert body["start"] == "2026-09-13T15:00:00Z"  # 00:00 on the 14th in Tokyo
    assert body["end"] == "2026-09-20T15:00:00Z"
    assert [(e["anilist_id"], e["episode"]) for e in body["episodes"]] == [(1, 5), (2, 3), (21, 1150)]


def test_only_the_newest_fetch_is_served(world):
    client, _, _ = world

    frieren = client.get("/schedule").json()["episodes"][0]

    assert frieren["airing_at"] == "2026-09-13T17:00:00Z"  # today's 02:00, not yesterday's 03:00
    assert client.get("/schedule").json()["fetched_on"] == "2026-09-14"


def test_a_new_days_fetch_is_served_without_rebuilding_the_warehouse(world):
    """The schedule is fetched daily and the views are made weekly. The glob is
    read per query, so a new file is live the moment it lands."""
    client, _, data = world
    _write_airing(data, "2026-09-15", [_episode(1, 5, _at(15, 2), fetched_on="2026-09-15")])

    body = client.get("/schedule").json()

    assert body["fetched_on"] == "2026-09-15"
    assert [e["airing_at"] for e in body["episodes"]] == ["2026-09-14T17:00:00Z"]


def test_a_title_is_placed_by_its_anilist_id_then_its_mal_id(world):
    client, ids, _ = world

    by_id = {e["anilist_id"]: e for e in client.get("/schedule").json()["episodes"]}

    assert (by_id[1]["wb_id"], by_id[1]["title"], by_id[1]["poster_url"]) == (ids[0], "Frieren", "https://kitsu/1.jpg")
    assert (by_id[2]["wb_id"], by_id[2]["title"], by_id[2]["format"]) == (ids[1], "Only By MAL", "ONA")


def test_a_show_the_catalogue_does_not_hold_is_on_the_schedule_as_anilist_has_it(world):
    client, _, _ = world

    one_piece = next(e for e in client.get("/schedule").json()["episodes"] if e["anilist_id"] == 21)

    assert one_piece["wb_id"] is None
    assert (one_piece["title"], one_piece["poster_url"]) == ("ONE PIECE", "https://s4.anilist.co/21.jpg")


def test_a_title_carries_its_next_episodes_and_none_that_have_aired(world):
    client, ids, _ = world

    upcoming = client.get(f"/anime/{ids[0]}").json()["upcoming_episodes"]

    # Episodes 4 and 5 have aired by 21:00 on the 14th; four at most, soonest first.
    assert [e["episode"] for e in upcoming] == [6, 7, 8, 9]
    assert upcoming[0] == {"episode": 6, "airing_at": "2026-09-20T17:00:00Z", "fetched_on": "2026-09-14"}


def test_a_title_placed_by_its_mal_id_carries_its_episodes_too_and_lists_carry_none(world):
    client, ids, _ = world

    assert [e["episode"] for e in client.get(f"/anime/{ids[1]}").json()["upcoming_episodes"]] == [3]
    assert all(t["upcoming_episodes"] == [] for t in client.get("/anime?limit=10").json()["items"])


def test_before_any_schedule_is_fetched_nothing_breaks(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_module, "now", lambda: NOW.timestamp())
    data = tmp_path / "data"
    path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-14" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([{"source": "kitsu", "source_id": "1", "title_english": "X",
                                          "run_date": "2026-09-14"}]), path)
    db = tmp_path / "warehouse.duckdb"
    refresh_catalog(data, db)

    def override():
        con = duckdb.connect(str(db), read_only=True)
        try:
            yield con
        finally:
            con.close()

    app.dependency_overrides[get_db] = override
    try:
        body = TestClient(app).get("/schedule").json()
    finally:
        app.dependency_overrides.clear()

    assert (body["episodes"], body["fetched_on"]) == ([], None)


# --- AniList's status check --------------------------------------------------------------

from ingestion.anilist.fetch_status import SCHEMA as STATUS_SCHEMA  # noqa: E402


def _write_status(data, fetched_on, rows):
    path = data / "processed" / "anilist_status" / f"{fetched_on}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=STATUS_SCHEMA), path)


def _check(anilist_id, status, mal=None, ended_on=None, fetched_on="2026-09-14"):
    return {"anilist_id": anilist_id, "mal_id": mal, "status": status, "ended_on": ended_on,
            "fetched_on": fetched_on}


def test_a_title_carries_anilists_newest_status_check(world):
    client, ids, data = world
    _write_status(data, "2026-09-13", [_check(1, "current", fetched_on="2026-09-13")])
    _write_status(data, "2026-09-14", [_check(1, "finished", ended_on="2026-09-10")])
    refresh_catalog(data, data.parent / "warehouse.duckdb")

    status = client.get(f"/anime/{ids[0]}").json()["anilist_status"]

    assert status == {"status": "finished", "ended_on": "2026-09-10", "checked_on": "2026-09-14"}


def test_a_status_check_is_placed_by_mal_id_too_and_absent_where_never_asked(world):
    client, ids, data = world
    _write_status(data, "2026-09-14", [_check(99, "hiatus", mal=20)])
    refresh_catalog(data, data.parent / "warehouse.duckdb")

    assert client.get(f"/anime/{ids[1]}").json()["anilist_status"]["status"] == "hiatus"
    assert client.get(f"/anime/{ids[0]}").json()["anilist_status"] is None
    assert all(t["anilist_status"] is None for t in client.get("/anime?limit=10").json()["items"])
