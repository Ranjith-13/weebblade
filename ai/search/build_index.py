from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb

from .embed import embed_texts, text_for_embedding

logger = logging.getLogger(__name__)

COLLECTION_NAME = "anime_media"

# The new index is built here and renamed into place only once it is complete.
_BUILDING = f"{COLLECTION_NAME}__building"

# Chroma refuses an add larger than its max batch size (5,461 on the server's
# build). Used only if the client cannot say.
_FALLBACK_BATCH = 1000

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


def build_index(db_path: Path, chroma_dir: Path) -> int:
    """(Re)build the Chroma collection used for semantic "find similar titles" search.

    Reads from anime_media_latest (one row per title, not per weekly run - see
    processing/duckdb_catalog.py) so re-running this doesn't index the same title
    multiple times once a few weeks of data have accumulated.

    Returns 0 (rather than raising) if the warehouse file or the anime_media_latest
    view don't exist yet - a legitimate state whenever every source has failed on a
    given run, not just before the very first successful one.
    """
    if not db_path.exists():
        logger.warning("Warehouse file %s doesn't exist yet - nothing to index", db_path)
        return 0

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows: list[dict[str, Any]] = (
            con.execute(_select_for_index(con)).fetch_arrow_table().to_pylist()
        )
    except duckdb.CatalogException:
        logger.warning("anime_media_latest view doesn't exist yet - nothing to index")
        return 0
    finally:
        con.close()

    if not rows:
        logger.warning("No data in anime_media_latest - nothing to index")
        return 0

    from .client import get_chroma_client

    ids = [f"{row['source']}:{row['source_id']}" for row in rows]
    documents = [text_for_embedding(row) for row in rows]
    embeddings = embed_texts(documents)
    metadatas = [
        {
            "source": row["source"],
            "source_id": str(row["source_id"]),
            "title": row["title_english"] or row["title_romaji"] or "Untitled",
        }
        for row in rows
    ]

    # A full rebuild, built BESIDE the live collection and swapped in at the end.
    # This used to delete the live collection first and then add every title in
    # one call - and when the backfill took the catalogue to 6,055 titles, past
    # Chroma's 5,461 batch limit, the add failed after the delete and live search
    # answered every query with nothing. Now a failure anywhere before the swap
    # leaves the old index serving, and the add goes in batches the client allows.
    client = get_chroma_client(chroma_dir)
    names = {getattr(c, "name", c) for c in client.list_collections()}
    if _BUILDING in names:
        client.delete_collection(_BUILDING)  # left over from a build that died
    building = client.create_collection(_BUILDING)

    batch = _batch_size(client)
    for start in range(0, len(ids), batch):
        end = start + batch
        building.add(
            ids=ids[start:end],
            embeddings=embeddings[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )

    if COLLECTION_NAME in names:
        client.delete_collection(COLLECTION_NAME)
    building.modify(name=COLLECTION_NAME)
    logger.info("Indexed %s titles into Chroma collection '%s'", len(ids), COLLECTION_NAME)
    return len(ids)


def _batch_size(client: Any) -> int:
    get = getattr(client, "get_max_batch_size", None)
    try:
        return max(1, int(get())) if get else _FALLBACK_BATCH
    except Exception:  # an older or stricter client - the fallback is always safe
        return _FALLBACK_BATCH


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=Path("data/warehouse.duckdb"))
    parser.add_argument("--chroma-dir", type=Path, default=Path("data/chroma"))
    args = parser.parse_args()

    count = build_index(args.db_path, args.chroma_dir)
    print(f"Indexed {count} titles")
