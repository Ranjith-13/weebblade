"""Running the pipeline without Airflow: pipeline/run.py."""

from datetime import datetime, timezone

import pytest

from pipeline import run as runner


@pytest.fixture
def steps(monkeypatch):
    """Replace every step with a recorder, so a test can watch the order and
    make any one of them fail without touching an API."""
    called: list[str] = []

    def build(fail: set[str] | None = None):
        fail = fail or set()

        def fake(name):
            def step(data_dir, at, run_date):
                called.append(name)
                if name in fail:
                    raise RuntimeError(f"{name} fell over")

            return step

        for group in ("WEEKLY", "DAILY"):
            monkeypatch.setattr(
                runner, group,
                [runner.Step(s.name, fake(s.name)) for s in getattr(runner, group)],
            )
        return called

    return build


@pytest.fixture
def checks(monkeypatch):
    """Stand in for processing.run_checks, and report what it was told."""
    seen: dict = {}

    class _Record:
        def __init__(self, passed):
            self.passed = passed

        def summary(self):
            return "summary"

    def build(passed: bool = True):
        def check(data_dir, run_date, failed):
            seen.update(data_dir=data_dir, run_date=run_date, failed=failed)
            return _Record(passed)

        monkeypatch.setattr("processing.run_checks.check_weekly", check)
        monkeypatch.setattr("processing.run_checks.check_daily", check)
        monkeypatch.setattr("processing.run_checks.notify", lambda record: seen.update(notified=True))
        return seen

    return build


AT = datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc)


def test_the_weekly_run_does_the_dags_work_in_the_dags_order(steps, checks, tmp_path):
    """The names are the DAG's task ids on purpose: a failure reads the same in
    both places, and run_checks is handed these names."""
    called = steps()
    checks()

    assert runner.run("weekly", tmp_path, AT) == 0
    assert called == [
        "fetch_anilist", "fetch_mal", "fetch_kitsu",
        "fetch_bridge_ids", "build_bridge", "consolidate", "record_changes",
        "refresh_catalog", "fetch_mal_relations", "build_franchises",
        "generate_digest", "build_search_index", "build_similar",
    ]


def test_the_daily_run_does_the_same(steps, checks, tmp_path):
    called = steps()
    checks()

    assert runner.run("daily", tmp_path, AT) == 0
    # refresh_catalog LAST, and the order is the assertion. The views are built
    # from the lake before any step runs, and a fetch that changes a file's
    # shape - score_100 and user_count arriving in anilist_status - leaves them
    # describing a source that no longer matches. Re-deriving them before the
    # check is what stops a run that did all its work from going red on
    # "Contents of view were altered".
    assert called == ["fetch_airing", "resolve_ids", "fetch_status", "refresh_catalog"]


def test_a_failed_step_does_not_stop_the_run(steps, checks, tmp_path):
    """Every task after the fetches is ALL_DONE in the DAG: consolidating
    whatever landed beats blocking the whole pipeline on one sick API."""
    called = steps(fail={"fetch_mal"})
    seen = checks()

    runner.run("weekly", tmp_path, AT)

    assert "build_search_index" in called  # the run reached the end
    assert seen["failed"] == ["fetch_mal"]


def test_what_failed_is_judged_by_the_check_not_instead_of_it(steps, checks, tmp_path):
    """A step dying is not the verdict - the check reads what the run actually
    produced, and gets the failures as one more input."""
    steps(fail={"fetch_mal", "consolidate"})
    seen = checks(passed=True)

    assert runner.run("weekly", tmp_path, AT) == 0
    assert seen["failed"] == ["fetch_mal", "consolidate"]


def test_a_failing_check_exits_non_zero_and_tells_someone(steps, checks, tmp_path):
    """How a scheduler - Airflow or Actions - learns the run was bad."""
    steps()
    seen = checks(passed=False)

    assert runner.run("weekly", tmp_path, AT) == 1
    assert seen["notified"] is True


def test_the_run_date_comes_from_the_end_of_the_interval(steps, checks, tmp_path):
    """Never logical_date, which is the start of the interval and would file
    today's fetch under last week."""
    steps()
    seen = checks()

    runner.run("daily", tmp_path, AT)

    assert seen["run_date"] == "2026-10-11"


def test_a_dry_run_runs_nothing(steps, checks, tmp_path, capsys):
    called = steps()
    checks()

    assert runner.main(["weekly", "--data-dir", str(tmp_path), "--dry-run"]) == 0
    assert called == []
    assert "consolidate" in capsys.readouterr().out
