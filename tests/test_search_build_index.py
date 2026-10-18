"""The vector index: a table in the warehouse, beside the titles it indexes."""

from pathlib import Path

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
        # Asked with a vector read back out of the table, because a vector is
        # nearest to itself whatever else is in there. Picking a row by position
        # and asserting which axis it got does not survive CI: the warehouse scan
        # has no defined row order, and 1.1.3 hands the titles over in the other
        # one, so each gets the other's vector.
        key, vector = con.execute(f"SELECT key, embedding FROM {TABLE_NAME} LIMIT 1").fetchone()
        nearest = con.execute(
            f"SELECT key FROM {TABLE_NAME} "
            f"ORDER BY array_cosine_similarity(embedding, ?::FLOAT[{DIM}]) DESC LIMIT 1",
            [list(vector)],
        ).fetchone()[0]
    finally:
        con.close()

    assert kind == f"FLOAT[{DIM}]"
    assert nearest == key


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


# THE VECTORS SURVIVE A WAREHOUSE REBUILD
#
# warehouse.duckdb is rebuilt from the lake every run, and the vectors used to
# be the one thing in it no parquet backed - so any run that wanted to publish
# had to embed every title again. Measured on the republish of 2026-10-19, 602
# of 721 seconds were recomputing vectors nothing had changed, while the publish
# itself took six. That cost is why the warehouse was only published weekly, and
# so why the daily score series reached readers up to eight days late.
#
# These guard the two halves of the fix: that a build writes the lake, and that
# refresh_catalog can restore a USABLE table from it without a model. Usable is
# the word doing the work - see the cast test below.


def _counting(calls):
    def embed(docs):
        calls.append(list(docs))
        return [[1.0 if j == i else 0.0 for j in range(DIM)] for i, _ in enumerate(docs)]
    return embed


def test_a_build_persists_its_vectors_to_the_lake(warehouse, tmp_path):
    db = warehouse(3)

    build_index(db, data_dir=tmp_path / "data")

    persisted = pq.read_table(tmp_path / "data" / build_module.LAKE_PATH)
    assert persisted.num_rows == 3
    assert set(persisted.column_names) >= {"key", "document", "embedding"}


def test_refresh_catalog_restores_the_index_without_a_model(warehouse, tmp_path):
    """The point of the whole change: a run with no embedding model installed
    can rebuild the warehouse and still serve search."""
    data = tmp_path / "data"
    db = warehouse(3)
    build_index(db, data_dir=data)
    db.unlink()  # exactly what a fresh runner starts from

    created = refresh_catalog(data, db)

    assert TABLE_NAME in created
    con = duckdb.connect(str(db), read_only=True)
    try:
        assert con.execute(f"SELECT count(*) FROM {TABLE_NAME}").fetchone()[0] == 3
    finally:
        con.close()


def test_a_restored_vector_can_actually_be_searched(warehouse, tmp_path):
    """THE ONE THAT MATTERS. A vector read back out of parquet is a LIST, and
    array_cosine_similarity takes only a fixed-size ARRAY - restored without the
    cast the table looks perfectly healthy and every query raises
    BinderException. Checked by ranking, not by reading the type.

    The probe is taken FROM the table rather than built here, because a vector
    is nearest to itself whatever else is in the index. The first version of
    this asked for the stub's second axis and expected kitsu:1, which assumed
    anime_media_latest hands its rows back in key order - the stub assigns an
    axis per position in the batch, so the title holding axis 1 is whichever one
    came second. It does on DuckDB 1.5.6 and does not on the pinned 1.1.3, so
    the test passed here and failed in CI.
    """
    data = tmp_path / "data"
    db = warehouse(3)
    build_index(db, data_dir=data)
    db.unlink()
    refresh_catalog(data, db)

    con = duckdb.connect(str(db), read_only=True)
    try:
        key, probe = con.execute(f"SELECT key, embedding FROM {TABLE_NAME} LIMIT 1").fetchone()
        best = con.execute(
            f"SELECT key FROM {TABLE_NAME} "
            f"ORDER BY array_cosine_similarity(embedding, ?::FLOAT[{DIM}]) DESC LIMIT 1",
            [probe],
        ).fetchone()
    finally:
        con.close()
    assert best[0] == key


def test_an_unchanged_title_is_not_embedded_again(warehouse, tmp_path):
    data = tmp_path / "data"
    build_index(warehouse(3), data_dir=data)

    calls = []
    build_index(warehouse(3, embed=_counting(calls)), data_dir=data)

    assert calls == [] or calls == [[]], f"nothing changed, yet {calls} reached the model"


def test_only_a_title_whose_document_changed_is_embedded_again(warehouse, tmp_path, monkeypatch):
    """The document, not a date, is what decides: a vector is only right for the
    exact text it was made from, so the stored text is compared to the new one.

    The patch wraps the real text_for_embedding rather than replacing it, so the
    two untouched titles produce byte-identical documents and only the third is
    seen to have moved. Replacing it outright invalidates all three, which is
    the next test."""
    data = tmp_path / "data"
    build_index(warehouse(3), data_dir=data)

    real = build_module.text_for_embedding
    monkeypatch.setattr(
        build_module, "text_for_embedding",
        lambda row: real(row) + (" now with a sequel" if row["source_id"] == "1" else ""),
    )
    calls = []
    build_index(warehouse(3, embed=_counting(calls)), data_dir=data)

    assert len(calls) == 1 and len(calls[0]) == 1, f"one title moved, {calls} were embedded"
    assert calls[0][0].endswith(" now with a sequel")


