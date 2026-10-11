from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from .build_index import TABLE_NAME
from .embed import DIM, embed_texts

# Nearest first, decorated in the same pass. Chroma could only return what it
# stored, so a match had to be looked up in the warehouse afterwards - and when a
# later merge changed which source row won a title, the stored key was no longer
# a row in anime_media_latest and the result came back undecorated unless it was
# chased through the identity registry. The vectors live in the warehouse now and
# are rebuilt with it, so the join cannot miss and that whole path is gone.
#
# Distance rather than similarity, because that is what the API has always
# returned and what a client sorts on: 0 is the same text, 2 is its opposite.
_SEARCH = f"""
    SELECT e.source, e.source_id, e.title,
           1 - array_cosine_similarity(e.embedding, ?::FLOAT[{DIM}]) AS distance,
           m.wb_id, m.poster_url, m.score_100, m.format, m.status
    FROM {TABLE_NAME} e
    LEFT JOIN anime_media_latest m ON m.source = e.source AND m.source_id = e.source_id
    ORDER BY distance
    LIMIT ?
"""


def find_similar(
    con: duckdb.DuckDBPyConnection, query_text: str, n_results: int = 10
) -> list[dict[str, Any]]:
    """Embed a free-text query - a title, a vibe, a description - and return the
    most semantically similar titles, nearest first, each already carrying what a
    client needs to draw it.

    Takes a connection rather than a path: the API already holds one per request,
    and opening the warehouse twice to answer one question is both slower and a
    second chance to fail.
    """
    [query_embedding] = embed_texts([query_text])
    return con.execute(_SEARCH, [query_embedding, n_results]).fetch_arrow_table().to_pylist()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="A title or free-text description to search for")
    parser.add_argument("--db-path", type=Path, default=Path("data/warehouse.duckdb"))
    parser.add_argument("-n", "--n-results", type=int, default=10)
    args = parser.parse_args()

    con = duckdb.connect(str(args.db_path), read_only=True)
    try:
        for rank, match in enumerate(find_similar(con, args.query, args.n_results), 1):
            print(f"{rank}. {match['title']} (distance={match['distance']:.4f}, "
                  f"source={match['source']})")
    finally:
        con.close()
