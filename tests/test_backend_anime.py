from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db
from backend.app.main import app
from processing.duckdb_catalog import refresh_catalog


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


@pytest.fixture
def client(tmp_path):
    data_dir = tmp_path / "data"
    _write_parquet(
        data_dir
        / "processed"
        / "anime_media_consolidated"
        / "2026-SUMMER"
        / "2026-09-07"
        / "part-0.parquet",
        [
            {
                "source": "kitsu",
                "source_id": "1",
                "title_english": "Demon Slayer",
                "title_romaji": None,
                "score_100": 84.0,
                "popularity": 500.0,
                "genres": ["Action", "Fantasy"],
                "format": "TV",
                "season": "SUMMER",
                "season_year": 2026,
                "run_date": "2026-09-07",
            },
            {
                "source": "kitsu",
                "source_id": "2",
                "title_english": "Frieren",
                "title_romaji": None,
                "score_100": 90.0,
                "popularity": 300.0,
                "genres": ["Fantasy", "Drama"],
                "format": "TV",
                "season": "SUMMER",
                "season_year": 2026,
                "run_date": "2026-09-07",
            },
        ],
    )
    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(data_dir, db_path)

    def override_get_db():
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            yield con
        finally:
            con.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_anime_sorted_by_score_desc_by_default(client):
    response = client.get("/anime")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert [item["title_english"] for item in data["items"]] == ["Frieren", "Demon Slayer"]


