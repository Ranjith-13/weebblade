"""GET /scores/daily/{wb_id}: a title's score as asked every morning.

THE DENSE HALF OF /scores/settling, and these tests guard the two things that
make it honest rather than merely more frequent.

First, the unit is still a re-ask. The daily AniList check writes a row every
morning whether or not anything moved, so a pair of readings counts only where
the vote count moved - the same rule, and for the same reason, as the weekly
series it sits beside (see the note above backend/app/routers/scores._REASKS).

Second, a "score change" at this resolution is mostly arithmetic. A score is
stored out of 100 and printed out of 10 to one decimal, so a title sitting on a
rounding boundary flips the printed number on a single vote: measured on the
live catalogue on 2026-10-17, Xian Ni went 6.8 to 6.9 on two new votes while
Toaru Anbu no ITEM went 6.9 to 7.0 on 521. Both are real readings and only one
is news, so the votes behind a move travel with it.
"""

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db
from backend.app.main import app
from ingestion.anilist.fetch_status import SCHEMA
from ingestion.storage import write_daily
from processing.duckdb_catalog import refresh_catalog
from processing.identity import Registry, assign, save


def _reading(anilist_id: int, day: str, score: int | None, votes: int) -> dict:
    return {"anilist_id": anilist_id, "mal_id": None, "status": "RELEASING",
            "score_100": score, "user_count": votes, "ended_on": None, "fetched_on": day}


def _morning(data: Path, day: str, rows: list[dict]) -> None:
    write_daily(rows, SCHEMA, data, "anilist_status", day)


@pytest.fixture
def world(tmp_path):
    """One title asked about on five consecutive mornings.

    The readings are built to separate every case the endpoint has to tell
    apart: a day the votes moved and the printed score with them, a day the
    votes moved and the score did not, a day the score moved two decimal places
    below anything the site shows, and a day nothing moved at all.
    """
    data = tmp_path / "data"
    ids, registry, _ = assign([["anilist:1", "kitsu:1"], ["kitsu:2"]], Registry(), "2026-10-16")
    save(data, registry)
    catalogue = [
        {"source": "kitsu", "source_id": "1", "wb_id": ids[0], "source_keys": ["anilist:1", "kitsu:1"],
         "title_english": "Airing Show", "format": "TV", "status": "current",
         "season": "FALL", "season_year": 2026, "score_100": 70.0, "user_count": 500,
         "run_date": "2026-10-16"},
        {"source": "kitsu", "source_id": "2", "wb_id": ids[1], "source_keys": ["kitsu:2"],
         "title_english": "Finished Show", "format": "TV", "status": "finished",
         "season": "FALL", "season_year": 2021, "score_100": 80.0, "user_count": 900,
         "run_date": "2026-10-16"},
    ]
    path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-10-16" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(catalogue), path)

    _morning(data, "2026-10-16", [_reading(1, "2026-10-16", 69, 1000)])
    _morning(data, "2026-10-17", [_reading(1, "2026-10-17", 70, 1521)])  # printed 6.9 -> 7.0
    _morning(data, "2026-10-18", [_reading(1, "2026-10-18", 70, 1600)])  # votes moved, score did not
    _morning(data, "2026-10-19", [_reading(1, "2026-10-19", 71, 1600)])  # a copy: no new votes
    _morning(data, "2026-10-20", [_reading(1, "2026-10-20", 72, 1602)])  # printed 7.0 -> 7.2

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


def test_every_morning_is_a_point_oldest_first(world):
    client, ids, _ = world

    body = client.get(f"/scores/daily/{ids[0]}").json()

    assert [p["fetched_on"] for p in body["points"]] == [
        "2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"]
    assert body["points"][0] == {"fetched_on": "2026-10-16", "score_100": 69.0, "user_count": 1000}


