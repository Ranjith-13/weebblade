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
# live catalogue, on-genre was 92/120 before and 92/120 after - and 96/120 both
# ways again at 40 seasons, after the tiers below were added.
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
# RE-MEASURED AT 40 SEASONS (11,992 titles, 2026-10-19), because the figures above
# were taken on a catalogue half this size and a bigger one is a harder one: more
# titles means more titles sharing a name. Romaji read 38/40 until the tier below
# was added and 39/40 after, which IS full marks - see _name_rank, and the
# ceiling evaluate.unsatisfiable reports. Native 40/40, on-genre 96/120, both up.
#
# WHAT THIS DOES NOT DO: repair a typo. With two adjacent letters swapped it is
# 8/40 - 7/40 before the catalogue grew, against the vector index's own 6/40,
# which is the floor rather than a gain. Anything better needs trigram or edit
# distance, and that is a second index to build and keep in step rather than a
# term in an ORDER BY.
_NORM = r"trim(regexp_replace(lower(COALESCE(%s, '')), '[^\pL\pN]+', ' ', 'g'))"

# Every name a title is known by. Checked against the view rather than assumed:
# a warehouse built from a snapshot older than a column does not have it, which
# is the same reason build_index._select_for_index asks. Assuming them cost the
# whole endpoint - search threw BinderException on any warehouse without
# title_romaji rather than quietly ranking a little worse.
NAME_COLUMNS = ("title_english", "title_romaji", "title_native")


def _columns(con: duckdb.DuckDBPyConnection) -> set[str]:
    """What anime_media_latest actually carries. A warehouse built from a
    snapshot older than a column does not have it, and naming one it lacks
    fails the whole query rather than ranking a little worse - which is how
    search once threw BinderException on every request."""
    try:
        return {row[0] for row in con.execute("DESCRIBE anime_media_latest").fetchall()}
    except duckdb.Error:
        return set()


def _name_rank(con: duckdb.DuckDBPyConnection) -> tuple[str, int]:
    """An expression scoring how well a row's names match the query, and how
    many query parameters it needs. 0 is a literal match, 1 a normalised one,
    2 no match at all.

    "2" rather than NULL where the view carries no name, so the caller can
    order by it unconditionally and get the plain distance ordering this
    replaced."""
    names = [c for c in NAME_COLUMNS if c in _columns(con)]
    if not names:
        return "2", 0
    # The emptiness guard is not optional: a row with no romaji normalises to
    # the empty string, so does a query of pure punctuation, and without it the
    # two match and every untitled row sorts ahead of the real results.
    query = _NORM % "?"
    matches = ", ".join(_NORM % f"m.{c}" for c in names)
    literal = ", ".join(f"lower(trim(COALESCE(m.{c}, '')))" for c in names)
    # THREE TERMS, AND THE MIDDLE ONE EARNS ITS PLACE. Two titles can match a
    # name equally well and the catalogue is full of them: Demon Slayer's film
    # and the TV re-cut carry the SAME title_romaji, and "Kakegurui" matches
    # both seasons because season two is "Kakegurui××" and the normaliser
    # strips a multiplication sign as punctuation. With only a match flag the
    # tie fell to cosine distance, which picked the TV arc over the film and
    # season two over season one - measured as 38/40 on a benchmark that had
    # read 40/40 before the catalogue doubled.
    #
    # Where names cannot separate two titles, the one more people hold is the
    # one more people mean: the film has 239,419 votes against 91,964, and
    # Kakegurui's first season 74,924 against 36,026. Applied ONLY inside the
    # matched tiers, so a vague query that names no title is ordered by
    # distance exactly as it was.
    #
    # A literal match outranks a normalised one, because normalising is a
    # concession to how people type and not a claim that two names are the
    # same. Typing a title exactly should not be beaten by a sequel whose
    # punctuation the normaliser happened to erase.
    return (
        f"CASE WHEN {query} = '' THEN 2 "
        f"     WHEN lower(trim(?)) IN ({literal}) THEN 0 "
        f"     WHEN {query} IN ({matches}) THEN 1 ELSE 2 END",
        3,
    )


def _search_sql(con: duckdb.DuckDBPyConnection) -> tuple[str, int]:
    """The search, and how many times the query text has to be bound.

    Ranked in a wrapper rather than in one ORDER BY, because the match tier is
    needed TWICE - once to order by it and once to decide whether the vote
    tiebreak applies - and repeating the expression would bind the query text
    twice as often and drift the two copies apart. The inner select names its
    columns so name_rank and user_count rank the results without joining them.
    """
    rank, params = _name_rank(con)
    # Votes are the tiebreak between titles that match a name equally well, and
    # like the names themselves they are not guaranteed to be there. 0 for every
    # row where they are not, which leaves distance deciding, as before.
    votes = "m.user_count" if "user_count" in _columns(con) else "0"
    return (
        f"""
    SELECT source, source_id, title, distance, wb_id, poster_url, score_100, format, status
    FROM (
      SELECT e.source, e.source_id, e.title,
             1 - array_cosine_similarity(e.embedding, ?::FLOAT[{DIM}]) AS distance,
             m.wb_id, m.poster_url, m.score_100, m.format, m.status,
             {votes} AS user_count,
             {rank} AS name_rank
      FROM {TABLE_NAME} e
      LEFT JOIN anime_media_latest m ON m.source = e.source AND m.source_id = e.source_id
    )
    ORDER BY name_rank,
             -- Only inside a matched tier. For a vague query every row is 2,
             -- this is 0 for all of them, and distance decides as it always did.
             CASE WHEN name_rank < 2 THEN -COALESCE(user_count, 0) ELSE 0 END,
             distance
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
