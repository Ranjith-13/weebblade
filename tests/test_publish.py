"""Making the warehouse portable: processing/publish.py."""

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ai.search.embed import DIM
from processing.duckdb_catalog import refresh_catalog
from processing.publish import materialise


@pytest.fixture
def warehouse(tmp_path):
    """A warehouse of views over a small lake, with vectors beside them."""
    rows = [
        {"source": "kitsu", "source_id": str(i), "title_english": f"Title {i}",
         "season": "FALL", "season_year": 2026, "status": "current", "run_date": "2026-10-11"}
        for i in range(5)
    ]
    path = (tmp_path / "data" / "processed" / "anime_media_consolidated" / "_catalogue"
            / "2026-10-11" / "p.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)

    db = tmp_path / "data" / "warehouse.duckdb"
    refresh_catalog(tmp_path / "data", db)

    con = duckdb.connect(str(db))
    con.execute(
        f"CREATE TABLE anime_embedding (key VARCHAR, source VARCHAR, source_id VARCHAR, "
        f"title VARCHAR, document VARCHAR, embedding FLOAT[{DIM}])"
    )
    con.execute(
        "INSERT INTO anime_embedding VALUES ('kitsu:1', 'kitsu', '1', 'Title 1', '', ?)",
        [[1.0] + [0.0] * (DIM - 1)],
    )
    con.close()
    return tmp_path / "data", db


def test_the_copy_works_with_the_lake_deleted(warehouse, tmp_path):
    """The whole point. The views carry the absolute path of every parquet file,
    so the original answers nothing once the lake is gone - and does it by
    returning no rows rather than erroring."""
    data, db = warehouse
    out = materialise(db, tmp_path / "published" / "warehouse.duckdb")

    for parquet in (data / "processed").rglob("*.parquet"):
        parquet.unlink()

    con = duckdb.connect(str(out), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM anime_media_latest").fetchone()[0] == 5
    finally:
        con.close()

    original = duckdb.connect(str(db), read_only=True)
    try:
        with pytest.raises(duckdb.IOException):
            original.execute("SELECT count(*) FROM anime_media_latest").fetchone()
    finally:
        original.close()


def test_views_become_tables(warehouse, tmp_path):
    _, db = warehouse
    out = materialise(db, tmp_path / "warehouse.duckdb")

    con = duckdb.connect(str(out), read_only=True)
    try:
        kinds = dict(con.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall())
    finally:
        con.close()

    assert kinds["anime_media_latest"] == "BASE TABLE"
    assert set(kinds) >= {"anime_media", "anime_media_latest", "anime_embedding"}


def test_the_vectors_keep_the_type_similarity_needs(warehouse, tmp_path):
    """A fixed-size ARRAY, not a LIST: array_cosine_similarity takes only the
    former, and search is the one thing that would break silently."""
    _, db = warehouse
    out = materialise(db, tmp_path / "warehouse.duckdb")

    con = duckdb.connect(str(out), read_only=True)
    try:
        kind = con.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'anime_embedding' AND column_name = 'embedding'"
        ).fetchone()[0]
        nearest = con.execute(
            f"SELECT key FROM anime_embedding "
            f"ORDER BY array_cosine_similarity(embedding, ?::FLOAT[{DIM}]) DESC LIMIT 1",
            [[1.0] + [0.0] * (DIM - 1)],
        ).fetchone()[0]
    finally:
        con.close()

    assert kind == f"FLOAT[{DIM}]"
    assert nearest == "kitsu:1"


def test_nothing_to_publish_is_not_an_error(tmp_path):
    assert materialise(tmp_path / "missing.duckdb", tmp_path / "out.duckdb") is None


def test_publishing_twice_replaces_the_previous_file(warehouse, tmp_path):
    _, db = warehouse
    out = tmp_path / "warehouse.duckdb"
    materialise(db, out)
    first = out.stat().st_size

    materialise(db, out)

    assert out.stat().st_size == first  # replaced, not appended to
