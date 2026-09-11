"""GET /anime/{wb_id}/franchise."""

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db
from backend.app.main import app
from ingestion.mal.fetch_relations import SCHEMA
from processing.duckdb_catalog import refresh_catalog
from processing.franchise import build_franchises


def _title(wb_id, mal_id, title, year, month=4, day=1, **over):
    row = {
        "source": "kitsu", "source_id": wb_id, "wb_id": wb_id, "mal_id": mal_id, "title_english": title,
        "title_romaji": None, "format": "TV", "season": "SPRING", "season_year": year,
        "start_year": year, "start_month": month, "start_day": day, "score_100": 80.0,
        "poster_url": f"https://img/{wb_id}.jpg", "run_date": "2026-09-11",
    }
    row.update(over)
    return row


def _edge(mal_id, related, relation):
    return {
        "mal_id": mal_id, "title": None, "format": None, "start_date": None, "poster_url": None,
        "related_mal_id": related, "relation_type": relation, "related_title": f"MAL {related}",
        "related_format": "movie", "related_start_date": "2019-06", "related_poster_url": f"https://mal/{related}.jpg",
        "fetched_on": "2026-09-11",
    }


@pytest.fixture
def api(tmp_path):
    """A catalogue of three seasons of one show, a film older than the catalogue,
    and an unrelated title - with MAL's relations between them."""
    data = tmp_path / "data"
    catalogue = [
        _title("wb_s1", 100, "Show", 2022),
        _title("wb_s2", 200, "Show 2nd Season", 2024),
        _title("wb_sp", 300, "Show Special", 2024, month=9),
        _title("wb_lone", 900, "Unrelated", 2025),
        _title("wb_nomal", None, "No MAL id", 2025),
    ]
    path = data / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-11" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(catalogue), path)

    relations = [
        _edge(100, 50, "prequel"),      # the film, older than the catalogue
        _edge(100, 200, "sequel"),
        _edge(200, 100, "prequel"),
        _edge(300, 200, "parent_story"),  # only the special names this link
        _edge(900, 100, "character"),     # a cameo: not a franchise link
    ]
    out = data / "processed" / "mal_relations" / "2026-09-11"
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(relations, schema=SCHEMA), out / "from-100.parquet")
    build_franchises(data)
    db = tmp_path / "warehouse.duckdb"
    refresh_catalog(data, db)

    def override():
        con = duckdb.connect(str(db), read_only=True)
        try:
            yield con
        finally:
            con.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_franchise_comes_oldest_first_with_titles_older_than_the_catalogue(api):
    body = api.get("/anime/wb_s2/franchise").json()

    assert body["franchise_id"] == "fr_50"
    assert [(e["mal_id"], e["wb_id"], e["title"]) for e in body["entries"]] == [
        (50, None, "MAL 50"),              # 2019-06, from MAL's description
        (100, "wb_s1", "Show"),            # 2022-04-01
        (200, "wb_s2", "Show 2nd Season"),
        (300, "wb_sp", "Show Special"),    # 2024-09-01
    ]
    film = body["entries"][0]
    assert (film["format"], film["start_date"], film["poster_url"], film["score_100"]) == (
        "movie", "2019-06", "https://mal/50.jpg", None)


def test_each_entry_says_how_it_relates_to_the_title_asked_about(api):
    entries = {e["mal_id"]: e for e in api.get("/anime/wb_s2/franchise").json()["entries"]}

    assert entries[100]["relation"] == "prequel"      # from this title's own list
    assert entries[300]["relation"] == "side_story"   # only the special named it: read from its side
    assert entries[50]["relation"] is None            # the prequel's prequel: not linked directly
    assert entries[200]["is_this"] and not entries[100]["is_this"]


def test_a_title_in_no_franchise_has_an_empty_one_not_an_error(api):
    """A cameo link is not a franchise, and having no sequels is not a failure."""
    for wb_id in ("wb_lone", "wb_nomal"):
        response = api.get(f"/anime/{wb_id}/franchise")
        assert response.status_code == 200
        assert response.json() == {"franchise_id": None, "entries": []}


def test_an_unknown_title_is_a_404(api):
    assert api.get("/anime/wb_nope/franchise").status_code == 404


def test_the_source_key_route_still_answers_beside_it(api):
    """/{wb_id}/franchise and /{source}/{source_id} are both two segments; the
    franchise route must not swallow a source key that happens to be the word."""
    assert api.get("/anime/kitsu/wb_s1").json()["wb_id"] == "wb_s1"
