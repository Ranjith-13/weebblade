from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from .embed import DIM, embed_texts, text_for_embedding

logger = logging.getLogger(__name__)

TABLE_NAME = "anime_embedding"

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


def build_index(db_path: Path) -> int:
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
        vectors = embed_texts(documents)

        table = pa.Table.from_pylist(
            [
                {
                    "key": f"{row['source']}:{row['source_id']}",
                    "source": row["source"],
                    "source_id": str(row["source_id"]),
                    "title": row["title_english"] or row["title_romaji"] or "Untitled",
                    "document": document,
                    "embedding": vector,
                }
                for row, document, vector in zip(rows, documents, vectors)
            ],
            schema=pa.schema(
                [
                    ("key", pa.string()), ("source", pa.string()), ("source_id", pa.string()),
                    ("title", pa.string()), ("document", pa.string()),
                    ("embedding", pa.list_(pa.float32(), DIM)),
                ]
            ),
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

    logger.info("Indexed %s titles into %s", len(rows), TABLE_NAME)
    return len(rows)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=Path("data/warehouse.duckdb"))
    args = parser.parse_args()

    print(f"Indexed {build_index(args.db_path)} titles")
