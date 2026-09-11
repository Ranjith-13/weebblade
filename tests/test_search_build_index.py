from pathlib import Path

from ai.search.build_index import build_index
from processing.duckdb_catalog import refresh_catalog


def test_build_index_handles_missing_warehouse_file(tmp_path):
    count = build_index(tmp_path / "does-not-exist.duckdb", tmp_path / "chroma")

    assert count == 0


def test_build_index_handles_missing_view(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(tmp_path / "data", db_path)

    count = build_index(db_path, tmp_path / "chroma")

    assert count == 0


# --- rebuilding a live index ---------------------------------------------------------

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import pytest  # noqa: E402

import ai.search.build_index as build_module  # noqa: E402


class _FakeCollection:
    def __init__(self, client, name):
        self.client, self.name, self.ids = client, name, []

    def add(self, ids, embeddings, documents, metadatas):
        assert len(ids) <= self.client.max_batch, "a batch over the client's limit"
        self.client.adds.append(len(ids))
        if self.client.fail_on_add == len(self.client.adds):
            raise RuntimeError("chroma refused the batch")
        self.ids += ids

    def modify(self, name):
        self.client.cols[name] = self.client.cols.pop(self.name)
        self.name = name


class _FakeClient:
    """Chroma's surface as build_index uses it, with Chroma's batch limit."""

    def __init__(self, max_batch=3, fail_on_add=None):
        self.max_batch, self.fail_on_add, self.cols, self.adds = max_batch, fail_on_add, {}, []

    def get_max_batch_size(self):
        return self.max_batch

    def list_collections(self):
        return list(self.cols.values())

    def create_collection(self, name):
        self.cols[name] = _FakeCollection(self, name)
        return self.cols[name]

    def delete_collection(self, name):
        del self.cols[name]


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    """A warehouse of `n` titles, and an index client standing in for Chroma."""

    def build(n: int, client: _FakeClient):
        rows = [
            {"source": "kitsu", "source_id": str(i), "title_english": f"Title {i}", "title_romaji": None,
             "genres": ["Drama"], "synopsis": "A story.", "run_date": "2026-09-11"}
            for i in range(n)
        ]
        path = tmp_path / "data" / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-11" / "p.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path)
        refresh_catalog(tmp_path / "data", tmp_path / "warehouse.duckdb")
        monkeypatch.setattr("ai.search.client.get_chroma_client", lambda chroma_dir: client)
        monkeypatch.setattr(build_module, "embed_texts", lambda docs: [[0.0]] * len(docs))
        return tmp_path / "warehouse.duckdb"

    return build


def test_titles_go_in_batches_the_client_accepts(warehouse, tmp_path):
    """The backfill took the catalogue to 6,055 titles, past Chroma's limit of
    5,461 per add, and a single add of everything was refused."""
    client = _FakeClient(max_batch=3)

    count = build_index(warehouse(7, client), tmp_path / "chroma")

    assert count == 7
    assert client.adds == [3, 3, 1]
    assert len(client.cols["anime_media"].ids) == 7


def test_a_failed_rebuild_leaves_the_live_index_serving(warehouse, tmp_path):
    """The live collection used to be deleted before the new one was filled, so
    when the fill failed, search answered every query with nothing."""
    client = _FakeClient(max_batch=3, fail_on_add=2)
    live = client.create_collection("anime_media")
    live.ids = ["kitsu:old"]
    db = warehouse(7, client)

    with pytest.raises(RuntimeError):
        build_index(db, tmp_path / "chroma")

    assert client.cols["anime_media"].ids == ["kitsu:old"]


def test_a_successful_rebuild_replaces_the_live_index_and_any_leftover(warehouse, tmp_path):
    client = _FakeClient(max_batch=10)
    client.create_collection("anime_media").ids = ["kitsu:old"]
    client.create_collection("anime_media__building").ids = ["kitsu:half-built"]
    db = warehouse(4, client)

    build_index(db, tmp_path / "chroma")

    assert sorted(client.cols) == ["anime_media"]
    # Sorted: the warehouse scan has no defined row order, and CI reads it differently.
    assert sorted(client.cols["anime_media"].ids) == [f"kitsu:{i}" for i in range(4)]