def test_a_reading_with_no_new_votes_is_not_counted_as_one(world):
    """The 19th's score is a point higher than the 18th's on an identical vote
    count. At a day's resolution that is indistinguishable from a row carried
    forward, and counting it would let the schedule invent a revision - the
    mistake the weekly series exists because of."""
    client, ids, _ = world

    body = client.get(f"/scores/daily/{ids[0]}").json()

    assert body["reasks"] == 3  # the 17th, 18th and 20th; never the 19th
    assert "2026-10-19" not in [m["on"] for m in body["moves"]]


def test_only_a_change_the_site_would_print_is_a_move(world):
    """69 to 70 out of 100 is 6.9 to 7.0 and shows; the 18th held 70 and moved
    only its votes, so there is nothing to report about it."""
    client, ids, _ = world

    moves = client.get(f"/scores/daily/{ids[0]}").json()["moves"]

    assert [m["on"] for m in moves] == ["2026-10-17", "2026-10-20"]
    assert moves[0] == {"on": "2026-10-17", "was": 69.0, "now": 70.0, "votes_gained": 521}


def test_a_move_carries_the_votes_behind_it(world):
    """What keeps the page from reporting arithmetic as news. The 17th's move
    rode 521 new votes and the 20th's rode two, and a reader cannot tell those
    apart from the scores alone."""
    client, ids, _ = world

    moves = client.get(f"/scores/daily/{ids[0]}").json()["moves"]

    assert [m["votes_gained"] for m in moves] == [521, 2]


def test_the_votes_gained_span_the_whole_series(world):
    client, ids, _ = world

    assert client.get(f"/scores/daily/{ids[0]}").json()["votes_gained"] == 602


def test_a_title_nobody_asks_about_daily_has_an_empty_series_not_an_error(world):
    """Only the titles the catalogue calls airing are asked about every morning -
    199 of 11,992 on 2026-10-19 - so silence on a finished show is the correct
    answer rather than a gap."""
    client, ids, _ = world

    response = client.get(f"/scores/daily/{ids[1]}")

    assert response.status_code == 200
    assert response.json() == {"wb_id": ids[1], "points": [], "reasks": 0, "moves": [],
                               "votes_gained": None}


def test_an_unknown_identity_answers_empty_rather_than_404(world):
    client, _, _ = world

    response = client.get("/scores/daily/wb-does-not-exist")

    assert response.status_code == 200
    assert response.json()["points"] == []


