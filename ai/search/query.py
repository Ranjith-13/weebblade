from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from .build_index import TABLE_NAME
from .embed import DIM, embed_query

# Nearest first, decorated in the same pass. Chroma could only return what it
# stored, so a match had to be looked up in the warehouse afterwards - and when a
# later merge changed which source row won a title, the stored key was no longer
# a row in anime_media_latest and the result came back undecorated unless it was
# chased through the identity registry. The vectors live in the warehouse now and
# are rebuilt with it, so the join cannot miss and that whole path is gone.
#
# Distance rather than similarity, because that is what the API has always
# returned and what a client sorts on: 0 is the same text, 2 is its opposite.
#
# A TITLE TYPED IN IS NOT A SEMANTIC QUESTION, and the vector index treats it as
# one. Measured over the 40 most-held titles (ai/search/evaluate.py), searching
# each by its romaji put the right one first 10 times - while finding it inside
# the top ten 28 times. So they were not missing, they were losing: the failures
# are franchises whose documents are near-identical - four Attack on Titan
# entries, three Demon Slayer arcs - and cosine distance cannot separate them.
#
# So a name match sorts ahead of distance. One ORDER BY term rather than a second
# index or a rank fusion, and it cannot disturb a vague query: "a quiet show
# about cooking" equals no title's name, every row scores the same, and the
# ordering is the distance ordering it has always been. Measured both ways on the
# live catalogue, on-genre was 92/120 before and 92/120 after.
#
# BOTH SIDES ARE NORMALISED THE SAME WAY, and that is most of the gain. Compared
# as stored, lower-cased only, the rule fires for titles that happen to carry no
# punctuation and misses every one that does - which is every franchise entry,
# the rows it exists for. Typed loosely, first-hits went 10/40 to 23/40 that way
# and to 40/40 once a colon stopped mattering.
#
# Letters and numbers of ANY script survive; everything else becomes a space.
# \pL and \pN rather than a-z0-9, or the normaliser would delete a Japanese query
# outright and take native matching with it.
#
# WHAT THIS DOES NOT DO: repair a typo. With two adjacent letters swapped it is
# 7/40 against the vector index's own 6/40, which is the floor rather than a
# gain. Anything better needs trigram or edit distance, and that is a second
# index to build and keep in step rather than a term in an ORDER BY.
_NORM = r"trim(regexp_replace(lower(COALESCE(%s, '')), '[^\pL\pN]+', ' ', 'g'))"

# Every name a title is known by. Checked against the view rather than assumed:
# a warehouse built from a snapshot older than a column does not have it, which
# is the same reason build_index._select_for_index asks. Assuming them cost the
# whole endpoint - search threw BinderException on any warehouse without
# title_romaji rather than quietly ranking a little worse.
NAME_COLUMNS = ("title_english", "title_romaji", "title_native")


def _order_by(con: duckdb.DuckDBPyConnection) -> tuple[str, int]:
    """The ranking term, and how many query parameters it needs.

    Returns plain distance ordering where the view carries no name at all, which
    is exactly the behaviour this replaced."""
    try:
        columns = {row[0] for row in con.execute("DESCRIBE anime_media_latest").fetchall()}
    except duckdb.Error:
        return "ORDER BY distance", 0
    names = [c for c in NAME_COLUMNS if c in columns]
    if not names:
        return "ORDER BY distance", 0
    # The emptiness guard is not optional: a row with no romaji normalises to
    # the empty string, so does a query of pure punctuation, and without it the
    # two match and every untitled row sorts ahead of the real results.
    query = _NORM % "?"
    matches = ", ".join(_NORM % f"m.{c}" for c in names)
    return f"ORDER BY CASE WHEN {query} <> '' AND {query} IN ({matches}) THEN 0 ELSE 1 END, distance", 2


def _search_sql(con: duckdb.DuckDBPyConnection) -> tuple[str, int]:
    order, params = _order_by(con)
    return (
        f"""
    SELECT e.source, e.source_id, e.title,
           1 - array_cosine_similarity(e.embedding, ?::FLOAT[{DIM}]) AS distance,
           m.wb_id, m.poster_url, m.score_100, m.format, m.status
    FROM {TABLE_NAME} e
    LEFT JOIN anime_media_latest m ON m.source = e.source AND m.source_id = e.source_id
    {order}
    LIMIT ?
""",
        params,
    )


def find_similar(
    con: duckdb.DuckDBPyConnection, query_text: str, n_results: int = 10
) -> list[dict[str, Any]]:
    """Embed a free-text query - a title, a vibe, a description - and return the
    most semantically similar titles, nearest first, each already carrying what a
    client needs to draw it.

    A query that IS a title's name, give or take case, spacing and punctuation,
    puts that title first regardless of distance. See the note above _NORM.

    Takes a connection rather than a path: the API already holds one per request,
    and opening the warehouse twice to answer one question is both slower and a
    second chance to fail.

    One query at a time, through embed_query rather than the batch path the index
    is built with - same model, far less memory. See embed.get_query_embedder.
    """
    query_embedding = embed_query(query_text)
    sql, name_params = _search_sql(con)
    # The normalised query appears on both sides of the emptiness guard, and
    # DuckDB binds positionally.
    params = [query_embedding, *([query_text] * name_params), n_results]
    return con.execute(sql, params).fetch_arrow_table().to_pylist()


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
