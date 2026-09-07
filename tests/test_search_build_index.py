from pathlib import Path

from ai.search.build_index import build_index
from processing.duckdb_catalog import refresh_catalog


def test_build_index_handles_missing_warehouse_file(tmp_path):
    count = build_index(tmp_path / "does-not-exist.duckdb", tmp_path / "chroma")

    assert count == 0


def test_build_index_handles_missing_view(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(tmp_path / "data", db_path)

    count = build_index(db_path, tmp_path / "chroma")

    assert count == 0