def test_a_warehouse_with_no_daily_readings_does_not_take_the_block_down(tmp_path):
    """The API and the site deploy separately, so a frontend build can reach a
    container serving a warehouse published before the score columns existed.
    There is no anime_score_daily view at all then, and a 503 would cost the
    title page its block on every one of them."""
    data = tmp_path / "data"
    ids, registry, _ = assign([["kitsu:1"]], Registry(), "2026-10-16")
    save(data, registry)
    path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-10-16" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([
        {"source": "kitsu", "source_id": "1", "wb_id": ids[0], "source_keys": ["kitsu:1"],
         "title_english": "X", "format": "TV", "run_date": "2026-10-16"}]), path)
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
        response = TestClient(app).get(f"/scores/daily/{ids[0]}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["points"] == []


def test_a_title_rated_on_only_one_morning_has_a_point_and_no_pairs(world):
    """A premiere week. One reading is not an observation of movement, and the
    series says so rather than drawing a flat line."""
    client, ids, data = world
    _morning(data, "2026-10-21", [_reading(1, "2026-10-21", 72, 1602),
                                  _reading(9, "2026-10-21", 60, 10)])

    body = client.get(f"/scores/daily/{ids[0]}").json()

    assert len(body["points"]) == 6
    assert body["reasks"] == 3  # the 21st brought no new votes either


# GET /scores/moving: the same instrument pointed across titles instead of down
# one, and the front door the measurement did not have. Before it, the daily
# series could be seen only by landing on the right title's page and knowing to
# look - 308 re-asks over three days with no route to any of them.


def _morning_for(data, day, readings):
    """readings: {anilist_id: (score_100, user_count)}"""
    _morning(data, day, [_reading(i, day, s, v) for i, (s, v) in readings.items()])


@pytest.fixture
def season(tmp_path):
    """Four airing titles over three mornings, one of each case the page has to
    tell apart: moved up on real weight, moved down, wandered and came back, and
    gained votes without the printed score budging."""
    data = tmp_path / "data"
    ids, registry, _ = assign([[f"anilist:{i}", f"kitsu:{i}"] for i in (1, 2, 3, 4)],
                              Registry(), "2026-10-16")
    save(data, registry)
    catalogue = [
        {"source": "kitsu", "source_id": str(i), "wb_id": ids[i - 1],
         "source_keys": [f"anilist:{i}", f"kitsu:{i}"], "title_english": name,
         # A real string, not None on every row: an all-null column is typed
         # INTEGER by parquet inference, and DuckDB 1.1.3 refuses to COALESCE
         # that with a VARCHAR where 1.5.6 allows it. A fixture artifact, but
         # only the pinned environment ever said so.
         "title_romaji": f"{name} (romaji)",
         "format": "TV", "status": "current", "season": "FALL", "season_year": 2026,
         "poster_url": f"https://kitsu/{i}.jpg",
         "score_100": 70.0, "user_count": 500, "run_date": "2026-10-16"}
        for i, name in enumerate(["Climber", "Slider", "Wanderer", "Steady"], start=1)
    ]
    path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-10-16" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(catalogue), path)

    today = date.today()
    days = [(today - timedelta(days=n)).isoformat() for n in (2, 1, 0)]
    _morning_for(data, days[0], {1: (69, 1000), 2: (72, 1000), 3: (69, 1000), 4: (70, 1000)})
    _morning_for(data, days[1], {1: (70, 1300), 2: (71, 1050), 3: (70, 1400), 4: (70, 1600)})
    _morning_for(data, days[2], {1: (71, 1900), 2: (70, 1120), 3: (69, 1900), 4: (70, 2000)})

    db = tmp_path / "warehouse.duckdb"
    refresh_catalog(data, db)

    def override():
        con = duckdb.connect(str(db), read_only=True)
        try:
            yield con
        finally:
            con.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app), ids
    app.dependency_overrides.clear()


def test_a_title_whose_printed_score_moved_is_listed(season):
    client, ids = season

    movers = {m["title"]: m for m in client.get("/scores/moving").json()["movers"]}

    assert set(movers) == {"Climber", "Slider"}
    assert (movers["Climber"]["was"], movers["Climber"]["now"]) == (69.0, 71.0)
    assert (movers["Slider"]["was"], movers["Slider"]["now"]) == (72.0, 70.0)


def test_the_votes_are_the_whole_window_not_the_pair_that_crossed(season):
    """A tenth of a point is the sum of a week's opinions, not one of them."""
    client, _ = season

    climber = next(m for m in client.get("/scores/moving").json()["movers"]
                   if m["title"] == "Climber")

    assert climber["votes_gained"] == 900  # 1000 -> 1300 -> 1900
    assert climber["reasks"] == 2


def test_a_score_that_wandered_and_came_back_is_not_a_mover(season):
    """FIRST and LAST over the window. Wanderer went 6.9 to 7.0 to 6.9, which is
    two readings and no news - and three rows saying otherwise would read as
    three shows."""
    client, _ = season
    body = client.get("/scores/moving").json()

    assert "Wanderer" not in [m["title"] for m in body["movers"]]
    assert body["steady"] == 2  # Wanderer and Steady


def test_votes_without_a_printed_move_are_counted_but_not_listed(season):
    """Most titles do not move, and saying so is what makes the ones that did
    worth reading."""
    client, _ = season
    body = client.get("/scores/moving").json()

    assert "Steady" not in [m["title"] for m in body["movers"]]
    assert body["titles_reasked"] == 4
    assert body["reasks"] == 8


