"""What a run checks about its own output. Real files in tmp_path, so these run
anywhere; the catalogue snapshots stand in for what Spark writes."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ingestion.anilist.fetch_airing import SCHEMA as AIRING_SCHEMA
from ingestion.anilist.fetch_status import SCHEMA as STATUS_SCHEMA
from ingestion.storage import write_daily
from processing import identity, run_checks
from processing.changes import SCHEMA as CHANGES_SCHEMA
from processing.duckdb_catalog import refresh_catalog
from processing.run_checks import check_daily, check_weekly, notify


def _landed(data, source, date, n, partition="2026-SUMMER"):
    path = data / "processed" / f"{source}_media" / partition / f"{date}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([{"source_id": str(i)} for i in range(n)]), path)


def _catalogue(data, date, groups, registry):
    """A consolidated snapshot of `groups` (lists of source keys), identities
    assigned the way consolidate does it."""
    ids, registry, report = identity.assign(groups, registry, date)
    identity.save(data, registry)
    out = data / "processed" / "anime_media_consolidated" / "_catalogue" / date
    out.mkdir(parents=True, exist_ok=True)
    rows = [{"source": k[0].split(":")[0], "source_id": k[0].split(":")[1], "wb_id": wb_id, "source_keys": k,
             "title_english": f"T {wb_id}", "run_date": date} for wb_id, k in zip(ids, groups)]
    pq.write_table(pa.Table.from_pylist(rows), out / "part-0.parquet")
    (out / "_SUCCESS").touch()
    return dict(zip(map(tuple, groups), ids)), registry, report


def _changes(data, date):
    path = data / "processed" / "changes" / f"{date}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"wb_id": None, "source": "kitsu", "source_id": "1", "field": "status", "old": "current",
           "new": "finished", "label": None, "run_date": date, "since": "2026-09-06", "partition": "2026-SUMMER"}
    pq.write_table(pa.Table.from_pylist([row], schema=CHANGES_SCHEMA), path)


def _week(data, before, now, landed_now=None):
    """Last week's catalogue of `before` and this week's of `now`, both sources
    fetched both weeks, the warehouse refreshed onto this week's."""
    _, registry, _ = _catalogue(data, "2026-09-06", before, identity.Registry())
    _catalogue(data, "2026-09-13", now, registry)
    for source, n in {"kitsu": 10, "mal": 12}.items():
        _landed(data, source, "2026-09-06", n)
        got = (landed_now or {}).get(source, n + 1)
        if got is not None:
            _landed(data, source, "2026-09-13", got)
    _changes(data, "2026-09-13")
    refresh_catalog(data, data / "warehouse.duckdb")


TWO = [["kitsu:1", "mal:1"], ["kitsu:2"]]


def _fails(record):
    return [f.message for f in record.findings if f.level == "fail"]


def test_a_healthy_week_passes_and_writes_its_numbers_down(tmp_path):
    _week(tmp_path, TWO, TWO + [["kitsu:3"]])

    record = check_weekly(tmp_path, "2026-09-13")

    assert record.passed, record.summary()
    n = record.numbers
    assert (n["titles"], n["titles_before"], n["kept"], n["minted"], n["merged"], n["lost"], n["split"]) == (3, 2, 2, 1, 0, 0, 0)
    assert n["sources"]["kitsu"] == {"rows": 11, "previous": 10, "previous_date": "2026-09-06"}
    assert (n["served_snapshot"], n["changes"]) == ("2026-09-13", {"status": 1})
    saved = json.loads((tmp_path / "processed" / "runs" / "anime_seasonal_pipeline" / "2026-09-13.json").read_text())
    assert saved["passed"] is True and saved["numbers"]["minted"] == 1


def test_a_source_that_answered_last_week_and_landed_nothing_fails_the_run(tmp_path):
    _week(tmp_path, TWO, TWO, landed_now={"mal": None})

    assert _fails(check_weekly(tmp_path, "2026-09-13")) == [
        "mal landed nothing; its fetch of 2026-09-06 landed 12 rows"]


