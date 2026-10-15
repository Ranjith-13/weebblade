"""How well search finds a title you already know the name of.

THE NUMBER THIS EXISTS TO STOP BEING ANECDOTAL. "Romaji search recall is 24/40"
has sat in ROADMAP.md as a carried-over gap since September, and the four
document variants in embed.text_for_embedding were chosen against figures like
it - but the script that produced them was never committed, so every one of
those numbers is a claim nobody can re-run. A measurement that cannot be
repeated is a story about a measurement.

So this is the harness, and the cases are DERIVED FROM THE WAREHOUSE rather than
hand-listed. A hand-picked set of forty titles rots the moment the catalogue
moves and quietly becomes a set of titles that happen to still work.

Three measurements, and the third is the one that stops the other two being
gamed:

  by other name   A title the site shows in English, searched for by its romaji.
                  This is the 24/40 figure. It is the common real query: people
                  type the name a show airs under, not the one a licensor chose.

  by native name  The same title searched for in Japanese. Currently near zero
                  by construction - title_native is not in the indexed document
                  at all - which is exactly why it is measured separately rather
                  than folded into the line above.

  loosely typed   The same other name, typed the way people type: lower case,
                  punctuation gone, spacing collapsed. THIS IS THE HONEST ONE.
                  Cases are generated from the warehouse's own strings, so any
                  rule that matches a name exactly scores 40/40 against the line
                  above by construction - it is being asked to reproduce the
                  string it was given. Nobody types "Kimetsu no Yaiba: Yuukaku-hen"
                  with the colon and the capitals. A fix that survives here is a
                  fix; one that only holds above is a benchmark marking its own
                  homework.

  mistyped        The same name with two adjacent letters swapped. THE BOUNDARY.
                  "loosely typed" above stopped being an independent check the
                  moment the fix normalised punctuation, because the harness
                  loosens a name exactly as the query path does - it now tests
                  one transformation from both ends and will read 40/40 for any
                  normalising rule, including a wrong one. A transposition is
                  not repaired by normalising, so this is what is left when the
                  exact-match path cannot fire, and it should be read as the
                  floor the vector index provides on its own.

  on-genre        Twelve vague descriptions, scored on how many of the top ten
                  carry a genre the query asked for. THE REGRESSION GUARD. Every
                  way of making names easier to find works by adding name text to
                  a document the model mean-pools, which dilutes the synopsis and
                  makes vague search worse. A change that lifts recall and drops
                  this has moved the problem, not fixed it.

Run it against a built warehouse, before and after a change, on the SAME file:
the sample is drawn from the catalogue in it, so figures from two different
warehouses are not comparable.

    python -m ai.search.evaluate --db-path data/warehouse.duckdb
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from .query import find_similar

# Deliberately vague: none of these names a title, so the only thing a result
# can be judged on is whether it is the KIND of thing asked for. The genre each
# one is scored against is the one a reader would say they had asked for.
VAGUE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("a quiet show about cooking", ("Slice of Life", "Gourmet")),
    ("mecha pilots fighting in space", ("Mecha", "Sci-Fi", "Action")),
    ("a romance between two high school students", ("Romance",)),
    ("detectives solving a murder", ("Mystery",)),
    ("a sports team training for a tournament", ("Sports",)),
    ("magical girls transforming", ("Fantasy", "Magic")),
    ("something funny about office workers", ("Comedy",)),
    ("a dark story about revenge", ("Drama", "Thriller", "Action")),
    ("music and a band forming", ("Music",)),
    ("a horror story with monsters", ("Horror", "Supernatural")),
    ("isekai hero summoned to another world", ("Fantasy", "Adventure", "Isekai")),
    ("a gentle story about family life", ("Slice of Life", "Drama")),
)

TOP_N = 10


@dataclass
class Case:
    """One query and the title it must find."""

    query: str
    source: str
    source_id: str
    shown_as: str


def _cases(con: duckdb.DuckDBPyConnection, column: str, limit: int) -> list[Case]:
    """Titles the site displays in English, paired with another of their names.

    Ordered by user_count, not sampled at random: the titles most people hold are
    the ones most likely to be searched for, and a fixed order means two runs over
    one warehouse draw exactly the same cases. Random sampling would make every
    comparison carry its own noise.

    The other name has to actually differ from the displayed one, or the case
    asks whether search can find a title by the name it is already listed under,
    which it can and which measures nothing.
    """
    rows = con.execute(
        f"""
        SELECT source, source_id, title_english, {column} AS other
        FROM anime_media_latest
        WHERE title_english IS NOT NULL AND {column} IS NOT NULL
          AND lower(trim(title_english)) <> lower(trim({column}))
          AND length(trim({column})) > 2
        ORDER BY user_count DESC NULLS LAST, source_id
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [Case(other, source, source_id, english) for source, source_id, english, other in rows]


