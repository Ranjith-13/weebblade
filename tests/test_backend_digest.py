"""GET /digest: the weekly write-up, out of the warehouse.

It used to come off the filesystem, which worked while the API and the pipeline
shared a disk. These tests build it the way the pipeline does - markdown files
in the lake, folded into the warehouse by refresh_catalog - because that is the
path that has to work for the digest to reach a reader at all.
"""

import duckdb
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db, get_db_optional
from backend.app.main import app
from processing.duckdb_catalog import _prose_views


@pytest.fixture
def digests_for(tmp_path):
    def build(written: dict[str, str]) -> TestClient:
        data = tmp_path / "data"
        (data / "digests").mkdir(parents=True)
        for run_date, content in written.items():
            (data / "digests" / f"{run_date}.md").write_text(content, encoding="utf-8")

        db_path = tmp_path / "warehouse.duckdb"
        con = duckdb.connect(str(db_path))
        try:
            _prose_views(con, data)
        finally:
            con.close()

        def override():
            con = duckdb.connect(str(db_path), read_only=True)
            try:
                yield con
            finally:
                con.close()

        app.dependency_overrides[get_db] = override
        app.dependency_overrides[get_db_optional] = override
        return TestClient(app)

    yield build
    app.dependency_overrides.clear()


def test_latest_digest_returns_503_when_none_exist(digests_for):
    client = digests_for({})

    assert client.get("/digest/latest").status_code == 503


def test_the_index_is_empty_rather_than_an_error_when_none_exist(digests_for):
    """The sitemap asks this on every build. "No digests" is an answer, not a
    failure."""
    client = digests_for({})

    assert client.get("/digest").json() == []


def test_list_and_fetch_digests(digests_for):
    client = digests_for({
        "2026-08-31": "Older digest",
        "2026-09-07": "Newest digest",
    })

    assert client.get("/digest").json() == ["2026-09-07", "2026-08-31"]
    assert client.get("/digest/latest").json() == {
        "run_date": "2026-09-07", "content": "Newest digest",
    }
    assert client.get("/digest/2026-08-31").json() == {
        "run_date": "2026-08-31", "content": "Older digest",
    }
    assert client.get("/digest/2026-01-01").status_code == 404


def test_markdown_survives_the_round_trip_through_the_warehouse(digests_for):
    """The digest is markdown with apostrophes, headings and newlines in it, and
    it is now carried as a string through DuckDB rather than read off disk. What
    a reader sees has to be byte for byte what the model wrote."""
    written = "## Fall 2026\n\nIt's *busy*: 227 titles, 39 can't be confirmed.\n\n- one\n- two\n"
    client = digests_for({"2026-10-11": written})

    assert client.get("/digest/latest").json()["content"] == written