def test_a_source_landing_under_half_of_last_week_fails(tmp_path):
    """What Kitsu's paging bug looked like from outside: a listing that shrank."""
    _week(tmp_path, TWO, TWO, landed_now={"kitsu": 4})

    assert _fails(check_weekly(tmp_path, "2026-09-13")) == [
        "kitsu landed 4 rows, under half the 10 of 2026-09-06"]


def test_a_source_that_has_never_answered_is_not_news(tmp_path):
    _week(tmp_path, TWO, TWO)

    record = check_weekly(tmp_path, "2026-09-13", failed_tasks=["fetch_jikan"])

    assert record.passed
    assert record.numbers["sources"]["jikan"] == {"rows": 0, "previous": None, "previous_date": None}


def test_a_source_is_compared_with_its_last_fetch_of_the_same_season(tmp_path):
    """MAL's newest fetch before 2026-09-13 was of other seasons, on 09-11; its
    last Summer fetch was 09-10. The first version compared with 09-11's 0."""
    _week(tmp_path, TWO, TWO)
    _landed(tmp_path, "mal", "2026-09-10", 12, partition="2026-SPRING")

    assert check_weekly(tmp_path, "2026-09-13").numbers["sources"]["mal"]["previous"] == 12


def test_a_title_gone_from_the_catalogue_fails(tmp_path):
    _week(tmp_path, TWO, [["kitsu:1", "mal:1"]])

    fails = _fails(check_weekly(tmp_path, "2026-09-13"))

    assert len(fails) == 1 and fails[0].startswith("1 title(s) from 2026-09-06 gone: wb_")


def test_merges_are_counted_and_too_many_in_one_run_fail(tmp_path, monkeypatch):
    _week(tmp_path, [["kitsu:1"], ["mal:1"], ["kitsu:2"]], [["kitsu:1", "mal:1"], ["kitsu:2"]])

    assert check_weekly(tmp_path, "2026-09-13").numbers["merged"] == 1

    monkeypatch.setattr(run_checks, "MERGED_LIMIT", 0)
    assert _fails(check_weekly(tmp_path, "2026-09-13")) == ["1 titles merged into others, more than 0 in one run"]


def test_a_split_fails_though_consolidate_counts_it_as_a_new_title(tmp_path):
    """Two 2024 music videos called Moonlight were one title until 2026-09-14;
    the matching guard separated them. The identity report said "minted"; the
    catalogue says one title's rows now sit on two."""
    moonlight = ["kitsu:49268", "mal:59994", "mal:60524"]
    _week(tmp_path, [moonlight], [moonlight[:2], moonlight[2:]])

    fails = _fails(check_weekly(tmp_path, "2026-09-13"))

    assert len(fails) == 1 and fails[0].startswith("1 title(s) split: wb_")


