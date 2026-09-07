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
    data_dir = tmp_path / "data"
    db_path = tmp_path / "warehouse.duckdb"

    created = refresh_catalog(data_dir, db_path)

    assert created == []
