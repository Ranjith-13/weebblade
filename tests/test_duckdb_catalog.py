from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from processing.duckdb_catalog import refresh_catalog


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_refresh_catalog_creates_views_for_available_sources(tmp_path):
    data_dir = tmp_path / "data"
    _write_parquet(
        data_dir / "processed" / "kitsu_media" / "2026-SUMMER" / "2026-09-07.parquet",
        [{"source": "kitsu", "source_id": "1", "title_english": "Test Anime"}],
    )
    # anilist_media and jikan_media are deliberately absent, simulating those sources
    # being down - the catalog refresh should skip them, not fail entirely.

    db_path = tmp_path / "warehouse.duckdb"
    created = refresh_catalog(data_dir, db_path)

    assert "anime_media_kitsu" in created
    assert "anime_media_anilist" not in created
    assert "anime_media_jikan" not in created

    import duckdb

    con = duckdb.connect(str(db_path))
    try:
        rows = con.execute("SELECT title_english FROM anime_media_kitsu").fetchall()
    finally:
        con.close()

    assert rows == [("Test Anime",)]


def test_refresh_catalog_handles_no_data_at_all(tmp_path):
    """Nothing in the lake claims nothing over it - except the two views that
    exist whether their files do or not.

    digest and run_check are written later in the same run than this function
    is called (see _prose_views), so guarding them on the files already being
    there would mean a run never publishing its own digest. An empty glob is
    zero rows, so the views are honest about having nothing.
    """
    data_dir = tmp_path / "data"
    db_path = tmp_path / "warehouse.duckdb"

    created = refresh_catalog(data_dir, db_path)

    assert created == ["digest", "run_check"]

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM digest").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM run_check").fetchone()[0] == 0
    finally:
        con.close()


def test_anime_media_latest_dedupes_to_most_recent_run(tmp_path):
    data_dir = tmp_path / "data"
    # Same title (source="anilist", source_id="1") appears in two different weekly
    # runs with a different score each time - anime_media_latest should keep only
    # the most recent one, not both.
    _write_parquet(
        data_dir
        / "processed"
        / "anime_media_consolidated"
        / "2026-SUMMER"
        / "2026-08-31"
        / "part-0.parquet",
        [{"source": "anilist", "source_id": "1", "score_100": 70.0, "run_date": "2026-08-31"}],
    )
    _write_parquet(
        data_dir
        / "processed"
        / "anime_media_consolidated"
        / "2026-SUMMER"
        / "2026-09-07"
        / "part-0.parquet",
        [{"source": "anilist", "source_id": "1", "score_100": 75.0, "run_date": "2026-09-07"}],
    )

    db_path = tmp_path / "warehouse.duckdb"
    created = refresh_catalog(data_dir, db_path)

    assert "anime_media_latest" in created

    import duckdb

    con = duckdb.connect(str(db_path))
    try:
        all_rows = con.execute("SELECT COUNT(*) FROM anime_media").fetchone()
        latest_rows = con.execute(
            "SELECT score_100, run_date FROM anime_media_latest"
        ).fetchall()
    finally:
        con.close()

    assert all_rows == (2,)
    assert latest_rows == [(75.0, "2026-09-07")]


# --- identity-aware latest view -------------------------------------------------

import duckdb  # noqa: E402

from processing.identity import Registry, assign, save  # noqa: E402


def _catalogue(data_dir: Path, run_date: str, rows: list[dict]) -> None:
    for r in rows:
        r.setdefault("run_date", run_date)
    _write_parquet(
        data_dir / "processed" / "anime_media_consolidated" / "_catalogue" / run_date / "part-0.parquet",
        rows,
    )


def _latest(tmp_path, data_dir):
    db = tmp_path / "warehouse.duckdb"
    refresh_catalog(data_dir, db)
    con = duckdb.connect(str(db))
    try:
        cols = [c[0] for c in con.execute("DESCRIBE anime_media_latest").fetchall()]
        rows = con.execute("SELECT * FROM anime_media_latest ORDER BY source, source_id").fetchall()
        return [dict(zip(cols, r)) for r in rows]
    finally:
        con.close()


