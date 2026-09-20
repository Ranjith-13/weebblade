"""GET /catalogue: the shape of the catalogue without paging through it."""

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db
from backend.app.main import app
from processing.duckdb_catalog import refresh_catalog


@pytest.fixture
def catalogue_for(tmp_path):
    """A client over a catalogue built from `rows`, the way the pipeline builds one."""

    def build(rows: list[dict]) -> TestClient:
        path = (
            tmp_path / "data" / "processed" / "anime_media_consolidated" / "_catalogue"
            / "2026-09-10" / "part-0.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path)
        db_path = tmp_path / "warehouse.duckdb"
        refresh_catalog(tmp_path / "data", db_path)

        def override_get_db():
            con = duckdb.connect(str(db_path), read_only=True)
            try:
                yield con
            finally:
                con.close()

        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    yield build
    app.dependency_overrides.clear()


def _title(source_id: str, season: str | None, year: int | None, **over) -> dict:
    row = {
        "source": "kitsu", "source_id": source_id, "title_english": f"Title {source_id}",
        "format": "TV", "season": season, "season_year": year, "run_date": "2026-09-10",
    }
    row.update(over)
    return row


def test_seasons_come_newest_first_in_broadcast_order_not_alphabetical(catalogue_for):
    """Alphabetically FALL sorts before SPRING and SUMMER; the broadcast year ends
    with it. A season list in the wrong order puts the newest season mid-list."""
    client = catalogue_for([
        _title("1", "WINTER", 2025), _title("2", "FALL", 2025), _title("3", "SPRING", 2025),
        _title("4", "SUMMER", 2025), _title("5", "WINTER", 2026), _title("6", "FALL", 2025),
    ])

    seasons = client.get("/catalogue").json()["seasons"]

    assert [(s["season"], s["season_year"], s["count"]) for s in seasons] == [
        ("WINTER", 2026, 1),
        ("FALL", 2025, 2),
        ("SUMMER", 2025, 1),
        ("SPRING", 2025, 1),
        ("WINTER", 2025, 1),
    ]


def test_a_title_with_no_season_counts_in_the_total_and_in_no_season(catalogue_for):
    client = catalogue_for([_title("1", "SUMMER", 2026), _title("2", None, None)])

    body = client.get("/catalogue").json()

    assert body["total"] == 2
    assert body["seasons"] == [
        {"season": "SUMMER", "season_year": 2026, "count": 1, "upcoming": False}]


def test_sources_include_one_that_never_won_a_merge(catalogue_for):
    """MAL supplies studios and source material for titles Kitsu wins. Naming only
    merge winners would call a source that contributed to every title absent."""
    client = catalogue_for([
        _title("1", "SUMMER", 2026, wb_id="wb_a", source_keys=["kitsu:1", "mal:10"]),
        _title("2", "SUMMER", 2026, wb_id="wb_b", source_keys=["kitsu:2"]),
    ])

    assert client.get("/catalogue").json()["sources"] == ["kitsu", "mal"]


def test_before_identities_sources_fall_back_to_the_merge_winners(catalogue_for):
    client = catalogue_for([
        _title("1", "SUMMER", 2026),
        _title("10", "SUMMER", 2026, source="mal"),
    ])

    assert client.get("/catalogue").json()["sources"] == ["kitsu", "mal"]


def test_catalogue_is_a_503_before_the_pipeline_has_run(tmp_path, monkeypatch):
    import backend.app.db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "does-not-exist.duckdb")

    with TestClient(app) as client:
        assert client.get("/catalogue").status_code == 503


def test_a_season_the_sources_list_but_that_has_not_started_says_so(catalogue_for):
    """The pipeline fetches the next season months before it airs, so "the newest
    season on file" is not what a reader means by "this season". A client that
    took it would default every page to a season with nothing aired in it."""
    client = catalogue_for([_title("1", "SUMMER", 2026), _title("2", "WINTER", 2099)])

    seasons = {(s["season"], s["season_year"]): s["upcoming"] for s in client.get("/catalogue").json()["seasons"]}

    assert seasons == {("WINTER", 2099): True, ("SUMMER", 2026): False}
