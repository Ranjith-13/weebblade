from fastapi.testclient import TestClient

from backend.app.main import app


def test_search_returns_503_when_index_not_built(tmp_path, monkeypatch):
    import backend.app.routers.search as search_module

    monkeypatch.setattr(search_module, "CHROMA_DIR", tmp_path / "chroma")

    with TestClient(app) as client:
        response = client.get("/search", params={"q": "magic and war"})

    assert response.status_code == 503


def test_search_requires_nonempty_query():
    with TestClient(app) as client:
        response = client.get("/search", params={"q": ""})

    assert response.status_code == 422


def test_search_is_rate_limited(tmp_path, monkeypatch):
    # /search has a stricter 20/minute limit than the app default (60/minute) since
    # it runs the embedding model on every call. The 503 "index not built" path is
    # still subject to the limit - rate limiting happens before the route body runs.
    # Checks the behavior (early requests pass, the limiter does eventually kick
    # in) rather than an exact request-count boundary, since that's an internal
    # slowapi counting detail, not a contract worth pinning a test to.
    import backend.app.routers.search as search_module

    monkeypatch.setattr(search_module, "CHROMA_DIR", tmp_path / "chroma")

    with TestClient(app) as client:
        statuses = [client.get("/search", params={"q": "test"}).status_code for _ in range(25)]

    assert statuses[0] == 503
    assert 429 in statuses


# --- decoration -------------------------------------------------------------------

import sys  # noqa: E402
import types  # noqa: E402
from pathlib import Path  # noqa: E402

import duckdb  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import pytest  # noqa: E402

from backend.app.db import get_db_optional  # noqa: E402
from processing.duckdb_catalog import refresh_catalog  # noqa: E402
from processing.identity import Registry, assign, save  # noqa: E402


@pytest.fixture
def search_over(tmp_path, monkeypatch):
    """A search whose vector matches are fixed, over a warehouse built from rows.

    The index is stubbed: what is under test is what the endpoint does with the
    matches, and the real one needs chromadb and an embedding model."""
    import backend.app.routers.search as search_module
    from backend.app.limiter import limiter

    # The limiter's counts are process-wide, and the rate-limit test above spends
    # this client's whole allowance on purpose.
    limiter.reset()
    chroma = tmp_path / "chroma"
    chroma.mkdir()
    monkeypatch.setattr(search_module, "CHROMA_DIR", chroma)

    def build(matches: list[dict], rows: list[dict] | None, registry=None) -> TestClient:
        fake = types.ModuleType("ai.search.query")
        fake.find_similar = lambda chroma_dir, q, n_results=10: matches
        monkeypatch.setitem(sys.modules, "ai.search.query", fake)

        if rows is None:
            def no_warehouse():  # a generator, as the real dependency is
                yield None

            app.dependency_overrides[get_db_optional] = no_warehouse
            return TestClient(app)

        data = tmp_path / "data"
        path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-10" / "part-0.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path)
        if registry is not None:
            save(data, registry)
        db_path = tmp_path / "warehouse.duckdb"
        refresh_catalog(data, db_path)

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


def _match(source: str, source_id: str, distance: float = 1.1) -> dict:
    return {"title": f"{source}:{source_id}", "source": source, "source_id": source_id, "distance": distance}


def _row(source: str, source_id: str, **over) -> dict:
    row = {
        "source": source, "source_id": source_id, "title_english": "Frieren", "format": "TV",
        "season": "SUMMER", "season_year": 2026, "run_date": "2026-09-10", "status": "current",
        "poster_url": f"https://img/{source_id}.jpg", "score_100": 90.0,
    }
    row.update(over)
    return row


def test_results_carry_what_a_client_needs_to_draw_them(search_over):
    """The frontend shipped the whole catalogue to the browser to decorate twenty
    results. The results now bring their own poster, score and format."""
    client = search_over([_match("kitsu", "1")], [_row("kitsu", "1", wb_id="wb_1", source_keys=["kitsu:1"])])

    result = client.get("/search", params={"q": "elf mage"}).json()["results"][0]

    assert result["poster_url"] == "https://img/1.jpg"
    assert result["score_100"] == 90.0
    assert (result["format"], result["status"], result["wb_id"]) == ("TV", "current", "wb_1")


def test_a_match_under_a_key_that_since_lost_the_merge_is_still_decorated(search_over):
    """The index is keyed by the winner when it was built. If MAL's row wins next
    week, kitsu:1 is no longer a row in the latest view - but the title is still
    there, and the registry knows the key belongs to it."""
    ids, reg, _ = assign([["kitsu:1", "mal:10"]], Registry(), "2026-09-10")
    client = search_over(
        [_match("kitsu", "1")],
        [_row("mal", "10", wb_id=ids[0], source_keys=["kitsu:1", "mal:10"], poster_url="https://img/mal.jpg")],
        reg,
    )

    result = client.get("/search", params={"q": "elf mage"}).json()["results"][0]

    assert (result["source"], result["source_id"]) == ("kitsu", "1")  # as matched
    assert result["poster_url"] == "https://img/mal.jpg"
    assert result["wb_id"] == ids[0]


def test_a_match_the_warehouse_cannot_place_comes_back_undecorated(search_over):
    client = search_over([_match("kitsu", "1"), _match("kitsu", "404")], [_row("kitsu", "1")])

    results = client.get("/search", params={"q": "elf mage"}).json()["results"]

    assert [r["source_id"] for r in results] == ["1", "404"]  # order kept, nothing dropped
    assert results[1]["poster_url"] is None


def test_without_a_warehouse_search_still_answers(search_over):
    """The matches come from the vector index. A missing warehouse costs them their
    artwork, not their existence."""
    client = search_over([_match("kitsu", "1")], None)

    response = client.get("/search", params={"q": "elf mage"})

    assert response.status_code == 200
    assert response.json()["results"][0]["poster_url"] is None
