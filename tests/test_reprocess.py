"""Re-running a transform over stored raw responses."""

import json

import pyarrow.parquet as pq
import pytest

from ingestion.reprocess import reprocess


def _raw(data_dir, source, partition, run_date, items):
    path = data_dir / "raw" / source / partition / f"{run_date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items))


def _flatten(tag):
    def flatten(m):
        return {"source": "mal", "source_id": m["id"], "genres": [tag], "average_score": 70.0}
    return flatten


def test_every_stored_snapshot_is_rebuilt_under_its_own_partition_and_date(tmp_path):
    """A fix belongs in every season stored, not only those fetched after it
    shipped - and the snapshot keeps its capture date, so it means what it did."""
    _raw(tmp_path, "mal", "2024-FALL", "2026-09-10", [{"id": "1"}, {"id": "2"}])
    _raw(tmp_path, "mal", "2026-SUMMER", "2026-09-09", [{"id": "3"}])

    done = reprocess("mal", tmp_path, flatteners={"mal": _flatten("Science Fiction")})

    assert [(d.partition, d.run_date, d.rows) for d in done] == [
        ("2024-FALL", "2026-09-10", 2),
        ("2026-SUMMER", "2026-09-09", 1),
    ]
    rebuilt = pq.read_table(tmp_path / "processed" / "mal_media" / "2024-FALL" / "2026-09-10.parquet")
    assert rebuilt.column("genres").to_pylist() == [["Science Fiction"], ["Science Fiction"]]


def test_the_new_transform_replaces_what_the_old_one_wrote(tmp_path):
    _raw(tmp_path, "mal", "2024-FALL", "2026-09-10", [{"id": "1"}])
    reprocess("mal", tmp_path, flatteners={"mal": _flatten("Sci-Fi")})

    reprocess("mal", tmp_path, flatteners={"mal": _flatten("Science Fiction")})

    snap = tmp_path / "processed" / "mal_media" / "2024-FALL" / "2026-09-10.parquet"
    assert pq.read_table(snap).column("genres").to_pylist() == [["Science Fiction"]]


def test_a_transform_that_produces_bad_rows_leaves_the_old_snapshot_alone(tmp_path):
    """Validated before it replaces anything. A reprocess that breaks the scale
    must not overwrite a good snapshot with a broken one."""
    _raw(tmp_path, "mal", "2024-FALL", "2026-09-10", [{"id": str(i)} for i in range(30)])
    reprocess("mal", tmp_path, flatteners={"mal": _flatten("Drama")})
    snap = tmp_path / "processed" / "mal_media" / "2024-FALL" / "2026-09-10.parquet"
    before = pq.read_table(snap).to_pylist()

    broken = lambda m: {"source": "mal", "source_id": m["id"], "average_score": 8.1}  # noqa: E731
    done = reprocess("mal", tmp_path, flatteners={"mal": broken})

    assert done[0].error and "0-10 scale" in done[0].error
    assert pq.read_table(snap).to_pylist() == before


def test_the_raw_responses_are_never_modified(tmp_path):
    _raw(tmp_path, "mal", "2024-FALL", "2026-09-10", [{"id": "1"}])
    raw = tmp_path / "raw" / "mal" / "2024-FALL" / "2026-09-10.json"
    original = raw.read_text()

    reprocess("mal", tmp_path, flatteners={"mal": _flatten("Drama")})

    assert raw.read_text() == original


def test_a_dry_run_writes_nothing(tmp_path):
    _raw(tmp_path, "mal", "2024-FALL", "2026-09-10", [{"id": "1"}])

    done = reprocess("mal", tmp_path, dry_run=True, flatteners={"mal": _flatten("Drama")})

    assert done[0].rows == 1
    assert not (tmp_path / "processed").exists()


def test_a_source_with_no_transform_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no transform"):
        reprocess("anilist", tmp_path, flatteners={"mal": _flatten("x")})