def test_without_a_registry_the_view_behaves_exactly_as_before(tmp_path):
    """A lake that has never seen an identity - every deploy until the first new
    run - must render the same catalogue it did yesterday."""
    data = tmp_path / "data"
    _catalogue(data, "2026-09-09", [
        {"source": "kitsu", "source_id": "1", "title_english": "A"},
        {"source": "kitsu", "source_id": "2", "title_english": "B"},
    ])

    rows = _latest(tmp_path, data)

    assert [r["title_english"] for r in rows] == ["A", "B"]


def test_a_change_of_winning_source_no_longer_duplicates_the_title(tmp_path):
    """The bug in the old view, reproduced. Week one the title survives the
    merge as kitsu:1; week two MAL wins and it survives as mal:10. Keyed by
    (source, source_id) those are two titles and both stayed. Keyed by identity
    they are one, and the newer row wins."""
    data = tmp_path / "data"
    ids, reg, _ = assign([["kitsu:1", "mal:10"]], Registry(), "2026-09-09")
    save(data, reg)
    _catalogue(data, "2026-09-09", [
        {"source": "kitsu", "source_id": "1", "title_english": "Old", "wb_id": ids[0]},
    ])
    _catalogue(data, "2026-09-16", [
        {"source": "mal", "source_id": "10", "title_english": "New", "wb_id": ids[0]},
    ])

    rows = _latest(tmp_path, data)

    assert [(r["title_english"], r["wb_id"]) for r in rows] == [("New", ids[0])]


def test_rows_written_before_identities_existed_are_resolved_through_the_registry(tmp_path):
    """The live lake is mostly old snapshots with no wb_id column at all. Each
    must still be recognised as the title it is, via its source key, or it would
    survive beside the new stamped row as a duplicate on the first run."""
    data = tmp_path / "data"
    ids, reg, _ = assign([["kitsu:1", "mal:10"]], Registry(), "2026-09-16")
    save(data, reg)
    # an old per-partition snapshot: no wb_id, no source_keys
    _write_parquet(
        data / "processed" / "anime_media_consolidated" / "2026-SUMMER" / "2026-08-30" / "part-0.parquet",
        [{"source": "kitsu", "source_id": "1", "title_english": "Old", "run_date": "2026-08-30"}],
    )
    _catalogue(data, "2026-09-16", [
        {"source": "kitsu", "source_id": "1", "title_english": "New", "wb_id": ids[0]},
    ])

    rows = _latest(tmp_path, data)

    assert [(r["title_english"], r["wb_id"]) for r in rows] == [("New", ids[0])]


def test_a_row_stamped_with_a_since_merged_identity_follows_its_alias(tmp_path):
    """Two identities merge; an older row still carries the one that retired. It
    has to land in the surviving title's partition, or both rows survive."""
    data = tmp_path / "data"
    a, reg, _ = assign([["kitsu:1"]], Registry(), "2026-06-15")
    b, reg, _ = assign([["kitsu:1"], ["mal:10"]], reg, "2026-09-09")
    merged, reg, _ = assign([["kitsu:1", "mal:10"]], reg, "2026-09-16")
    save(data, reg)
    _catalogue(data, "2026-09-09", [
        {"source": "mal", "source_id": "10", "title_english": "Stale", "wb_id": b[1]},
    ])
    _catalogue(data, "2026-09-16", [
        {"source": "kitsu", "source_id": "1", "title_english": "Current", "wb_id": merged[0]},
    ])

    rows = _latest(tmp_path, data)

    assert [(r["title_english"], r["wb_id"]) for r in rows] == [("Current", a[0])]


def test_every_row_in_the_latest_view_carries_an_identity(tmp_path):
    data = tmp_path / "data"
    ids, reg, _ = assign([["kitsu:1"], ["kitsu:2"]], Registry(), "2026-09-16")
    save(data, reg)
    _catalogue(data, "2026-09-16", [
        {"source": "kitsu", "source_id": "1", "title_english": "A", "wb_id": ids[0]},
        {"source": "kitsu", "source_id": "2", "title_english": "B", "wb_id": ids[1]},
    ])

    rows = _latest(tmp_path, data)

    assert sorted(r["wb_id"] for r in rows) == sorted(ids)


# --- the newest catalogue snapshot -------------------------------------------------------

import duckdb  # noqa: E402


def _snapshot(data_dir, run_date, rows, complete=True):
    """A catalogue snapshot as Spark writes one: a directory of parts, with a
    _SUCCESS marker once the job has committed."""
    out = data_dir / "processed" / "anime_media_consolidated" / "_catalogue" / run_date
    _write_parquet(out / "part-0.parquet", [{**r, "run_date": run_date} for r in rows])
    if complete:
        (out / "_SUCCESS").write_text("")


