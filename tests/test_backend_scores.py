"""GET /scores/settling: what a score does over its life.

THE ONE THING THESE TESTS EXIST TO PROTECT is the difference between a snapshot
and an observation. anime_media holds a row for every title in every run, but
the weekly run only refetches the season it covers; every other row is written
again unchanged. Measured on 2026-10-14, the 68 Fall 2021 TV titles carry a row
on all ten dated snapshots and their user_count sums to exactly 592,705 on every
one of them. Counting snapshots would therefore report the pipeline's own
schedule as a fact about anime: "no old score ever moves", said of numbers
nobody asked about.

So a pair of readings counts only where user_count moved, which no carry-forward
can fake - and the detector is deliberately not the score itself, because a
detector that looks at the outcome drops every observation where the answer was
"unchanged" and reports a rate near 100% by construction.
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

# A season already over before the window, one on air during it, and one not yet
# started - the three phases the endpoint sorts seasons into. The run dates below
# sit in September 2026, so Summer (July to September) is the airing one.
OVER, AIRING, UPCOMING = ("SPRING", 2025), ("SUMMER", 2026), ("WINTER", 2027)


def _snapshot(data: Path, run_date: str, rows: list[dict]) -> None:
    for row in rows:
        row.setdefault("run_date", run_date)
        row.setdefault("source", "kitsu")
        row.setdefault("format", "TV")
        row.setdefault("season", AIRING[0])
        row.setdefault("season_year", AIRING[1])
        # Present on every row the endpoint looks at: it is the proof that a row
        # was fetched rather than copied.
        row.setdefault("user_count", 1000)
    path = (data / "processed" / "anime_media_consolidated" / "_catalogue" / run_date
            / "part-0.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


@pytest.fixture
def settling_for(tmp_path):
    """A client over a catalogue of dated snapshots, keyed by run date."""

    def build(snapshots: dict[str, list[dict]], groups: list[list[str]] | None = None):
        data = tmp_path / "data"
        groups = groups or [["kitsu:1"]]
        ids, registry, _ = assign(groups, Registry(), min(snapshots))
        save(data, registry)
        by_key = {key: wb_id for keys, wb_id in zip(groups, ids) for key in keys}
        for run_date, rows in snapshots.items():
            for row in rows:
                row.setdefault("source", "kitsu")
                row["wb_id"] = by_key[f"{row['source']}:{row['source_id']}"]
            _snapshot(data, run_date, rows)

        db = tmp_path / "warehouse.duckdb"
        refresh_catalog(data, db)

        def override():
            con = duckdb.connect(str(db), read_only=True)
            try:
                yield con
            finally:
                con.close()

        app.dependency_overrides[get_db] = override
        return TestClient(app)

    yield build
    app.dependency_overrides.clear()


def _only(body: dict) -> dict:
    [season] = body["seasons"]
    return season


def test_a_row_carried_forward_unchanged_is_not_an_observation(settling_for):
    """The whole point. Three snapshots of a title nobody asked about again look
    exactly like three snapshots of a title whose score held steady, and only one
    of those is a fact about the score."""
    client = settling_for({
        "2026-09-13": [{"source_id": "1", "score_100": 80.0, "user_count": 1000}],
        "2026-09-20": [{"source_id": "1", "score_100": 80.0, "user_count": 1000}],
        "2026-09-27": [{"source_id": "1", "score_100": 80.0, "user_count": 1000}],
    })

    body = client.get("/scores/settling").json()

    assert body["reasks"] == 0
    assert body["seasons"] == []
    # And the window is still reported: the snapshots exist, they just cannot be
    # compared.
    assert body["snapshots"] == 3


def test_a_refetch_that_returned_the_same_score_is_counted(settling_for):
    """The observation the tempting detector throws away. The vote count moved,
    so the source was asked and answered; the answer happened to be the same
    number. Drop these and every rate on the page is near 100%."""
    client = settling_for({
        "2026-09-13": [{"source_id": "1", "score_100": 80.0, "user_count": 1000}],
        "2026-09-20": [{"source_id": "1", "score_100": 80.0, "user_count": 1100}],
    })

    season = _only(client.get("/scores/settling").json())

    assert (season["reasks"], season["revised"], season["visible"]) == (1, 0, 0)


def test_a_revision_too_small_to_print_is_counted_but_not_visible(settling_for):
    """Scores are stored out of 100 and printed out of 10 to one decimal, so
    83.41 to 83.36 is a real revision that nobody can see. Reporting it as
    movement would claim precision the site does not use anywhere else - and the
    gap between the two columns is the finding, not a rounding detail."""
    client = settling_for({
        "2026-09-13": [{"source_id": "1", "score_100": 83.41, "user_count": 1000}],
        "2026-09-20": [{"source_id": "1", "score_100": 83.36, "user_count": 1100}],
    })

    season = _only(client.get("/scores/settling").json())

    assert (season["reasks"], season["revised"], season["visible"]) == (1, 1, 0)
    assert season["median_change"] == 0.05


def test_a_revision_big_enough_to_print_is_visible(settling_for):
    client = settling_for({
        "2026-09-13": [{"source_id": "1", "score_100": 80.0, "user_count": 1000}],
        "2026-09-20": [{"source_id": "1", "score_100": 81.0, "user_count": 1100}],
    })

    season = _only(client.get("/scores/settling").json())

    assert (season["revised"], season["visible"], season["up"], season["down"]) == (1, 1, 1, 0)
    assert season["largest_change"] == 1.0


def test_a_source_arriving_late_is_not_the_other_one_being_revised(settling_for):
    """Each source's own reading is followed on its own. Three sources rate the
    same show differently and the merge picks a winner every run, so a title
    compared with itself reports a change of winner - here Kitsu's 80 giving way
    to MyAnimeList's 90 - as a revision nobody made."""
    client = settling_for(
        {
            "2026-09-13": [{"source": "kitsu", "source_id": "1", "score_100": 80.0,
                            "user_count": 1000}],
            "2026-09-20": [{"source": "kitsu", "source_id": "1", "score_100": 80.0,
                            "user_count": 1100},
                           {"source": "mal", "source_id": "7", "score_100": 90.0,
                            "user_count": 5000}],
        },
        groups=[["kitsu:1", "mal:7"]],
    )

    body = client.get("/scores/settling").json()
    season = _only(body)

    # One comparison: Kitsu's, which was flat. MAL's first reading has nothing
    # before it to be compared with.
    assert (season["reasks"], season["revised"]) == (1, 0)
    assert [s["source"] for s in body["sources"]] == ["kitsu"]


