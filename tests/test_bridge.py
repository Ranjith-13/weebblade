"""Which MAL ids AniList's record is allowed to put on a Kitsu-only row."""

import pyarrow as pa
import pyarrow.parquet as pq

from ingestion.anilist.bridge_ids import SCHEMA as LEDGER_SCHEMA
from processing.bridge import OUT_NAME, build_bridge


def _snapshot(data_dir, source, partition, run_date, rows):
    """A source's own rows: (source_id, start_year, start_month, start_day) and
    optionally the MAL id the row carries - its own for a MAL row, whatever
    Kitsu maps it to for a Kitsu one."""
    out = data_dir / "processed" / f"{source}_media" / partition / f"{run_date}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"source": source, "source_id": str(row[0]), "start_year": row[1],
                 "start_month": row[2], "start_day": row[3],
                 "mal_id": row[4] if len(row) > 4 else (int(row[0]) if source == "mal" else None)}
                for row in rows
            ],
            schema=pa.schema([("source", pa.string()), ("source_id", pa.string()),
                              ("start_year", pa.int64()), ("start_month", pa.int64()),
                              ("start_day", pa.int64()), ("mal_id", pa.int64())]),
        ),
        out,
    )


def _ledger(data_dir, searched_on, rows):
    """What AniList said: (source_key, anilist_id, mal_id)."""
    out = data_dir / "processed" / "anilist_bridge" / f"{searched_on}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"source_key": key, "anilist_id": anilist_id, "mal_id": mal_id,
                 "matched_by": "premiere", "title": key, "searched_on": searched_on}
                for key, anilist_id, mal_id in rows
            ],
            schema=LEDGER_SCHEMA,
        ),
        out,
    )


def _adopted(data_dir):
    path = data_dir / "processed" / OUT_NAME
    if not path.exists():
        return {}
    return {r["source_key"]: r["mal_id"] for r in pq.read_table(path).to_pylist()}


def test_a_row_whose_twin_premiered_the_same_day_is_given_its_mal_id(tmp_path):
    """Zhu Xian Final and Jade Dynasty Final Season, both on 21 August 2026: the
    same show under two names, and no rule in matching.py can see it."""
    _snapshot(tmp_path, "kitsu", "2026-SUMMER", "2026-09-21", [("50936", 2026, 8, 21)])
    _snapshot(tmp_path, "mal", "2026-SUMMER", "2026-09-21", [("62990", 2026, 8, 21)])
    _ledger(tmp_path, "2026-09-22", [("kitsu:50936", 206189, 62990)])

    build_bridge(tmp_path)

    assert _adopted(tmp_path) == {"kitsu:50936": 62990}


def test_a_stale_cross_reference_to_an_earlier_season_is_refused(tmp_path):
    """AniList files Throne of Seal 3 under Throne of Seal 2nd Season's MAL id.
    Adopting it would merge a 2025 series into a 2022 one and delete a title."""
    _snapshot(tmp_path, "kitsu", "2025-SPRING", "2026-09-21", [("50289", 2025, 5, 1)])
    _snapshot(tmp_path, "mal", "2022-FALL", "2026-09-21", [("52684", 2022, 11, 10)])
    _ledger(tmp_path, "2026-09-22", [("kitsu:50289", 185729, 52684)])

    build_bridge(tmp_path)

    assert _adopted(tmp_path) == {}


def test_a_premiere_a_day_apart_is_refused(tmp_path):
    """Santa Tell Me is a day apart across the two sources and probably one
    work, but a window wide enough to bridge it joins a series to its
    compilation film - the reason matching.py keeps it shut."""
    _snapshot(tmp_path, "kitsu", "2024-WINTER", "2026-09-21", [("1", 2023, 12, 4)])
    _snapshot(tmp_path, "mal", "2023-FALL", "2026-09-21", [("57586", 2023, 12, 5)])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 57586)])

    build_bridge(tmp_path)

    assert _adopted(tmp_path) == {}


