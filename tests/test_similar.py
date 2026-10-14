"""Neighbours for "More like this" (ai/search/similar.py).

THE FEATURE WAS LOGGED AS FREE AND IS NOT. The plan was one SQL query against
the search index - array_cosine_similarity on a vector already built, already
published, already paid for. Measured on the live catalogue it returns puns: the
search document leads with every name a title has, because that is what takes
"type the other name and find it" from 10/40 to 22/40, and a vector that leads
with names matches on names. Blue Box Season 2 came back beside The Blue
Orchestra Season 2, The Fire Hunter Season 2 and Pacific Rim: The Black Season 2.

So this embeds a different document, and these tests pin the three decisions
that made the output usable rather than merely present.
"""

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ai.search import similar


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    """A warehouse of hand-written titles, embedded by a stub.

    The stub maps a document to a vector by the words in it, so "what should be
    near what" is decided by the test rather than by a 90 MB model. What is
    being tested is the filtering and the ranking, not MiniLM.
    """
    db = tmp_path / "warehouse.duckdb"

    def build(rows: list[dict], franchises: list[tuple[int, str]] | None = None) -> Path:
        con = duckdb.connect(str(db))
        for row in rows:
            row.setdefault("mal_id", None)
            row.setdefault("format", "TV")
            row.setdefault("genres", [])
            row.setdefault("synopsis", None)
            row.setdefault("title_english", row["wb_id"])
        con.register("_rows", pa.Table.from_pylist(rows))
        con.execute("CREATE TABLE anime_media_latest AS SELECT * FROM _rows")
        if franchises is not None:
            con.register("_f", pa.Table.from_pylist(
                [{"mal_id": m, "franchise_id": f} for m, f in franchises]))
            con.execute("CREATE TABLE franchise_member AS SELECT * FROM _f")
        con.close()
        return db

    # A word-bag embedding: documents sharing words end up near each other.
    def fake_embed(texts: list[str]) -> list[list[float]]:
        vocab = sorted({word for text in texts for word in text.lower().split()})
        return [[float(word in text.lower().split()) for word in vocab] or [1.0]
                for text in texts]

    monkeypatch.setattr(similar, "embed_texts", fake_embed)
    return build


def _neighbours(db: Path, wb_id: str) -> list[str]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT similar_wb_id FROM anime_similar WHERE wb_id = ? ORDER BY rank", [wb_id]
        ).fetchall()]
    finally:
        con.close()


def test_a_title_with_no_synopsis_is_neither_compared_nor_offered(warehouse):
    """THE BUG THIS EXISTS TO PREVENT. 533 of 6,359 titles have no synopsis. The
    search document gives those a shape line instead - a 2019 film by ufotable
    from a manga - which is right there and wrong here: two titles with nothing
    written about them produce the SAME STRING, so their vectors are identical
    and each is served to the other as the closest thing in the catalogue. 85
    pairs did that, "Madame: Welcome to Dolly's House" with "The Storm" among
    them. Inventing a relationship out of an absence is the one thing this
    design does not do."""
    db = warehouse([
        {"wb_id": "wb_blank1"},
        {"wb_id": "wb_blank2"},
        {"wb_id": "wb_real", "synopsis": "pirates sail the grand line"},
        {"wb_id": "wb_other", "synopsis": "pirates sail and fight"},
    ])
    similar.build_similar(db)

    assert _neighbours(db, "wb_blank1") == []
    assert _neighbours(db, "wb_blank2") == []
    assert "wb_blank1" not in _neighbours(db, "wb_real")
    assert _neighbours(db, "wb_real") == ["wb_other"]


def test_a_titles_own_franchise_is_left_out(warehouse):
    """The title page lists the franchise in full, immediately above this. A
    "more like this" that opens with the sequel is a second copy of the section
    the reader just scrolled past."""
    db = warehouse(
        [
            {"wb_id": "wb_s1", "mal_id": 1, "synopsis": "a quiet camping trip in the mountains"},
            {"wb_id": "wb_s2", "mal_id": 2, "synopsis": "a quiet camping trip in the mountains"},
            {"wb_id": "wb_else", "mal_id": 3, "synopsis": "a quiet trip to the seaside"},
        ],
        franchises=[(1, "f1"), (2, "f1"), (3, "f2")],
    )
    similar.build_similar(db)

    assert _neighbours(db, "wb_s1") == ["wb_else"]


def test_the_same_work_under_another_name_is_not_a_recommendation(warehouse):
    """MAL's relations do not cover everything, so the franchise exclusion
    misses pairs like "Wanmei Shijie 5" with "Perfect World 4" - one title
    romanised, the other translated - and 46 pairs sharing a synopsis word for
    word because the identity merge listed one show twice. Anything nearer than
    MIN_DISTANCE is that, not a neighbour."""
    db = warehouse([
        {"wb_id": "wb_a", "synopsis": "an immortal cultivator ascends the heavens"},
        {"wb_id": "wb_duplicate", "synopsis": "an immortal cultivator ascends the heavens"},
        {"wb_id": "wb_far", "synopsis": "an immortal cultivator opens a bakery"},
    ])
    similar.build_similar(db)

    assert "wb_duplicate" not in _neighbours(db, "wb_a")
    assert _neighbours(db, "wb_a") == ["wb_far"]


def test_music_videos_and_specials_are_not_what_to_watch_next(warehouse):
    """A third of the catalogue, almost none of it scored. The same reasoning
    that makes /browse default to TV, applied to the pool a recommendation can
    be drawn from rather than to a listing."""
    db = warehouse([
        {"wb_id": "wb_tv", "synopsis": "a band forms at school"},
        {"wb_id": "wb_mv", "format": "music", "synopsis": "a band forms at school"},
        {"wb_id": "wb_recap", "format": "special", "synopsis": "a band forms at school"},
        {"wb_id": "wb_other", "synopsis": "a band forms at work"},
    ])
    similar.build_similar(db)

    assert _neighbours(db, "wb_tv") == ["wb_other"]


def test_the_text_embedded_says_what_a_title_is_and_never_what_it_is_called(warehouse):
    """The whole difference from the search document, in one assertion. A name
    in here is what made the first version answer Blue Box Season 2 with four
    other titles that merely also said "Season 2"."""
    document = similar.text_for_similarity({
        "title_english": "Blue Box Season 2",
        "title_romaji": "Ao no Hako",
        "genres": ["Romance", "Sports"],
        "synopsis": "A badminton player falls for a basketball star.",
    })

    assert "Blue Box" not in document
    assert "Ao no Hako" not in document
    assert document == "Romance, Sports. A badminton player falls for a basketball star."


def test_an_early_warehouse_is_a_state_not_a_failure(warehouse, tmp_path):
    """No file, no catalogue, no identities yet. Same rule as build_index: this
    runs last in the weekly pipeline and must not be what fails a run."""
    assert similar.build_similar(tmp_path / "nothing.duckdb") == 0

    db = warehouse([{"wb_id": "wb_only", "synopsis": "nobody else is in this catalogue"}])
    assert similar.build_similar(db) == 0


def test_franchises_not_built_yet_costs_the_exclusion_and_nothing_else(warehouse):
    """build_franchises runs before this in the weekly pipeline, but a warehouse
    from before franchises existed still has to index."""
    db = warehouse([
        {"wb_id": "wb_a", "synopsis": "a detective solves a murder"},
        {"wb_id": "wb_b", "synopsis": "a detective solves a theft"},
    ], franchises=None)

    assert similar.build_similar(db) == 2
    assert _neighbours(db, "wb_a") == ["wb_b"]