def _served_and_history(tmp_path):
    con = duckdb.connect(str(tmp_path / "warehouse.duckdb"), read_only=True)
    try:
        return con.execute("SELECT source_id, score_100, run_date FROM anime_media_latest ORDER BY 1").fetchall(), \
            con.execute("SELECT count(*) FROM anime_media").fetchone()[0]
    finally:
        con.close()


def test_the_latest_view_reads_the_newest_complete_snapshot_and_history_keeps_the_rest(tmp_path):
    """Consolidation reads every source snapshot, so the newest catalogue holds
    every title; reading only it made a season query ten times cheaper."""
    data = tmp_path / "data"
    _snapshot(data, "2026-09-13", [{"source": "kitsu", "source_id": "1", "score_100": 70.0}])
    _snapshot(data, "2026-09-14", [{"source": "kitsu", "source_id": "1", "score_100": 75.0},
                                   {"source": "kitsu", "source_id": "2", "score_100": 60.0}])
    refresh_catalog(data, tmp_path / "warehouse.duckdb")

    latest, history = _served_and_history(tmp_path)

    assert latest == [("1", 75.0, "2026-09-14"), ("2", 60.0, "2026-09-14")]
    assert history == 3


def test_a_snapshot_whose_run_died_mid_write_is_not_served(tmp_path):
    data = tmp_path / "data"
    _snapshot(data, "2026-09-13", [{"source": "kitsu", "source_id": "1", "score_100": 70.0}])
    _snapshot(data, "2026-09-14", [{"source": "kitsu", "source_id": "1", "score_100": 75.0}], complete=False)
    refresh_catalog(data, tmp_path / "warehouse.duckdb")

    assert _served_and_history(tmp_path)[0] == [("1", 70.0, "2026-09-13")]


# --- airing the check could not confirm -------------------------------------------

def _airing(source_id, status, start_year=None):
    return {"source": "kitsu", "source_id": source_id, "title_english": f"T{source_id}",
            "status": status, "start_year": start_year, "start_month": 4, "start_day": 1}


def test_a_title_airing_since_years_ago_that_nothing_confirms_is_flagged(tmp_path):
    """The 48 of them in live data. AniList has never answered for this title,
    so the only evidence it is airing is a source snapshot from 2022."""
    data = tmp_path / "data"
    _catalogue(data, "2026-09-21", [_airing("1", "current", 2022)])

    assert _latest(tmp_path, data)[0]["airing_unconfirmed"] is True


def test_a_title_that_premiered_recently_is_not_flagged(tmp_path):
    """The sources' word is fresh, and for a show that started this season it is
    all anyone has."""
    data = tmp_path / "data"
    _catalogue(data, "2026-09-21", [_airing("1", "current", 2026)])

    assert _latest(tmp_path, data)[0]["airing_unconfirmed"] is False


def test_a_title_with_no_premiere_at_all_is_not_flagged(tmp_path):
    """Unconfirmed means known to be old, not impossible to date."""
    data = tmp_path / "data"
    _catalogue(data, "2026-09-21", [_airing("1", "current", None)])

    assert _latest(tmp_path, data)[0]["airing_unconfirmed"] is False


def test_a_finished_title_is_never_flagged(tmp_path):
    """Nothing is being claimed about it that wants confirming."""
    data = tmp_path / "data"
    _catalogue(data, "2026-09-21", [_airing("1", "finished", 2022)])

    assert _latest(tmp_path, data)[0]["airing_unconfirmed"] is False



# --- the daily score series ------------------------------------------------
#
# Weekly snapshots record a score that moved twice in a week as one move. This
# view is the dense half, read from the DATED anilist_status files that
# ingestion.storage.write_daily has been keeping all along - the only view here
# that reads a glob rather than processed/current, because here the history is
# the subject rather than a cost on every request.


