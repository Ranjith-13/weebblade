from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .embed import DIM, embed_texts, text_for_embedding

logger = logging.getLogger(__name__)

TABLE_NAME = "anime_embedding"

# WHERE THE VECTORS LIVE BETWEEN RUNS, and why this module writes to the lake.
#
# warehouse.duckdb is rebuilt from the lake every run, and until this was added
# the vectors were the one thing in it that no parquet backed - a table computed
# here and nowhere else. So any run that wanted to publish a warehouse had to
# embed every title again: 5m30s over 11,989 titles on a CI runner, beside
# build_similar's 4m20s. Measured on the republish of 2026-10-19, 602 of its 721
# seconds were recomputing vectors nothing had changed, and the publish itself
# took six.
#
# That cost is why the warehouse could only be published weekly, and so why the
# daily score series - a feature whose whole claim is that it asks every
# morning - reached readers up to eight days late. Persisted here,
# refresh_catalog materialises the table in about a second, and a run can
# publish with neither a model nor torch installed.
#
# ONE FILE, REPLACED, not the dated glob every other processed output uses. A
# vector is not an observation with a date; it is the current answer for a
# title, and the previous one is of no interest.
#
# WHAT IT COSTS, because it is not free and the bill falls somewhere visible.
# This file lives under processed/, which pipeline.state.KEPT tars whole, so a
# copy rides in every state release and in the off-site mirror. Measured at
# 6,359 titles it is 12 MB of parquet gzipping to 10.5, which scales to about
# 21 MB and 19 compressed over the live 11,992 - a state release going from
# ~53 MB to ~72. Eight releases are kept, so the standing cost is roughly
# 150 MB, against ten minutes a day of CI and a week of staleness for readers.
#
# Float32 vectors barely compress, so that figure will not improve with a
# better codec; it grows with the catalogue. If it ever stops being worth it,
# the fix is to publish the vectors as their own asset and fetch the newest one
# that has them, rather than to recompute them.
LAKE_PATH = Path("processed") / TABLE_NAME / "index.parquet"

_SCHEMA = pa.schema(
    [
        ("key", pa.string()), ("source", pa.string()), ("source_id", pa.string()),
        ("title", pa.string()), ("document", pa.string()),
        ("embedding", pa.list_(pa.float32(), DIM)),
    ]
)


def _cached(path: Path) -> dict[str, tuple[str, list[float]]]:
    """Last run's vectors by key, each with the document it was made from.

    THE DOCUMENT IS WHAT MAKES REUSE SAFE. A vector is only right for the exact
    text it was embedded from, and text_for_embedding's output moves with the
    catalogue: a title gains a studio, a synopsis arrives, a name is corrected,
    the function itself is edited. Comparing the stored document against the one
    just built is the one check that cannot go stale - identical text means the
    vector still stands, and a single character's difference recomputes it.

    Keying on the document rather than on a run date is also what makes this
    survive a change to the embedding text: edit text_for_embedding and every
    document differs, so every vector is rebuilt, with nothing to remember to
    invalidate by hand.

    Any failure here returns nothing and costs a rebuild, which is slow but
    correct. A cache that raises would be worse than no cache at all.
    """
    if not path.exists():
        return {}
    try:
        table = pq.read_table(path, columns=["key", "document", "embedding"])
    except Exception:
        logger.warning("Could not read the vector cache at %s - rebuilding all", path, exc_info=True)
        return {}
    return {
        row["key"]: (row["document"], row["embedding"])
        for row in table.to_pylist()
        if row["key"] and row["embedding"] is not None
    }

# Everything text_for_embedding can say about a title. The columns beyond title
# and synopsis are what an entry with no synopsis has instead of nothing.
# Whichever of them the view actually has: a warehouse built from a snapshot
# older than a column does not have it, and an index of names is better than no
# index at all.
_WANTED = (
    "source", "source_id", "title_english", "title_romaji", "genres", "synopsis",
    "format", "season", "season_year", "studios", "source_material",
)


def _select_for_index(con: duckdb.DuckDBPyConnection) -> str:
    columns = {row[0] for row in con.execute("DESCRIBE anime_media_latest").fetchall()}
    return f"SELECT {', '.join(c for c in _WANTED if c in columns)} FROM anime_media_latest"


