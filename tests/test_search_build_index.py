"""The vector index: a table in the warehouse, beside the titles it indexes."""

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import ai.search.build_index as build_module
from ai.search.build_index import TABLE_NAME, build_index
from ai.search.embed import DIM
from processing.duckdb_catalog import refresh_catalog


def test_build_index_handles_missing_warehouse_file(tmp_path):
    assert build_index(tmp_path / "does-not-exist.duckdb") == 0


def test_build_index_handles_missing_view(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(tmp_path / "data", db_path)

    assert build_index(db_path) == 0


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    """A warehouse of `n` titles, with the model stubbed: what is under test is
    what gets written, not what the model returns."""

    def build(n: int, embed=None):
        rows = [
            {"source": "kitsu", "source_id": str(i), "title_english": f"Title {i}",
             "title_romaji": None, "genres": ["Drama"], "synopsis": "A story.",
             "run_date": "2026-09-11"}
            for i in range(n)
        ]
        path = (tmp_path / "data" / "processed" / "anime_media_consolidated" / "_catalogue"
                / "2026-09-11" / "p.parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path)
        db_path = tmp_path / "warehouse.duckdb"
        refresh_catalog(tmp_path / "data", db_path)
        monkeypatch.setattr(
            build_module, "embed_texts",
            # One axis each, never a zero vector: cosine similarity against zero
            # is undefined, and DuckDB 1.1.3 sorts that NaN to the front where
            # 1.5.6 sorts it to the back. CI found that; the laptop could not.
            embed or (lambda docs: [[1.0 if j == i else 0.0 for j in range(DIM)]
                                    for i, _ in enumerate(docs)]),
        )
        return db_path

    return build


def _indexed(db_path):
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return con.execute(f"SELECT key, title FROM {TABLE_NAME} ORDER BY key").fetchall()
    finally:
        con.close()


def test_every_title_is_indexed_under_its_own_key(warehouse):
    db = warehouse(4)

    assert build_index(db) == 4
    assert [key for key, _ in _indexed(db)] == [f"kitsu:{i}" for i in range(4)]


def test_the_vectors_are_an_array_the_similarity_function_accepts(warehouse):
    """A fixed-size ARRAY, not a LIST. array_cosine_similarity takes only the
    former, and Arrow's fixed-size list arrives as the latter without the cast -
    which fails at query time, not here, so it is worth asserting here."""
    db = warehouse(2)
    build_index(db)

    con = duckdb.connect(str(db), read_only=True)
    try:
        kind = con.execute(
            f"SELECT data_type FROM information_schema.columns "
            f"WHERE table_name = '{TABLE_NAME}' AND column_name = 'embedding'"
        ).fetchone()[0]
        nearest = con.execute(
            f"SELECT key FROM {TABLE_NAME} "
            f"ORDER BY array_cosine_similarity(embedding, ?::FLOAT[{DIM}]) DESC LIMIT 1",
            [[0.0, 1.0] + [0.0] * (DIM - 2)],
        ).fetchone()[0]
    finally:
        con.close()

    assert kind == f"FLOAT[{DIM}]"
    assert nearest == "kitsu:1"  # the only row whose vector points down that axis


def test_a_rebuild_replaces_the_previous_index(warehouse):
    db = warehouse(4)
    build_index(db)

    con = duckdb.connect(str(db))
    con.execute(f"INSERT INTO {TABLE_NAME} SELECT 'kitsu:stale', 'kitsu', 'stale', 'Stale', '', "
                f"embedding FROM {TABLE_NAME} LIMIT 1")
    con.close()

    build_index(db)

    assert [key for key, _ in _indexed(db)] == [f"kitsu:{i}" for i in range(4)]


def test_a_failed_rebuild_leaves_the_live_index_serving(warehouse):
    """The Chroma version once deleted the live collection and then failed to
    write the new one, so search answered every query with nothing. Embedding
    happens before the database is touched at all, so the old table survives
    whatever goes wrong in the slow part."""
    db = warehouse(4)
    build_index(db)

    def refuse(docs):
        raise RuntimeError("the model fell over")

    with pytest.raises(RuntimeError):
        build_index(warehouse(4, embed=refuse))

    assert [key for key, _ in _indexed(db)] == [f"kitsu:{i}" for i in range(4)]
