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