def build_index(db_path: Path, data_dir: Path | None = None) -> int:
    """(Re)build the vector index the API searches - a table in the warehouse.

    It used to be a Chroma collection in a directory of its own. Measured against
    it on the same 6,349 titles, DuckDB answers the same twelve vague queries
    with the same twelve genre matches (100 of 120 top-ten results on-genre) and
    finds a title typed under its other name slightly more often (English 31/40
    against 30/40 first-hit, 40/40 against 38/40 in the top five), because this
    searches every vector exactly where Chroma approximates. It costs 33 ms a
    query instead of 11, which is nothing beside a network round trip, and the
    index went from a 286 MB directory to 9.8 MB inside the warehouse file.

    That it lives IN the warehouse is the point. One file is the whole serving
    layer: the catalogue and the vectors are built in the same run, so a search
    result can never name a title the catalogue has since merged away, and the
    API needs one artifact rather than a file plus a directory plus the code to
    keep them in step.

    Embeddings are computed before the database is touched at all, so a failure
    anywhere in the slow part leaves the old index serving. That lesson is from
    the Chroma version, which once deleted the live collection and then failed to
    write the new one, leaving search answering every query with nothing.

    Returns 0 (rather than raising) where there is nothing to index yet - no
    warehouse file, or no anime_media_latest - which is a legitimate state
    whenever every source has failed on a run, not just before the first one.

    WITH data_dir IT ALSO READS AND WRITES THE LAKE, which is what lets a later
    run rebuild the warehouse without a model. Only the titles whose document
    has changed are embedded; see LAKE_PATH and _cached above for why the
    document, and not a date, is what decides. Without data_dir the behaviour is
    exactly what it was: embed everything, write one table, touch no files.
    """
    if not db_path.exists():
        logger.warning("Warehouse file %s doesn't exist yet - nothing to index", db_path)
        return 0

    con = duckdb.connect(str(db_path))
    try:
        try:
            rows: list[dict[str, Any]] = (
                con.execute(_select_for_index(con)).fetch_arrow_table().to_pylist()
            )
        except duckdb.CatalogException:
            logger.warning("anime_media_latest view doesn't exist yet - nothing to index")
            return 0

        if not rows:
            logger.warning("No data in anime_media_latest - nothing to index")
            return 0

        documents = [text_for_embedding(row) for row in rows]
        keys = [f"{row['source']}:{row['source_id']}" for row in rows]

        # Reuse before compute. A title whose document is unchanged keeps the
        # vector it already had, so a week that adds forty titles embeds forty
        # rather than twelve thousand.
        cache = _cached(data_dir / LAKE_PATH) if data_dir else {}
        stale = [i for i, key in enumerate(keys) if cache.get(key, (None, None))[0] != documents[i]]
        computed = dict(zip(stale, embed_texts([documents[i] for i in stale]))) if stale else {}
        vectors = [
            computed[i] if i in computed else cache[keys[i]][1] for i in range(len(keys))
        ]
        logger.info(
            "Vectors: %s embedded, %s reused from %s",
            len(stale), len(keys) - len(stale), data_dir / LAKE_PATH if data_dir else "nothing",
        )

        table = pa.Table.from_pylist(
            [
                {
                    "key": key,
                    "source": row["source"],
                    "source_id": str(row["source_id"]),
                    "title": row["title_english"] or row["title_romaji"] or "Untitled",
                    "document": document,
                    "embedding": vector,
                }
                for key, row, document, vector in zip(keys, rows, documents, vectors)
            ],
            schema=_SCHEMA,
        )

        # A fixed-size ARRAY, not a LIST: array_cosine_similarity only takes the
        # former, and Arrow's fixed-size list arrives as the latter without this.
        con.register("_new_embeddings", table)
        con.execute(
            f"CREATE OR REPLACE TABLE {TABLE_NAME} AS "
            f"SELECT key, source, source_id, title, document, embedding::FLOAT[{DIM}] AS embedding "
            "FROM _new_embeddings"
        )
        con.unregister("_new_embeddings")
    finally:
        con.close()

    # AFTER the table, and best-effort. The serving artifact is the table; this
    # is next run's shortcut, so a failure to write it costs a rebuild rather
    # than this run's index. Nothing downstream may assume the file is here -
    # a publish that needs the vectors checks the TABLE, not this (see the
    # daily workflow's artifact check).
    if data_dir is not None:
        try:
            path = data_dir / LAKE_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            staged = path.with_suffix(".parquet.part")
            pq.write_table(table, staged)
            staged.replace(path)
            logger.info("Persisted %s vectors to %s", table.num_rows, path)
        except Exception:
            logger.warning("Could not persist vectors to the lake", exc_info=True)

    logger.info("Indexed %s titles into %s", len(rows), TABLE_NAME)
    return len(rows)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=Path("data/warehouse.duckdb"))
    args = parser.parse_args()

    print(f"Indexed {build_index(args.db_path)} titles")