def test_list_anime_filters_by_genre_case_insensitively(client):
    response = client.get("/anime", params={"genre": "drama"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title_english"] == "Frieren"


def test_list_anime_respects_limit_and_offset(client):
    response = client.get("/anime", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["items"][0]["title_english"] == "Demon Slayer"


def test_get_anime_detail(client):
    response = client.get("/anime/kitsu/1")

    assert response.status_code == 200
    assert response.json()["title_english"] == "Demon Slayer"


def test_get_anime_not_found(client):
    response = client.get("/anime/kitsu/999")

    assert response.status_code == 404


def test_anime_endpoints_503_when_no_warehouse(tmp_path, monkeypatch):
    # Exercises the real get_db logic (not an override) - a missing warehouse file
    # is a legitimate early-project/all-sources-failed state, not a bug.
    import backend.app.db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "does-not-exist.duckdb")

    with TestClient(app) as test_client:
        response = test_client.get("/anime")

    assert response.status_code == 503


@pytest.fixture
def tied_client(tmp_path):
    """A catalogue that is almost entirely one tie block, spread over several
    parquet files — which is what the real lake looks like, and what it takes to
    reproduce the bug.

    Both details matter. The default fixture above has two rows with distinct
    scores in a single file, so it can never exercise ordering stability. A
    single file does not either: DuckDB reads one small file in a predictable
    order, and the test passes with or without the fix. It is the parallel scan
    across MULTIPLE files, over a large block of equal values, that leaves the
    row order genuinely undefined. Measured here without a tiebreaker: 400 rows
    paged back as 200-250 distinct ids, differing on every run."""
    files = 8
    per_file = 50
    partition = (
        tmp_path / "data" / "processed" / "anime_media_consolidated" / "2026-SUMMER" / "2026-09-07"
    )
    for f in range(files):
        _write_parquet(
            partition / f"part-{f}.parquet",
            [
                {
                    "source": "kitsu",
                    "source_id": str(f * per_file + i),
                    "title_english": f"Untitled {f * per_file + i:04d}",
                    "title_romaji": None,
                    # All NULL: every row ties with every other under score_desc.
                    "score_100": None,
                    "popularity": 1000.0,
                    "genres": ["Action"],
                    "format": "TV",
                    "season": "SUMMER",
                    "season_year": 2026,
                    "run_date": "2026-09-07",
                }
                for i in range(per_file)
            ],
        )
    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(tmp_path / "data", db_path)

    def override_get_db():
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            yield con
        finally:
            con.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


TIED_ROWS = 400


def _page_through(client, sort: str, limit: int = 100) -> list[str]:
    ids: list[str] = []
    offset = 0
    while True:
        response = client.get("/anime", params={"sort": sort, "limit": limit, "offset": offset})
        assert response.status_code == 200
        items = response.json()["items"]
        if not items:
            break
        ids.extend(item["source_id"] for item in items)
        offset += limit
    return ids


@pytest.mark.parametrize("sort", ["score_desc", "popularity_desc", "title"])
def test_paging_serves_every_row_exactly_once(tied_client, sort):
    """Regression test for unstable pagination.

    Without a unique tiebreaker, ORDER BY over a tie block has no defined order,
    so LIMIT/OFFSET re-slices a differently shuffled result on each query: rows
    get served twice while others are never served at all. Against the live API
    this was measured as three identical two-page fetches returning 126, 116 and
    122 distinct titles out of 142."""
    ids = _page_through(tied_client, sort)

    assert len(ids) == TIED_ROWS, "paging returned a different number of rows than exist"
    assert sorted(ids, key=int) == [
        str(i) for i in range(TIED_ROWS)
    ], "rows were duplicated or skipped while paging"


@pytest.mark.parametrize("sort", ["score_desc", "popularity_desc", "title"])
def test_ordering_is_reproducible_across_identical_queries(tied_client, sort):
    """The same query must return the same order every time, or a cached client
    and a fresh one disagree about what page 2 contains."""
    runs = [_page_through(tied_client, sort) for _ in range(5)]

    assert all(run == runs[0] for run in runs), f"{sort} ordering is not deterministic"


def test_list_columns_survive_a_row_written_before_those_columns_existed(tmp_path):
    """Regression: /anime returned 500 for any page containing a carried-over row.

    anime_media_latest keeps the newest row per title, so a title that stops
    appearing upstream is still served from an older snapshot. standardize_schema
    fills that snapshot's missing columns with typed NULLs on purpose - it is what
    makes backfills work - and a NULL array reaches Pydantic as None, which a bare
    list[str] rejects. In production this failed on item 58 of limit=100 while
    limit=50 passed, because the old rows sat past the first page.
    """
    from backend.app.schemas import Anime

    anime = Anime.model_validate(
        {
            "source": "kitsu",
            "source_id": "1",
            "genres": None,
            "studios": None,
            "streaming_services": None,
            "streaming_urls": None,
        }
    )

    assert anime.genres == []
    assert anime.studios == []
    assert anime.streaming_services == []
    assert anime.streaming_urls == []


def test_list_columns_pass_through_when_present():
    from backend.app.schemas import Anime

    anime = Anime.model_validate(
        {
            "source": "kitsu",
            "source_id": "1",
            "genres": ["Action"],
            "streaming_services": ["Crunchyroll"],
            "streaming_urls": ["https://www.crunchyroll.com/series/a"],
        }
    )

    assert anime.genres == ["Action"]
    assert anime.streaming_services == ["Crunchyroll"]


# --- stable identities ----------------------------------------------------------

from processing.identity import Registry, assign, save  # noqa: E402


def _client_for(tmp_path, rows, registry=None):
    data_dir = tmp_path / "data"
    _write_parquet(
        data_dir / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-16" / "part-0.parquet",
        rows,
    )
    if registry is not None:
        save(data_dir, registry)
    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(data_dir, db_path)

    def override_get_db():
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            yield con
        finally:
            con.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _title(**over):
    row = {
        "source": "kitsu", "source_id": "1", "title_english": "Frieren", "format": "TV",
        "season": "SUMMER", "season_year": 2026, "run_date": "2026-09-16", "genres": ["Drama"],
    }
    row.update(over)
    return row


def test_a_title_is_reachable_by_its_stable_identity(tmp_path):
    ids, reg, _ = assign([["kitsu:1", "mal:10"]], Registry(), "2026-09-16")
    client = _client_for(tmp_path, [_title(wb_id=ids[0], source_keys=["kitsu:1", "mal:10"])], reg)

    body = client.get(f"/anime/{ids[0]}").json()

    assert body["title_english"] == "Frieren"
    assert body["wb_id"] == ids[0]
    assert body["source_keys"] == ["kitsu:1", "mal:10"]


def test_a_key_that_lost_the_merge_still_finds_its_title(tmp_path):
    """The bug in the old route. mal:10 was folded into kitsu:1, so it is not the
    winner and never appears as (source, source_id) in the catalogue - and the
    old route answered 404 for a title that plainly existed."""
    ids, reg, _ = assign([["kitsu:1", "mal:10"]], Registry(), "2026-09-16")
    client = _client_for(tmp_path, [_title(wb_id=ids[0], source_keys=["kitsu:1", "mal:10"])], reg)

    response = client.get("/anime/mal/10")

    assert response.status_code == 200
    body = response.json()
    assert body["title_english"] == "Frieren"
    assert (body["source"], body["source_id"]) == ("kitsu", "1")  # visibly redirected


def test_an_identity_that_merged_away_resolves_to_the_title_that_absorbed_it(tmp_path):
    a, reg, _ = assign([["kitsu:1"]], Registry(), "2026-06-15")
    b, reg, _ = assign([["kitsu:1"], ["mal:10"]], reg, "2026-09-09")
    merged, reg, _ = assign([["kitsu:1", "mal:10"]], reg, "2026-09-16")
    client = _client_for(tmp_path, [_title(wb_id=merged[0], source_keys=["kitsu:1", "mal:10"])], reg)

    body = client.get(f"/anime/{b[1]}").json()

    assert body["wb_id"] == a[0]
    assert body["title_english"] == "Frieren"


def test_an_unknown_identity_is_a_404(tmp_path):
    ids, reg, _ = assign([["kitsu:1"]], Registry(), "2026-09-16")
    client = _client_for(tmp_path, [_title(wb_id=ids[0])], reg)

    assert client.get("/anime/wb_doesnotexist").status_code == 404


def test_before_any_identity_run_the_api_neither_breaks_nor_invents_ids(tmp_path):
    """Between deploying this code and the first pipeline run with identities,
    the warehouse has no registry and no wb_id column. Asking for an identity is
    then a plain 404 - not the 500 a missing column raises or the 503 a missing
    view does - and the old address keeps working exactly as it did."""
    client = _client_for(tmp_path, [_title()])

    assert client.get("/anime/wb_anything").status_code == 404
    legacy = client.get("/anime/kitsu/1")
    assert legacy.status_code == 200
    assert legacy.json()["wb_id"] is None