def _status_day(data_dir: Path, run_date: str, rows: list[dict], with_score: bool = True) -> None:
    """A day's AniList status answers, as fetch_status lands them."""
    import pyarrow as pa

    fields = [("anilist_id", pa.int64()), ("mal_id", pa.int64()), ("status", pa.string())]
    if with_score:
        fields += [("score_100", pa.int64()), ("user_count", pa.int64())]
    fields += [("ended_on", pa.string()), ("fetched_on", pa.string())]
    for r in rows:
        r.setdefault("mal_id", None)
        r.setdefault("status", "current")
        r.setdefault("ended_on", None)
        r.setdefault("fetched_on", run_date)
        if not with_score:
            r.pop("score_100", None)
            r.pop("user_count", None)
    path = data_dir / "processed" / "anilist_status" / f"{run_date}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(fields)), path)


def _series(tmp_path, data_dir):
    db = tmp_path / "warehouse.duckdb"
    created = refresh_catalog(data_dir, db)
    if "anime_score_daily" not in created:
        return created, []
    con = duckdb.connect(str(db))
    try:
        rows = con.execute(
            "SELECT wb_id, fetched_on, score_100, user_count FROM anime_score_daily "
            "ORDER BY wb_id, fetched_on"
        ).fetchall()
    finally:
        con.close()
    return created, rows


def test_a_score_asked_for_daily_keeps_one_reading_per_day(tmp_path):
    """The point of the whole item: weekly granularity flattens movement inside
    a week, so three days must be three readings and not one."""
    data = tmp_path / "data"
    ids, reg, _ = assign([["anilist:1"]], Registry(), "2026-10-16")
    save(data, reg)
    _catalogue(data, "2026-10-16", [
        {"source": "anilist", "source_id": "1", "title_english": "A", "wb_id": ids[0]},
    ])
    for day, score, votes in (("2026-10-14", 78, 40_000), ("2026-10-15", 78, 40_900),
                              ("2026-10-16", 79, 41_400)):
        _status_day(data, day, [{"anilist_id": 1, "score_100": score, "user_count": votes}])

    created, rows = _series(tmp_path, data)

    assert "anime_score_daily" in created
    assert rows == [
        (ids[0], "2026-10-14", 78, 40_000),
        (ids[0], "2026-10-15", 78, 40_900),
        (ids[0], "2026-10-16", 79, 41_400),
    ]


def test_a_reading_with_no_score_is_absent_rather_than_null(tmp_path):
    """A title nobody has rated has not been measured, which is a different
    thing from one measured at the same value as yesterday."""
    data = tmp_path / "data"
    ids, reg, _ = assign([["anilist:1"]], Registry(), "2026-10-16")
    save(data, reg)
    _catalogue(data, "2026-10-16", [
        {"source": "anilist", "source_id": "1", "title_english": "A", "wb_id": ids[0]},
    ])
    _status_day(data, "2026-10-15", [{"anilist_id": 1, "score_100": None, "user_count": 12}])
    _status_day(data, "2026-10-16", [{"anilist_id": 1, "score_100": 71, "user_count": 90}])

    _, rows = _series(tmp_path, data)

    assert rows == [(ids[0], "2026-10-16", 71, 90)]


def test_days_fetched_before_the_score_was_collected_do_not_break_the_series(tmp_path):
    """Every dated file written before this shipped has neither column. They
    have to read as absent readings, not as an error that takes the view out."""
    data = tmp_path / "data"
    ids, reg, _ = assign([["anilist:1"]], Registry(), "2026-10-16")
    save(data, reg)
    _catalogue(data, "2026-10-16", [
        {"source": "anilist", "source_id": "1", "title_english": "A", "wb_id": ids[0]},
    ])
    _status_day(data, "2026-09-30", [{"anilist_id": 1}], with_score=False)
    _status_day(data, "2026-10-16", [{"anilist_id": 1, "score_100": 71, "user_count": 90}])

    created, rows = _series(tmp_path, data)

    assert "anime_score_daily" in created
    assert rows == [(ids[0], "2026-10-16", 71, 90)]


def test_before_any_day_carries_a_score_there_is_no_series_at_all(tmp_path):
    """The state on the morning this ships. No column to select, so no view -
    rather than a view that fails every query that touches it."""
    data = tmp_path / "data"
    ids, reg, _ = assign([["anilist:1"]], Registry(), "2026-10-16")
    save(data, reg)
    _catalogue(data, "2026-10-16", [
        {"source": "anilist", "source_id": "1", "title_english": "A", "wb_id": ids[0]},
    ])
    _status_day(data, "2026-09-30", [{"anilist_id": 1}], with_score=False)

    created, rows = _series(tmp_path, data)

    assert "anime_score_daily" not in created
    assert rows == []
