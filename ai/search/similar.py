"""Nearest neighbours for "More like this", precomputed into the warehouse.

WHY THIS IS NOT THE SEARCH INDEX, which already holds a vector per title.

The obvious version of this feature is one SQL query: array_cosine_similarity
against the row's own embedding, over data already built and already published.
It was logged that way, and measured on the live catalogue it does not work.
The search document leads with every name a title has, deliberately - that is
what took "type the other name and find it" from 10/40 to 22/40, and it is in
embed.text_for_embedding with the four documents that were compared to pick it.
Leading with names makes the vector a string match on titles, which is right for
search and wrong for this. Measured 2026-10-14 on the published warehouse:

    Blue Box Season 2   -> The Blue Orchestra Season 2, The Fire Hunter Season 2,
                           Ramen Akaneko Season 2, Pacific Rim: The Black Season 2
    SPY x FAMILY        -> Spy Classroom, Spy x Sect
    WITCH WATCH         -> Witch Hat Atelier, Witch on the Holy Night,
                           The Dawn of the Witch, Maebashi Witches

A sports romance beside a kaiju show because both say "Season 2". So the text
here drops the names and keeps what a title IS. Over 400 sampled titles, the
mean genre overlap of the five nearest non-franchise neighbours goes from 0.290
to 0.402, and the examples stop being puns: Blue Box finds school romances, SPY
x FAMILY finds Buddy Daddies, BOCCHI THE ROCK! finds BanG Dream and The Colors
Within.

Re-ranking the existing index by genre overlap was tried first, because it needs
no new embedding. It scores higher on that measure - 0.541 against 0.402 - and
that is the measure being optimised, so the number means nothing. The results
give it away: SPY x FAMILY still returns Spy Classroom and Spy x Sect, and
BOCCHI still leads with its own recap film. Re-ranking reorders a candidate
pool; it cannot repair one that is already thirty titles sharing a word.

WHY NEIGHBOURS AND NOT A SECOND VECTOR COLUMN

A second FLOAT[384] per title is 9.8 MB, on a warehouse the API downloads whole
on every wake into a 512 MB container - the documented constraint on this whole
shape. The neighbours themselves are a few rows per title, about 2 MB, and the
query at serve time becomes a lookup instead of a scan of every vector. The
vectors are a build-time artifact and are thrown away.

This runs after build_franchises, which is what lets the franchise be excluded
here rather than in the API: a title page already lists its own franchise in
full, so a "more like this" that opens with the sequel is a second copy of the
section above it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from .embed import embed_texts

logger = logging.getLogger(__name__)

TABLE_NAME = "anime_similar"

# How many to store. The page shows fewer; the slack is so that a later change
# to what is displayed does not need the pipeline to run again.
NEIGHBOURS = 8

# Formats nobody means by "what should I watch next". Music videos and recap
# specials are a third of the catalogue and almost none of them are scored -
# the same reasoning that makes /browse default to TV, applied to the pool a
# recommendation can come from rather than to a listing.
EXCLUDED_FORMATS = ("music", "special")

# Nearer than this is the same work under another name, not a recommendation.
# The franchise exclusion below catches sequels that MAL knows about, and a
# great many here it does not: the pairs under 0.10 are "Wanmei Shijie 5" with
# "Perfect World 4" (one title romanised, the other translated), "The Outcast
# Season 4" with "The Outcast 5th Season", "Eiga no Osomatsu-san 1" with "2",
# two episodes of the same Genshin Impact short, and 46 pairs that share a
# synopsis word for word because the identity merge listed one show twice.
# Chinese donghua and shorts mostly have no MAL id, so no franchise can be
# built for them and there is nothing else to key the exclusion on.
#
# A mitigation, not a tuning knob: it is covering for gaps in identity and in
# MAL's relation data, and if those improve this stops mattering. Measured on
# 2026-10-14 it drops 251 of 5,826 rank-one neighbours, in a part of the
# catalogue no reader of a well-known title ever reaches - a popular show's
# nearest neighbour sits between 0.25 and 0.55.
MIN_DISTANCE = 0.10

_WANTED = ("wb_id", "mal_id", "format", "genres", "synopsis")


def _select(con: duckdb.DuckDBPyConnection) -> str:
    """Only titles with a synopsis, and that exclusion is load-bearing.

    533 of the 6,359 have none (2026-10-14). The search document gives those a
    shape line instead - a 2019 film by ufotable adapted from a manga - which is
    right there, because something is better than a bare name to match a query
    against. Here it is actively wrong: two titles with no synopsis and the same
    year, format and studio produce the SAME STRING, so their vectors are
    identical and each is served to the other as a perfect match. 85 titles had
    a nearest neighbour at distance zero that way, among them "Madame: Welcome
    to Dolly's House" paired with "The Storm" - two films this catalogue knows
    nothing about, presented as the closest thing to each other in 6,359.

    Inventing a relationship out of an absence is the one thing the whole design
    is built not to do. A title with nothing to compare gets no neighbours and
    is offered as nobody else's, and the page says nothing rather than something
    false.
    """
    columns = {row[0] for row in con.execute("DESCRIBE anime_media_latest").fetchall()}
    return (f"SELECT {', '.join(c for c in _WANTED if c in columns)} "
            "FROM anime_media_latest WHERE wb_id IS NOT NULL AND synopsis IS NOT NULL")


def text_for_similarity(row: dict[str, Any]) -> str:
    """What a title is, with no mention of what it is called.

    Genres first because they are the one dense field - 100% coverage - and they
    are what a reader means by "like this". Then the synopsis, which carries the
    rest. No names, which is the whole difference from the search document; see
    the module docstring for what leaving them in does.
    """
    genres = ", ".join(row.get("genres") or [])
    synopsis = (row.get("synopsis") or "").strip()
    # Spelled out rather than strip(". ") on the joined string, which also ate
    # the synopsis's own closing full stop.
    if genres and synopsis:
        return f"{genres}. {synopsis}"
    return genres or synopsis or "Untitled"


def build_similar(db_path: Path, neighbours: int = NEIGHBOURS) -> int:
    """(Re)build the neighbour table. Returns how many titles got neighbours.

    Same failure rule as build_index: everything slow happens before the
    database is touched, so a failure leaves the previous table serving. And the
    same tolerance for an early warehouse - no file, no catalogue, no identities
    yet are all states this returns 0 for rather than raising.
    """
    if not db_path.exists():
        logger.warning("Warehouse file %s doesn't exist yet - nothing to relate", db_path)
        return 0

    con = duckdb.connect(str(db_path))
    try:
        try:
            rows: list[dict[str, Any]] = (
                con.execute(_select(con)).fetch_arrow_table().to_pylist()
            )
        except duckdb.CatalogException:
            logger.warning("anime_media_latest doesn't exist yet - nothing to relate")
            return 0
        if not rows:
            logger.warning("No data in anime_media_latest - nothing to relate")
            return 0

        families = _families(con)
        vectors = _normalised(embed_texts([text_for_similarity(row) for row in rows]))
        pairs = _neighbours(rows, vectors, families, neighbours)
        if not pairs:
            logger.warning("No neighbours found for any title")
            return 0

        table = pa.Table.from_pylist(pairs, schema=pa.schema([
            ("wb_id", pa.string()), ("similar_wb_id", pa.string()),
            ("distance", pa.float32()), ("rank", pa.int32()),
        ]))
        con.register("_new_similar", table)
        con.execute(f"CREATE OR REPLACE TABLE {TABLE_NAME} AS SELECT * FROM _new_similar")
        con.unregister("_new_similar")
    finally:
        con.close()

    related = len({pair["wb_id"] for pair in pairs})
    logger.info("Related %s titles, %s pairs", related, len(pairs))
    return related


def _families(con: duckdb.DuckDBPyConnection) -> dict[int, set[str]]:
    """Which franchises each MAL id belongs to, so they can be left out.

    Empty where franchises have not been built, which only costs this the
    exclusion: the neighbours are still the right ones, the sequels are just in
    among them.
    """
    try:
        rows = con.execute(
            "SELECT mal_id, franchise_id FROM franchise_member WHERE mal_id IS NOT NULL"
        ).fetchall()
    except duckdb.CatalogException:
        logger.warning("No franchises built yet - sequels will not be excluded")
        return {}
    families: dict[int, set[str]] = {}
    for mal_id, franchise_id in rows:
        families.setdefault(int(mal_id), set()).add(franchise_id)
    return families


def _normalised(vectors: list[list[float]]):
    import numpy as np

    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # A zero vector cannot happen with this model, but dividing by one would
    # poison every distance in the table rather than the one row it came from.
    norms[norms == 0] = 1.0
    return matrix / norms


def _neighbours(rows, vectors, families, neighbours: int) -> list[dict[str, Any]]:
    """Every title's nearest others, excluding its own franchise and the formats
    nobody is asking for.

    Brute force, one row at a time against the whole matrix, which runs once a
    week - an approximate index would be another artifact to keep in step with
    the catalogue for no gain.

    It is not "a few seconds" any more, and the number is written here rather
    than the adjective because the adjective was already wrong once. At 6,359
    titles it was seconds; at 11,989, after the backfill to 40 seasons on
    2026-10-17, it was 4m20s for 10,920 related titles and 87,265 pairs. The
    cost is quadratic in the catalogue, so doubling it again is around twenty
    minutes - which is the point at which an approximate index stops being
    pointless. Re-measure before assuming it is still fine.
    """
    import numpy as np

    eligible = np.array([row.get("format") not in EXCLUDED_FORMATS for row in rows])
    mal_ids = [row.get("mal_id") for row in rows]
    pairs: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        mine = families.get(mal_ids[i] or -1, set())
        scores = vectors @ vectors[i]
        # -2 is below any cosine distance, so these sort to the end and are
        # recognisable afterwards without carrying a second mask around.
        scores[~eligible] = -2.0
        scores[i] = -2.0
        # argpartition, not argsort: this runs 6,359 times over 6,359 scores and
        # only the head is wanted. A few more than asked for, because the
        # franchise is dropped after ranking.
        want = min(neighbours + 12, len(scores))
        head = np.argpartition(-scores, want - 1)[:want]
        taken = 0
        for j in head[np.argsort(-scores[head])]:
            if scores[j] <= -2.0:
                continue
            if mine and families.get(mal_ids[j] or -1, set()) & mine:
                continue
            if 1 - scores[j] < MIN_DISTANCE:
                continue
            taken += 1
            pairs.append({
                "wb_id": row["wb_id"],
                "similar_wb_id": rows[j]["wb_id"],
                "distance": float(1 - scores[j]),
                "rank": taken,
            })
            if taken >= neighbours:
                break
    return pairs
