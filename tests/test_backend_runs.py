"""GET /runs: the records each DAG's check_run writes, out of the warehouse."""

import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db_optional
from backend.app.main import app
from processing.duckdb_catalog import _prose_views


def _record(data, dag, run_date, passed=True, raw=None):
    path = data / "processed" / "runs" / dag / f"{run_date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        path.write_text(raw)
        return
    findings = [] if passed else [{"level": "fail", "message": "mal landed nothing"}]
    path.write_text(json.dumps({"dag": dag, "run_date": run_date, "passed": passed,
                                "checked_at": "x", "numbers": {"titles": 6136},
                                "findings": findings, "failed_tasks": []}))


@pytest.fixture
def client_over(tmp_path):
    def build(data) -> TestClient:
        db_path = tmp_path / "warehouse.duckdb"
        con = duckdb.connect(str(db_path))
        try:
            _prose_views(con, data)
        finally:
            con.close()

        def override():
            con = duckdb.connect(str(db_path), read_only=True)
            try:
                yield con
            finally:
                con.close()

        app.dependency_overrides[get_db_optional] = override
        return TestClient(app)

    yield build
    app.dependency_overrides.clear()


def test_recent_runs_come_newest_first_and_can_be_narrowed_to_one_dag(tmp_path, client_over):
    data = tmp_path / "data"
    _record(data, "anime_seasonal_pipeline", "2026-09-13")
    _record(data, "anime_seasonal_pipeline", "2026-09-20", passed=False)
    _record(data, "anilist_airing", "2026-09-15")
    _record(data, "anilist_airing", "2026-09-16", raw="{not json")
    client = client_over(data)

    everything = client.get("/runs").json()
    weekly = client.get("/runs?dag=anime_seasonal_pipeline&limit=1").json()

    assert [(r["dag"], r["run_date"], r["passed"]) for r in everything] == [
        ("anime_seasonal_pipeline", "2026-09-20", False),
        # 09-16's record is unreadable: skipped, not a 500, and not a gap that
        # swallows the records either side of it.
        ("anilist_airing", "2026-09-15", True),
        ("anime_seasonal_pipeline", "2026-09-13", True),
    ]
    assert weekly[0]["findings"] == [{"level": "fail", "message": "mal landed nothing"}]
    assert len(weekly) == 1


def test_no_records_at_all_is_an_empty_list_not_an_error(tmp_path, client_over):
    """Nothing has written a check into this warehouse. Nothing is broken."""
    client = client_over(tmp_path / "data")

    assert client.get("/runs").json() == []
