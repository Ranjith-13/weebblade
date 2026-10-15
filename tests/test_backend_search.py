"""GET /search: one query against the warehouse, matches already decorated."""

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from ai.search.embed import DIM
from backend.app.db import get_db_optional
from backend.app.main import app
from processing.duckdb_catalog import refresh_catalog


def _vector(lead: float = 1.0) -> list[float]:
    return [lead] + [0.0] * (DIM - 1)


@pytest.fixture
def search_over(tmp_path, monkeypatch):
    """A client over a warehouse built from rows, with the query embedding fixed.

    The model is stubbed, not the search: the SQL that ranks and decorates is
    exactly the shipped one. `vectors` maps a source key to the vector stored for
    it, so a test can say which title should win."""
    import ai.search.query as query_module
    from backend.app.limiter import limiter

    # The limiter counts process-wide, and the rate-limit test below spends a
    # whole allowance on purpose.
    limiter.reset()
    monkeypatch.setattr(query_module, "embed_query", lambda text: _vector())

    def build(rows: list[dict] | None, vectors: dict[str, list[float]] | None = None) -> TestClient:
        if rows is None:  # no warehouse at all
            app.dependency_overrides.pop(get_db_optional, None)
            return TestClient(app)

        data = tmp_path / "data"
        path = (data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-10"
                / "part-0.parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path)
        db_path = tmp_path / "warehouse.duckdb"
        refresh_catalog(data, db_path)

        if vectors is not None:
            con = duckdb.connect(str(db_path))
            con.execute(
                f"CREATE TABLE anime_embedding (key VARCHAR, source VARCHAR, source_id VARCHAR, "
                f"title VARCHAR, document VARCHAR, embedding FLOAT[{DIM}])"
            )
            for key, vector in vectors.items():
                source, source_id = key.split(":")
                con.execute(
                    "INSERT INTO anime_embedding VALUES (?, ?, ?, ?, ?, ?)",
                    [key, source, source_id, key, "", vector],
                )
            con.close()

        def override():
            con = duckdb.connect(str(db_path), read_only=True)
            try:
                yield con
            finally:
                con.close()

        app.dependency_overrides[get_db_optional] = override
        return TestClient(app)

    yield build
    app.dependency_overrides.clear()


def _row(source: str, source_id: str, **over) -> dict:
    row = {
        "source": source, "source_id": source_id, "title_english": "Frieren", "format": "TV",
        "season": "SUMMER", "season_year": 2026, "run_date": "2026-09-10", "status": "current",
        "poster_url": f"https://img/{source_id}.jpg", "score_100": 90.0,
    }
    row.update(over)
    return row


def test_results_carry_what_a_client_needs_to_draw_them(search_over):
    """The frontend used to ship the whole catalogue to the browser to decorate
    twenty results. They now arrive with their own poster, score and format -
    from the same query that ranked them, because the vectors are a table beside
    the titles rather than a separate store to reconcile afterwards."""
    client = search_over(
        [_row("kitsu", "1", wb_id="wb_1", source_keys=["kitsu:1"])],
        {"kitsu:1": _vector()},
    )

    result = client.get("/search", params={"q": "elf mage"}).json()["results"][0]

    assert result["poster_url"] == "https://img/1.jpg"
    assert result["score_100"] == 90.0
    assert (result["format"], result["status"], result["wb_id"]) == ("TV", "current", "wb_1")


def test_the_nearest_title_comes_first(search_over):
    client = search_over(
        [_row("kitsu", "1", wb_id="wb_1"), _row("kitsu", "2", wb_id="wb_2")],
        {"kitsu:1": [0.0, 1.0] + [0.0] * (DIM - 2), "kitsu:2": _vector()},
    )

    results = client.get("/search", params={"q": "elf mage"}).json()["results"]

    assert [r["source_id"] for r in results] == ["2", "1"]
    assert results[0]["distance"] < results[1]["distance"]


def test_n_limits_how_many_come_back(search_over):
    client = search_over(
        [_row("kitsu", str(i), wb_id=f"wb_{i}") for i in range(5)],
        {f"kitsu:{i}": _vector(1.0 - i / 10) for i in range(5)},
    )

    assert len(client.get("/search", params={"q": "x", "n": 2}).json()["results"]) == 2


def test_search_returns_503_when_no_index_has_been_built(search_over):
    """The warehouse is there, the vectors are not - the pipeline has run but
    build_index has not. Come back, rather than something is broken."""
    client = search_over([_row("kitsu", "1", wb_id="wb_1")], None)

    assert client.get("/search", params={"q": "magic and war"}).status_code == 503


def test_search_returns_503_without_a_warehouse(search_over):
    """Search no longer has a store of its own to fall back on: the index IS the
    warehouse. Without one there are no matches to answer with, decorated or
    otherwise."""
    client = search_over(None)

    assert client.get("/search", params={"q": "magic and war"}).status_code == 503


def test_search_requires_nonempty_query():
    with TestClient(app) as client:
        assert client.get("/search", params={"q": ""}).status_code == 422


def test_search_is_rate_limited(search_over):
    # /search has a stricter 20/minute limit than the app default (60/minute)
    # since it runs the embedding model on every call. Checks the behaviour -
    # early requests pass, the limiter does kick in - rather than an exact
    # boundary, which is a slowapi counting detail and not a contract.
    client = search_over([_row("kitsu", "1", wb_id="wb_1")], {"kitsu:1": _vector()})

    statuses = [client.get("/search", params={"q": "test"}).status_code for _ in range(25)]

    assert statuses[0] == 200
    assert 429 in statuses


# --- a name typed in is not a semantic question -----------------------------
#
# Measured over the 40 most-held titles on the live catalogue (ai/search/
# evaluate.py): searching each by its romaji put the right one first 10 times,
# while finding it somewhere in the top ten 28 times. The failures were
# franchises whose documents are near-identical - four Attack on Titan entries,
# three Demon Slayer arcs - so cosine distance cannot separate them. In every
# test below the DECOY is deliberately the nearer vector, which is the situation
# that was losing.


def _far() -> list[float]:
    """A vector the stubbed query is genuinely far from.

    Orthogonal, not merely shorter: distance here is cosine, which ignores
    magnitude, so _vector(0.1) is the SAME direction as _vector(1.0) and sits at
    distance 0 beside it. Written that way first, every "the decoy is nearer"
    test below was really a tie broken by row order."""
    return [0.0, 1.0] + [0.0] * (DIM - 2)


def _named(source_id, english, romaji=None, native=None):
    """A row carrying only the names it was given.

    Not `title_native=None`: a column that is None in every row lands in the
    parquet as a null-typed column, which changes what the catalogue builds and
    takes wb_id out of the view. The absent-column case has its own test below."""
    names = {"title_english": english, "wb_id": f"wb_{source_id}"}
    if romaji is not None:
        names["title_romaji"] = romaji
    if native is not None:
        names["title_native"] = native
    return _row("kitsu", source_id, **names)


def test_a_title_typed_by_its_other_name_beats_a_nearer_vector(search_over):
    client = search_over(
        [_named("1", "Decoy", romaji="Totally Different"),
         _named("2", "Attack on Titan: The Final Season", romaji="Shingeki no Kyojin: The Final Season")],
        {"kitsu:1": _vector(1.0), "kitsu:2": _far()},
    )

    results = client.get("/search", params={"q": "Shingeki no Kyojin: The Final Season"}).json()["results"]

    assert results[0]["source_id"] == "2"


def test_case_punctuation_and_spacing_are_not_what_anyone_means(search_over):
    """Nobody types the colon. Compared as stored, the rule fired only for
    titles that happen to carry no punctuation - which is no franchise entry,
    the exact rows it exists for."""
    client = search_over(
        [_named("1", "Decoy", romaji="Totally Different"),
         _named("2", "Demon Slayer", romaji="Kimetsu no Yaiba: Yuukaku-hen")],
        {"kitsu:1": _vector(1.0), "kitsu:2": _far()},
    )

    for typed in ("kimetsu no yaiba yuukaku hen", "KIMETSU NO YAIBA: YUUKAKU-HEN",
                  "  Kimetsu  no   Yaiba :  Yuukaku hen "):
        results = client.get("/search", params={"q": typed}).json()["results"]
        assert results[0]["source_id"] == "2", typed


def test_a_japanese_name_finds_its_title(search_over):
    """0/40 before this. The model is all-MiniLM-L6-v2, English-only, so adding
    title_native to the EMBEDDED document moved it to 1/40 - the tokeniser has
    almost nothing for the script. A string comparison does not care."""
    # The decoy carries a native name too, or the column is absent from the
    # whole view and the ranking term correctly declines to use it - which is
    # what the test below is for, and would make this one pass for that reason
    # instead of the one it is about.
    client = search_over(
        [_named("1", "Decoy", native="全く違う作品"),
         _named("2", "Demon Slayer", native="鬼滅の刃")],
        {"kitsu:1": _vector(1.0), "kitsu:2": _far()},
    )

    results = client.get("/search", params={"q": "鬼滅の刃"}).json()["results"]

    assert results[0]["source_id"] == "2"
    # The normaliser strips punctuation but must never strip the script itself:
    # [^a-z0-9] would delete this query outright.
    assert client.get("/search", params={"q": " 鬼滅の刃 "}).json()["results"][0]["source_id"] == "2"


def test_a_query_that_names_no_title_is_ordered_exactly_as_before(search_over):
    """THE REGRESSION GUARD, and the reason this is one ORDER BY term rather than
    a second index. A vague query equals no title's name, so every row scores the
    same and the ordering is the distance ordering it has always been. Measured
    on the live catalogue: 92/120 on-genre before and after."""
    client = search_over(
        [_named("1", "Nearest", romaji="Ichiban"), _named("2", "Furthest", romaji="Nibanme")],
        {"kitsu:1": _vector(1.0), "kitsu:2": _far()},
    )

    results = client.get("/search", params={"q": "a quiet show about cooking"}).json()["results"]

    assert [r["source_id"] for r in results] == ["1", "2"]


def test_an_empty_name_does_not_match_every_untitled_row(search_over):
    """A row with no romaji normalises to the empty string, and so does a query
    of pure punctuation. Without the guard they match and the whole catalogue
    sorts ahead of the actual results."""
    client = search_over(
        [_named("1", "Nearest", romaji="Ichiban"), _named("2", "No romaji at all", romaji=None)],
        {"kitsu:1": _vector(1.0), "kitsu:2": _far()},
    )

    results = client.get("/search", params={"q": "!!!"}).json()["results"]

    assert [r["source_id"] for r in results] == ["1", "2"]


def test_the_ranking_term_only_names_columns_the_view_actually_has(tmp_path):
    """A warehouse built from a snapshot older than a column does not have it -
    the same reason build_index._select_for_index asks before selecting. The
    first version assumed all three names and threw BinderException on every
    query, taking the endpoint down rather than ranking slightly worse.

    Asserted on the generated SQL rather than through a client, because the
    thing being checked is which columns are named."""
    from ai.search.query import _order_by

    con = duckdb.connect()
    con.execute("CREATE VIEW anime_media_latest AS SELECT 'a' AS title_english, 'b' AS title_romaji")
    order, params = _order_by(con)
    assert "title_english" in order and "title_romaji" in order
    assert "title_native" not in order
    assert params == 2

    # And with no name at all, the ordering it has always had.
    con.execute("CREATE OR REPLACE VIEW anime_media_latest AS SELECT 1 AS wb_id")
    assert _order_by(con) == ("ORDER BY distance", 0)
    con.close()
