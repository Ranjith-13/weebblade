from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb

from .embed import embed_texts, text_for_embedding

logger = logging.getLogger(__name__)

COLLECTION_NAME = "anime_media"

_SELECT_FOR_INDEX = """
    SELECT source, source_id, title_english, title_romaji, genres, synopsis
    FROM anime_media_latest
"""


def build_index(db_path: Path, chroma_dir: Path) -> int:
    """(Re)build the Chroma collection used for semantic "find similar titles" search.

    Reads from anime_media_latest (one row per title, not per weekly run - see
    processing/duckdb_catalog.py) so re-running this doesn't index the same title
    multiple times once a few weeks of data have accumulated.
    """
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows: list[dict[str, Any]] = con.execute(_SELECT_FOR_INDEX).fetch_arrow_table().to_pylist()
    finally:
        con.close()

    if not rows:
        logger.warning("No data in anime_media_latest - nothing to index")
        return 0

    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_dir))
    existing_names = {c.name for c in client.list_collections()}
    if COLLECTION_NAME in existing_names:
        client.delete_collection(COLLECTION_NAME)  # full rebuild, not an incremental upsert
    collection = client.create_collection(COLLECTION_NAME)

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

    collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    logger.info("Indexed %s titles into Chroma collection '%s'", len(ids), COLLECTION_NAME)
    return len(ids)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=Path("data/warehouse.duckdb"))
    parser.add_argument("--chroma-dir", type=Path, default=Path("data/chroma"))
    args = parser.parse_args()

    count = build_index(args.db_path, args.chroma_dir)
    print(f"Indexed {count} titles")