def loosen(name: str) -> str:
    """A title as somebody would actually type it into a search box.

    Lower case, no punctuation, single spaces. Deliberately not a typo model:
    the point is not to simulate mistakes but to stop the exact string the
    warehouse happens to store from being the only thing that is ever asked for.
    """
    kept = [c.lower() if c.isalnum() or c.isspace() else " " for c in name]
    return " ".join("".join(kept).split())


def mistype(name: str) -> str:
    """The name with two adjacent letters swapped, deterministically.

    Always the same swap for the same name, so two runs compare. The midpoint
    rather than a random position: a transposition in the first word is a
    different query, and one in the last is often inside a volume number."""
    chars = list(name)
    letters = [i for i, c in enumerate(chars) if c.isalnum()]
    if len(letters) < 4:
        return name
    i = letters[len(letters) // 2]
    j = letters[len(letters) // 2 + 1]
    chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def _rank_of(results: list[dict[str, Any]], case: Case) -> int | None:
    """Where the wanted title landed, 1-based, or None if it never did."""
    for rank, row in enumerate(results, 1):
        if row["source"] == case.source and str(row["source_id"]) == str(case.source_id):
            return rank
    return None


def by_name(
    con: duckdb.DuckDBPyConnection, column: str, limit: int, typed: str = "exact"
) -> dict[str, Any]:
    """Recall for titles searched for under another of their names."""
    how = {"exact": lambda n: n, "loose": loosen, "mistyped": mistype}[typed]
    cases = _cases(con, column, limit)
    ranks = [_rank_of(find_similar(con, how(c.query), TOP_N), c) for c in cases]
    return {
        "cases": len(cases),
        "first": sum(1 for r in ranks if r == 1),
        "top5": sum(1 for r in ranks if r is not None and r <= 5),
        "found": sum(1 for r in ranks if r is not None),
        "misses": [c.shown_as for c, r in zip(cases, ranks) if r is None][:8],
    }


def on_genre(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Of the top ten for each vague query, how many carry a genre it asked for."""
    hits = total = 0
    for query, wanted in VAGUE:
        for row in find_similar(con, query, TOP_N):
            genres = con.execute(
                "SELECT genres FROM anime_media_latest WHERE source = ? AND source_id = ?",
                [row["source"], row["source_id"]],
            ).fetchone()
            total += 1
            if genres and genres[0] and set(genres[0]) & set(wanted):
                hits += 1
    return {"on_genre": hits, "of": total}


def evaluate(con: duckdb.DuckDBPyConnection, limit: int = 40) -> dict[str, Any]:
    return {
        "romaji": by_name(con, "title_romaji", limit),
        "romaji, loose": by_name(con, "title_romaji", limit, "loose"),
        "romaji, mistyped": by_name(con, "title_romaji", limit, "mistyped"),
        "native": by_name(con, "title_native", limit),
        "vague": on_genre(con),
    }


def _print(report: dict[str, Any]) -> None:
    for key in ("romaji", "romaji, loose", "romaji, mistyped", "native"):
        r = report[key]
        print(
            f"  by {key:14} name   first {r['first']:>3}/{r['cases']}   "
            f"top5 {r['top5']:>3}/{r['cases']}   found {r['found']:>3}/{r['cases']}"
        )
        if r["misses"]:
            print(f"    never found: {', '.join(r['misses'])}")
    v = report["vague"]
    print(f"  on-genre (top {TOP_N})  {v['on_genre']}/{v['of']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=Path("data/warehouse.duckdb"))
    parser.add_argument("-n", "--cases", type=int, default=40)
    args = parser.parse_args()

    con = duckdb.connect(str(args.db_path), read_only=True)
    try:
        _print(evaluate(con, args.cases))
    finally:
        con.close()