def test_they_are_ranked_by_the_votes_behind_the_move(season):
    """Not by its size. A score shown out of 10 crosses a rounding boundary on a
    single vote, so the biggest-looking change on a page sorted by size is
    routinely the least meaningful one. Slider moved two tenths on 120 votes and
    Climber two on 900."""
    client, _ = season

    movers = client.get("/scores/moving").json()["movers"]

    assert [m["title"] for m in movers] == ["Climber", "Slider"]


def test_a_warehouse_with_no_daily_series_is_empty_rather_than_an_error(tmp_path):
    data = tmp_path / "data"
    ids, registry, _ = assign([["kitsu:1"]], Registry(), "2026-10-16")
    save(data, registry)
    path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-10-16" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([
        {"source": "kitsu", "source_id": "1", "wb_id": ids[0], "source_keys": ["kitsu:1"],
         "title_english": "X", "format": "TV", "run_date": "2026-10-16"}]), path)
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
        response = TestClient(app).get("/scores/moving")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["movers"] == []


# WHO IS FINDING AN AUDIENCE, which is a different question from whose score
# moved and mostly names different titles. Over 2026-10-16 to 10-19, 37 of 243
# re-asked titles moved their printed score while 78% of the week's 65,841 new
# votes landed on titles that did not - so a page built only on movers leaves
# most of the week on the floor.


def test_a_title_that_gained_an_audience_is_listed_even_if_its_score_held(season):
    """The whole point. Steady never moved its printed score and picked up more
    people than anything else here."""
    client, _ = season

    gaining = {g["title"]: g for g in client.get("/scores/moving").json()["gaining"]}

    assert "Steady" in gaining
    assert gaining["Steady"]["gained"] == 1000
    assert gaining["Steady"]["moved"] is False


def test_growth_is_measured_against_anilists_own_first_reading(season):
    """Never against the merged count on anime_media_latest, which may be
    another source's number entirely. The fixture's merged user_count is 500
    while AniList's first reading is 1000, so a share computed from the wrong
    one reads 180% where the truth is 90% - which is the shape of the real
    mistake this guards: a first draft reported +892% for a title that had
    grown 10.8%."""
    client, _ = season

    climber = next(g for g in client.get("/scores/moving").json()["gaining"]
                   if g["title"] == "Climber")

    assert (climber["started"], climber["ended"]) == (1000, 1900)
    assert climber["share"] == 90.0


def test_the_overlap_between_the_two_lists_is_marked(season):
    """A title can both move its score and gain an audience, and saying so is
    better than hiding it from one list or the other."""
    client, _ = season
    body = client.get("/scores/moving").json()

    gaining = {g["title"]: g["moved"] for g in body["gaining"]}
    assert gaining["Climber"] is True
    assert gaining["Steady"] is False
    assert "Climber" in [m["title"] for m in body["movers"]]


def test_they_are_ranked_by_how_many_people_not_by_the_rate(season):
    """Volume first, with the rate printed beside it: that is what separates a
    big show ticking over from a small one breaking out, without needing a
    second ranking to justify. Slider grew 12% and Steady 100%, but Steady
    brought eight times as many people."""
    client, _ = season

    gaining = client.get("/scores/moving").json()["gaining"]

    assert [g["title"] for g in gaining][0] == "Steady"
    assert [g["gained"] for g in gaining] == sorted(
        [g["gained"] for g in gaining], reverse=True
    )


def test_the_share_of_attention_the_movers_list_cannot_show_is_counted(season):
    """Stated rather than left to be noticed. Wanderer and Steady between them
    took 1,900 of the 2,920 new votes and neither appears among the movers."""
    client, _ = season
    body = client.get("/scores/moving").json()

    assert body["votes_total"] == 2920
    assert body["votes_on_steady"] == 1900


def test_a_title_that_lost_votes_is_not_a_gainer(season, tmp_path):
    """AniList's count can fall - a list is a thing people remove a title from.
    Negative growth is not news and is not printed as if it were."""
    client, _ = season

    assert all(g["gained"] > 0 for g in client.get("/scores/moving").json()["gaining"])