def test_a_run_with_no_complete_catalogue_fails(tmp_path):
    _week(tmp_path, TWO, TWO)
    (tmp_path / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-13" / "_SUCCESS").unlink()

    assert "No complete catalogue snapshot for 2026-09-13" in _fails(check_weekly(tmp_path, "2026-09-13"))


def test_a_warehouse_still_serving_last_weeks_catalogue_fails(tmp_path):
    """consolidate wrote the new snapshot; the refresh that should serve it did
    not run."""
    _, registry, _ = _catalogue(tmp_path, "2026-09-06", TWO, identity.Registry())
    refresh_catalog(tmp_path, tmp_path / "warehouse.duckdb")
    _catalogue(tmp_path, "2026-09-13", TWO, registry)
    _changes(tmp_path, "2026-09-13")

    assert _fails(check_weekly(tmp_path, "2026-09-13")) == [
        "The warehouse serves the catalogue of 2026-09-06, not 2026-09-13"]


def test_a_failed_task_fails_the_run_and_a_failed_fetch_is_judged_by_what_it_landed(tmp_path):
    _week(tmp_path, TWO, TWO)

    record = check_weekly(tmp_path, "2026-09-13", failed_tasks=["fetch_jikan", "build_search_index"])

    assert _fails(record) == ["Task(s) failed: build_search_index"]


def test_a_run_that_recorded_no_changes_fails(tmp_path):
    _week(tmp_path, TWO, TWO)
    (tmp_path / "processed" / "changes" / "2026-09-13.parquet").unlink()

    assert _fails(check_weekly(tmp_path, "2026-09-13")) == ["No changes recorded for 2026-09-13"]


# --- The daily AniList run ---------------------------------------------------------------

def _episode(n, fetched_on):
    return {"anilist_id": n, "mal_id": None, "episode": 1, "airing_at": 1789000000 + n, "title": "T",
            "format": "TV", "episodes": 12, "poster_url": None, "fetched_on": fetched_on}


def _answer(n, fetched_on, mal=None):
    return {"anilist_id": n, "mal_id": mal, "status": "finished", "ended_on": None, "fetched_on": fetched_on}


def _day(data, date, episodes=2, answers=2):
    write_daily([_episode(i, date) for i in range(episodes)], AIRING_SCHEMA, data, "anilist_airing", date)
    write_daily([_answer(i, date) for i in range(answers)], STATUS_SCHEMA, data, "anilist_status", date)


def test_a_day_that_landed_its_schedule_and_answers_passes(tmp_path):
    _day(tmp_path, "2026-09-14")
    _day(tmp_path, "2026-09-15")

    record = check_daily(tmp_path, "2026-09-15")

    assert record.passed, record.summary()
    assert record.numbers["anilist_airing"] == {"rows": 2, "previous": 2}


def test_a_day_whose_schedule_came_back_empty_fails(tmp_path):
    _day(tmp_path, "2026-09-14")
    _day(tmp_path, "2026-09-15", episodes=0)

    assert _fails(check_daily(tmp_path, "2026-09-15")) == ["anilist_airing landed nothing; 2026-09-14 landed 2"]


def test_a_served_file_older_than_the_run_fails(tmp_path):
    _day(tmp_path, "2026-09-15")
    dated = tmp_path / "processed" / "anilist_status" / "2026-09-16.parquet"
    pq.write_table(pa.Table.from_pylist([_answer(1, "2026-09-16")], schema=STATUS_SCHEMA), dated)
    write_daily([_episode(1, "2026-09-16")], AIRING_SCHEMA, tmp_path, "anilist_airing", "2026-09-16")

    assert _fails(check_daily(tmp_path, "2026-09-16")) == ["The served anilist_status is from 2026-09-15, not 2026-09-16"]


def test_a_failed_daily_task_fails_the_run(tmp_path):
    _day(tmp_path, "2026-09-15")

    assert _fails(check_daily(tmp_path, "2026-09-15", failed_tasks=["fetch_status"])) == ["Task(s) failed: fetch_status"]


# --- Telling someone ---------------------------------------------------------------------

class _Sent:
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _failed_record():
    record = run_checks.RunRecord("anime_seasonal_pipeline", "2026-09-20")
    record.fail("mal landed nothing")
    return record


def test_a_failed_run_is_pushed_only_where_a_topic_is_set(monkeypatch):
    sent = _Sent()
    monkeypatch.setattr(run_checks.urllib.request, "urlopen", sent)

    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert notify(_failed_record()) is False

    monkeypatch.setenv("NTFY_TOPIC", "a-topic")
    assert notify(run_checks.RunRecord("anime_seasonal_pipeline", "2026-09-20")) is False  # it passed
    assert notify(_failed_record()) is True

    [request] = sent.requests
    assert request.full_url == "https://ntfy.sh/a-topic"
    assert request.get_header("Title") == "WeebBlade anime_seasonal_pipeline 2026-09-20 failed its checks"
    assert b"fail: mal landed nothing" in request.data


def test_a_notification_that_cannot_be_sent_does_not_hide_the_failure(monkeypatch):
    def down(request, timeout):
        raise OSError("no route")

    monkeypatch.setenv("NTFY_TOPIC", "a-topic")
    monkeypatch.setattr(run_checks.urllib.request, "urlopen", down)

    assert notify(_failed_record()) is False