def test_seasons_are_sorted_into_the_phase_they_were_in(settling_for):
    """A score is alive while its show is on air, so the table's own axis has to
    be where each season sat while the pipeline was watching. Not a boolean: the
    warehouse always holds a season that has not started, and that is not the
    same state as one that has settled."""
    rows = lambda score, votes: [  # noqa: E731
        {"source_id": key, "score_100": score, "user_count": votes,
         "season": season, "season_year": year}
        for key, (season, year) in {"1": OVER, "2": AIRING, "3": UPCOMING}.items()
    ]
    client = settling_for(
        {"2026-09-13": rows(80.0, 1000), "2026-09-20": rows(81.0, 1100)},
        groups=[["kitsu:1"], ["kitsu:2"], ["kitsu:3"]],
    )

    body = client.get("/scores/settling").json()

    assert {(s["season"], s["season_year"]): s["phase"] for s in body["seasons"]} == {
        OVER: "over", AIRING: "airing", UPCOMING: "upcoming",
    }
    # Bands lead with what is on now and end with what nobody has seen yet.
    assert [b["phase"] for b in body["bands"]] == ["airing", "over", "upcoming"]
    assert all(b["seasons"] == 1 and b["titles"] == 1 for b in body["bands"])


def test_seasons_never_re_asked_are_absent_rather_than_reported_as_settled(settling_for):
    """Ten of the twenty-two seasons on file were never asked about again inside
    the window (2026-10-14). A row of zeroes for each would be the strongest
    claim on the page and the least supported one, so the count of seasons the
    catalogue holds is returned instead and the page says what it cannot speak
    for."""
    client = settling_for(
        {
            "2026-09-13": [{"source_id": "1", "score_100": 80.0, "user_count": 1000},
                           {"source_id": "2", "score_100": 70.0, "user_count": 2000,
                            "season": OVER[0], "season_year": OVER[1]}],
            "2026-09-20": [{"source_id": "1", "score_100": 81.0, "user_count": 1100},
                           {"source_id": "2", "score_100": 70.0, "user_count": 2000,
                            "season": OVER[0], "season_year": OVER[1]}],
        },
        groups=[["kitsu:1"], ["kitsu:2"]],
    )

    body = client.get("/scores/settling").json()

    assert body["seasons_held"] == 2
    assert [(s["season"], s["season_year"]) for s in body["seasons"]] == [AIRING]


def test_arrival_follows_the_newest_started_season_as_it_gets_its_scores(settling_for):
    """The other half of the story, and the one the design is built on: an
    unscored title prints screened back to halftone, and this is that state
    draining to colour. A season is listed months before anyone has rated it."""
    client = settling_for(
        {
            "2026-09-13": [{"source_id": "1", "score_100": None, "user_count": 10},
                           {"source_id": "2", "score_100": None, "user_count": 20}],
            "2026-09-20": [{"source_id": "1", "score_100": 80.0, "user_count": 100},
                           {"source_id": "2", "score_100": None, "user_count": 20}],
            "2026-09-27": [{"source_id": "1", "score_100": 81.0, "user_count": 200},
                           {"source_id": "2", "score_100": 60.0, "user_count": 50}],
        },
        groups=[["kitsu:1"], ["kitsu:2"]],
    )

    arrival = client.get("/scores/settling").json()["arrival"]

    assert (arrival["season"], arrival["season_year"]) == AIRING
    assert [(p["run_date"], p["listed"], p["scored"]) for p in arrival["points"]] == [
        ("2026-09-13", 2, 0), ("2026-09-20", 2, 1), ("2026-09-27", 2, 2),
    ]


def test_a_single_snapshot_has_nothing_to_compare_and_says_so(settling_for):
    """The state of a fresh warehouse. Empty lists are the true answer; a 500
    would make the page look broken on the one day it is simply new."""
    client = settling_for({
        "2026-09-13": [{"source_id": "1", "score_100": 80.0, "user_count": 1000}],
    })

    body = client.get("/scores/settling").json()

    assert (body["reasks"], body["seasons"], body["bands"]) == (0, [], [])
    assert body["first_run"] == body["last_run"] == "2026-09-13"
    assert body["arrival"]["points"] == [{"run_date": "2026-09-13", "listed": 1, "scored": 1}]