def test_an_incomplete_premiere_proves_nothing(tmp_path):
    _snapshot(tmp_path, "kitsu", "2026-SUMMER", "2026-09-21", [("1", 2026, None, None)])
    _snapshot(tmp_path, "mal", "2026-SUMMER", "2026-09-21", [("2", 2026, None, None)])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 2)])

    build_bridge(tmp_path)

    assert _adopted(tmp_path) == {}


def test_an_id_no_mal_row_carries_is_not_adopted(tmp_path):
    """There is no merge to verify, and an unverifiable id on a row is one that
    may merge something later for no reason anyone can check."""
    _snapshot(tmp_path, "kitsu", "2026-SUMMER", "2026-09-21", [("1", 2026, 8, 21)])
    _snapshot(tmp_path, "mal", "2026-SUMMER", "2026-09-21", [("999", 2026, 8, 21)])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 62990)])

    build_bridge(tmp_path)

    assert _adopted(tmp_path) == {}


def test_an_id_already_on_rows_that_disagree_is_refused(tmp_path):
    """Kitsu maps Yao Shen Ji 6 (23 April 2022) to the MAL id of Yao Shen Ji 7
    (14 January 2023), so that id already names one catalogue title made of two
    different seasons. Kitsu's own row for season 7 premieres on MAL's exact
    day, and a rule that looked only at MAL's row would let it in - adding a
    correct title to a group that is already wrong."""
    _snapshot(tmp_path, "kitsu", "2023-WINTER", "2026-09-21", [("49158", 2023, 1, 14)])
    _snapshot(tmp_path, "kitsu", "2022-SPRING", "2026-09-21", [("47013", 2022, 4, 23, 54285)])
    _snapshot(tmp_path, "mal", "2023-WINTER", "2026-09-21", [("54285", 2023, 1, 14)])
    _ledger(tmp_path, "2026-09-22", [("kitsu:49158", 900, 54285)])

    build_bridge(tmp_path)

    assert _adopted(tmp_path) == {}


def test_a_search_that_found_nothing_says_nothing(tmp_path):
    _snapshot(tmp_path, "kitsu", "2026-SUMMER", "2026-09-21", [("1", 2026, 8, 21)])
    _snapshot(tmp_path, "mal", "2026-SUMMER", "2026-09-21", [("2", 2026, 8, 21)])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", None, None)])

    assert build_bridge(tmp_path) is None
    assert _adopted(tmp_path) == {}


def test_the_newest_answer_about_a_row_is_the_one_used(tmp_path):
    """A monthly re-search can correct what an earlier one found."""
    _snapshot(tmp_path, "kitsu", "2026-SUMMER", "2026-09-21", [("1", 2026, 8, 21)])
    _snapshot(tmp_path, "mal", "2026-SUMMER", "2026-09-21", [("2", 2026, 8, 21), ("3", 2026, 8, 21)])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 2)])
    _ledger(tmp_path, "2026-11-30", [("kitsu:1", 901, 3)])

    build_bridge(tmp_path)

    assert _adopted(tmp_path) == {"kitsu:1": 3}


def test_a_mapping_whose_evidence_is_gone_does_not_go_on_merging(tmp_path):
    """The file is rebuilt every run, and removed when nothing survives, so a
    stale one cannot keep joining titles after the ledger stops saying so."""
    _snapshot(tmp_path, "kitsu", "2026-SUMMER", "2026-09-21", [("1", 2026, 8, 21)])
    _snapshot(tmp_path, "mal", "2026-SUMMER", "2026-09-21", [("2", 2026, 8, 21)])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 2)])
    build_bridge(tmp_path)

    (tmp_path / "processed" / "anilist_bridge" / "2026-09-22.parquet").unlink()
    build_bridge(tmp_path)

    assert _adopted(tmp_path) == {}


def test_nothing_at_all_is_not_an_error(tmp_path):
    assert build_bridge(tmp_path) is None
