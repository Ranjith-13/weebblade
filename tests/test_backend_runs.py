"""GET /runs: the records each DAG's check_run writes."""

import json

from fastapi.testclient import TestClient

from backend.app.main import app


def _record(runs, dag, run_date, passed=True):
    path = runs / dag / f"{run_date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    findings = [] if passed else [{"level": "fail", "message": "mal landed nothing"}]
    path.write_text(json.dumps({"dag": dag, "run_date": run_date, "passed": passed, "checked_at": "x",
                                "numbers": {"titles": 6136}, "findings": findings, "failed_tasks": []}))


def test_recent_runs_come_newest_first_and_can_be_narrowed_to_one_dag(tmp_path, monkeypatch):
    import backend.app.routers.runs as runs_module

    runs = tmp_path / "runs"
    _record(runs, "anime_seasonal_pipeline", "2026-09-13")
    _record(runs, "anime_seasonal_pipeline", "2026-09-20", passed=False)
    _record(runs, "anilist_airing", "2026-09-15")
    (runs / "anilist_airing" / "2026-09-16.json").write_text("{not json")
    monkeypatch.setattr(runs_module, "RUNS_DIR", runs)

    client = TestClient(app)
    everything = client.get("/runs").json()
    weekly = client.get("/runs?dag=anime_seasonal_pipeline&limit=1").json()

    assert [(r["dag"], r["run_date"], r["passed"]) for r in everything] == [
        ("anime_seasonal_pipeline", "2026-09-20", False),
        ("anilist_airing", "2026-09-15", True),  # 09-16's record is unreadable: skipped, not a 500
        ("anime_seasonal_pipeline", "2026-09-13", True),
    ]
    assert weekly[0]["findings"] == [{"level": "fail", "message": "mal landed nothing"}]
    assert len(weekly) == 1


def test_no_runs_recorded_is_an_empty_list(tmp_path, monkeypatch):
    import backend.app.routers.runs as runs_module

    monkeypatch.setattr(runs_module, "RUNS_DIR", tmp_path / "nothing")

    assert TestClient(app).get("/runs").json() == []
