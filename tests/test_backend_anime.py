from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db
from backend.app.main import app
from processing.duckdb_catalog import refresh_catalog


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


@pytest.fixture
def client(tmp_path):
    data_dir = tmp_path / "data"
    _write_parquet(
        data_dir
        / "processed"
        / "anime_media_consolidated"
        / "2026-SUMMER"
        / "2026-09-07"
        / "part-0.parquet",
        [
            {
                "source": "kitsu",
                "source_id": "1",
                "title_english": "Demon Slayer",
                "title_romaji": None,
                "score_100": 84.0,
                "popularity": 500.0,
                "genres": ["Action", "Fantasy"],
                "format": "TV",
                "season": "SUMMER",
                "season_year": 2026,
                "run_date": "2026-09-07",
            },
            {
                "source": "kitsu",
                "source_id": "2",
                "title_english": "Frieren",
                "title_romaji": None,
                "score_100": 90.0,
                "popularity": 300.0,
                "genres": ["Fantasy", "Drama"],
                "format": "TV",
                "season": "SUMMER",
                "season_year": 2026,
                "run_date": "2026-09-07",
            },
        ],
    )
    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(data_dir, db_path)

    def override_get_db():
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            yield con
        finally:
            con.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_anime_sorted_by_score_desc_by_default(client):
    response = client.get("/anime")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert [item["title_english"] for item in data["items"]] == ["Frieren", "Demon Slayer"]


def test_list_anime_filters_by_genre_case_insensitively(client):
    response = client.get("/anime", params={"genre": "drama"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title_english"] == "Frieren"


def test_list_anime_respects_limit_and_offset(client):
    response = client.get("/anime", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["items"][0]["title_english"] == "Demon Slayer"


def test_get_anime_detail(client):
    response = client.get("/anime/kitsu/1")

    assert response.status_code == 200
    assert response.json()["title_english"] == "Demon Slayer"


def test_get_anime_not_found(client):
    response = client.get("/anime/kitsu/999")

    assert response.status_code == 404


def test_anime_endpoints_503_when_no_warehouse(tmp_path, monkeypatch):
    # Exercises the real get_db logic (not an override) - a missing warehouse file
    # is a legitimate early-project/all-sources-failed state, not a bug.
    import backend.app.db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "does-not-exist.duckdb")

    with TestClient(app) as test_client:
        response = test_client.get("/anime")

    assert response.status_code == 503