def test_editing_the_document_rebuilds_every_vector(warehouse, tmp_path, monkeypatch):
    """The other half of keying on the document, and the reason there is no
    version to bump. Change what goes into an embedding and every stored
    document differs, so every vector is recomputed - with nothing to remember
    to invalidate by hand, and no way to leave the index half built from two
    different notions of what a title's text is."""
    data = tmp_path / "data"
    build_index(warehouse(3), data_dir=data)

    monkeypatch.setattr(build_module, "text_for_embedding", lambda row: f"rewritten {row['source_id']}")
    calls = []
    build_index(warehouse(3, embed=_counting(calls)), data_dir=data)

    # Sorted: what is being asserted is that all three were re-embedded, not the
    # order anime_media_latest happens to return them in, which is not promised
    # and differs between DuckDB versions.
    assert len(calls) == 1
    assert sorted(calls[0]) == ["rewritten 0", "rewritten 1", "rewritten 2"]


def test_a_title_that_left_the_catalogue_leaves_the_index(warehouse, tmp_path):
    data = tmp_path / "data"
    build_index(warehouse(4), data_dir=data)

    build_index(warehouse(2), data_dir=data)

    assert [key for key, _ in _indexed(warehouse(2))] == ["kitsu:0", "kitsu:1"]
    assert pq.read_table(data / build_module.LAKE_PATH).num_rows == 2


def test_an_unreadable_cache_costs_a_rebuild_rather_than_the_index(warehouse, tmp_path):
    """A cache that raises would be worse than no cache. Corrupt it and the run
    embeds everything again, which is slow and correct."""
    data = tmp_path / "data"
    build_index(warehouse(3), data_dir=data)
    (data / build_module.LAKE_PATH).write_bytes(b"not a parquet file")

    calls = []
    build_index(warehouse(3, embed=_counting(calls)), data_dir=data)

    assert len(calls[0]) == 3
    assert len(_indexed(warehouse(3))) == 3


def test_refresh_catalog_does_not_invent_an_empty_index(tmp_path):
    """A missing file is skipped, never fabricated empty: an empty
    anime_embedding publishes an API whose every search answers nothing while
    looking entirely healthy."""
    db = tmp_path / "warehouse.duckdb"

    created = refresh_catalog(tmp_path / "data", db)

    assert TABLE_NAME not in created
    con = duckdb.connect(str(db), read_only=True)
    try:
        with pytest.raises(duckdb.CatalogException):
            con.execute(f"SELECT count(*) FROM {TABLE_NAME}").fetchone()
    finally:
        con.close()


def test_restoring_the_index_needs_no_embedding_library(warehouse, tmp_path):
    """THE CLAIM THE DAILY PUBLISH RESTS ON. That job installs duckdb, pyarrow
    and requests - no model, no torch, no onnxruntime - and must still produce a
    warehouse whose search works. Run in a subprocess with every embedding
    package made unimportable, because this process has already imported them
    and so could never notice the dependency returning.

    What it catches is a restore path that reaches for a model: a lazy import
    fired inside refresh_catalog, a re-embed smuggled into the rebuild. What it
    does NOT catch is merely importing ai.search.embed, which loads nothing at
    module level and is harmless on a bare runner - the reason that module is
    still not imported there is layering, not packaging.
    """
    import subprocess
    import sys
    import textwrap

    data = tmp_path / "data"
    db = warehouse(3)
    build_index(db, data_dir=data)
    db.unlink()

    script = textwrap.dedent("""
        import sys, importlib.abc
        from pathlib import Path

        BLOCKED = {"fastembed", "onnxruntime", "torch", "sentence_transformers", "transformers"}

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCKED:
                    raise ImportError(name + " is not installed on this runner")
                return None

        sys.meta_path.insert(0, Blocker())
        repo, data, db, table = sys.argv[1:]
        sys.path.insert(0, repo)

        import duckdb
        from processing.duckdb_catalog import refresh_catalog

        refresh_catalog(Path(data), Path(db))
        con = duckdb.connect(db, read_only=True)
        width = con.execute(f"SELECT len(embedding) FROM {table} LIMIT 1").fetchone()[0]
        probe = con.execute(f"SELECT embedding FROM {table} LIMIT 1").fetchone()[0]
        # Ranked, not merely counted: the cast is what a search actually needs,
        # and a table restored without it counts perfectly and ranks not at all.
        con.execute(
            f"SELECT key FROM {table} "
            f"ORDER BY array_cosine_similarity(embedding, ?::FLOAT[{width}]) DESC LIMIT 1",
            [probe],
        ).fetchone()
        print(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    """)
    done = subprocess.run(
        [sys.executable, "-c", script,
         str(Path(__file__).resolve().parent.parent), str(data), str(db), TABLE_NAME],
        capture_output=True, text=True,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().endswith("3")
