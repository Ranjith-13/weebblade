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
from ingestion.storage import write_daily
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
    write_daily(episodes, SCHEMA, data, "anilist_airing", fetched_on)


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
         "title_english": "Frieren", "title_romaji": "Sousou no Frieren", "format": "TV", "poster_url": "https://kitsu/1.jpg", "score_100": 90.0, "status": "current",
         "season": "FALL", "season_year": 2026, "run_date": "2026-09-14"},
        {"source": "kitsu", "source_id": "2", "wb_id": ids[1], "source_keys": ["kitsu:2", "mal:20"],
         "title_english": "Only By MAL", "title_romaji": None, "format": "ONA", "poster_url": "https://kitsu/2.jpg", "score_100": None, "status": "current",
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
    """The schedule is fetched daily and the views are made weekly. The current
    file is read per query, so a new day is live the moment it lands."""
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


def _check(data, fetched_on, rows):
    write_daily(rows, STATUS_SCHEMA, data, "anilist_status", fetched_on)
    refresh_catalog(data, data.parent / "warehouse.duckdb")  # the first check makes the view


def _said(anilist_id, status, mal=None, ended_on=None, fetched_on="2026-09-14"):
    return {"anilist_id": anilist_id, "mal_id": mal, "status": status, "ended_on": ended_on,
            "fetched_on": fetched_on}


def test_a_title_anilist_says_has_finished_is_finished_in_the_catalogue(world):
    """The sources still call it airing; AniList's check says it finished on the
    10th. The catalogue believes AniList, and keeps what the sources said."""
    client, ids, data = world
    _check(data, "2026-09-13", [_said(1, "current", fetched_on="2026-09-13")])
    _check(data, "2026-09-14", [_said(1, "finished", ended_on="2026-09-10")])

    title = client.get(f"/anime/{ids[0]}").json()

    assert (title["status"], title["merged_status"]) == ("finished", "current")
    assert (title["anilist_status"], title["anilist_ended_on"], title["anilist_checked_on"]) == (
        "finished", "2026-09-10", "2026-09-14")


def test_lists_carry_the_corrected_status_too(world):
    """The point of correcting the view rather than one page: browse, the front
    page's counts and the digest all read lists."""
    client, ids, data = world
    _check(data, "2026-09-14", [_said(1, "finished"), _said(2, "cancelled", mal=20)])

    statuses = {t["wb_id"]: t["status"] for t in client.get("/anime?limit=10").json()["items"]}

    assert statuses == {ids[0]: "finished", ids[1]: "finished"}


def test_a_hiatus_leaves_the_series_current_but_says_so(world):
    """No shared word for a pause: the series is still running, so status stays
    current, and anilist_status tells a page not to offer a weekly slot."""
    client, ids, data = world
    _check(data, "2026-09-14", [_said(99, "hiatus", mal=20)])  # placed by MAL id

    title = client.get(f"/anime/{ids[1]}").json()

    assert (title["status"], title["anilist_status"]) == ("current", "hiatus")


def test_a_title_anilist_has_not_aired_is_upcoming(world):
    client, ids, data = world
    _check(data, "2026-09-14", [_said(1, "upcoming")])

    assert client.get(f"/anime/{ids[0]}").json()["status"] == "upcoming"


def test_a_title_never_asked_about_keeps_the_sources_status(world):
    client, ids, data = world
    _check(data, "2026-09-14", [_said(1, "finished")])

    title = client.get(f"/anime/{ids[1]}").json()

    assert (title["status"], title["merged_status"], title["anilist_status"]) == ("current", "current", None)


def test_before_any_check_the_status_is_the_sources_and_the_shape_is_the_same(world):
    client, ids, _ = world

    title = client.get(f"/anime/{ids[0]}").json()

    assert (title["status"], title["merged_status"], title["anilist_status"]) == ("current", "current", None)


# --- Titles no AniList or MAL row names, placed by the MAL id Kitsu maps them to ---------

@pytest.fixture
def mapped(tmp_path, monkeypatch):
    """Titles only Kitsu lists, each carrying the MAL id Kitsu maps it to - all
    the status check can ask AniList about them by."""
    monkeypatch.setattr(schedule_module, "now", lambda: NOW.timestamp())
    data = tmp_path / "data"
    keys = [["kitsu:3"], ["kitsu:4"], ["kitsu:5"], ["kitsu:6", "mal:61"], ["kitsu:7", "anilist:7"]]
    ids, registry, _ = assign(keys, Registry(), "2026-09-14")
    save(data, registry)
    catalogue = [
        {"source": "kitsu", "source_id": k[0].split(":")[1], "wb_id": wb_id, "source_keys": k, "mal_id": mal_id,
         "title_english": f"Kitsu {k[0]}", "title_romaji": None, "format": "TV", "poster_url": None,
         "score_100": None, "status": "current", "season": "FALL", "season_year": 2026, "run_date": "2026-09-14"}
        for k, wb_id, mal_id in zip(keys, ids, [
            30,  # Dongitsune Season 2's case
            40, 40,  # two titles Kitsu maps to one id
            60,  # MAL knows this one as 61
            70,  # and AniList this one as 7
        ])
    ]
    path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-14" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(catalogue), path)
    _write_airing(data, "2026-09-14", [_episode(300, 2, _at(16, 23), mal=30), _episode(400, 1, _at(16, 22), mal=40)])
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


def test_a_title_only_kitsu_lists_is_placed_by_the_mal_id_kitsu_maps_it_to(mapped):
    """No AniList or MAL key names it, so the check asked AniList by Kitsu's MAL
    id. The answer, and the schedule, belong to it."""
    client, ids, data = mapped
    _check(data, "2026-09-14", [_said(300, "finished", mal=30, ended_on="2024-02-28")])

    title = client.get(f"/anime/{ids[0]}").json()
    on_schedule = {e["anilist_id"]: e["wb_id"] for e in client.get("/schedule").json()["episodes"]}

    assert (title["status"], title["merged_status"], title["anilist_ended_on"]) == ("finished", "current", "2024-02-28")
    assert [e["episode"] for e in title["upcoming_episodes"]] == [2]
    assert on_schedule[300] == ids[0]


def test_a_mal_id_kitsu_maps_two_titles_to_places_neither(mapped):
    client, ids, data = mapped
    _check(data, "2026-09-14", [_said(400, "finished", mal=40)])

    statuses = [client.get(f"/anime/{wb_id}").json()["anilist_status"] for wb_id in ids[1:3]]
    on_schedule = {e["anilist_id"]: e["wb_id"] for e in client.get("/schedule").json()["episodes"]}

    assert statuses == [None, None]
    assert on_schedule[400] is None


def test_a_title_anilist_or_mal_knows_by_another_id_is_not_placed_by_kitsus(mapped):
    """MAL files the first as 61 and AniList the second as 7. An AniList record
    for MAL id 60 or 70 is some other work, whatever Kitsu says."""
    client, ids, data = mapped
    _check(data, "2026-09-14", [_said(600, "finished", mal=60), _said(700, "finished", mal=70)])

    titles = [client.get(f"/anime/{wb_id}").json() for wb_id in ids[3:5]]

    assert [(t["status"], t["anilist_status"]) for t in titles] == [("current", None), ("current", None)]
