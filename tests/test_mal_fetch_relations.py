"""Fetching MAL's related titles - the edges of the franchise graph."""

import json

import pyarrow.parquet as pq
import pytest
import requests

from ingestion.mal import fetch_relations as fr


def _response(mal_id, related=(), title="Show", media_type="tv", start_date="2024-04-01"):
    return {
        "id": mal_id, "title": title, "media_type": media_type, "start_date": start_date,
        "main_picture": {"large": f"https://img/{mal_id}.jpg"},
        "related_anime": [
            {"relation_type": rel, "node": {"id": rid, "title": f"Title {rid}", "media_type": "movie",
                                            "start_date": "2019", "main_picture": {"medium": f"https://img/{rid}m.jpg"}}}
            for rid, rel in related
        ],
    }


def test_each_edge_carries_both_ends_in_the_catalogue_vocabulary():
    """A prequel older than the catalogue has to be drawable from the edge alone:
    its title, poster, format and date all ride along."""
    [row] = fr.flatten_relations(_response(10, [(5, "prequel")]), "2026-09-11")

    assert (row["mal_id"], row["related_mal_id"], row["relation_type"]) == (10, 5, "prequel")
    assert (row["format"], row["poster_url"]) == ("TV", "https://img/10.jpg")
    assert (row["related_title"], row["related_format"], row["related_start_date"]) == ("Title 5", "movie", "2019")
    assert row["related_poster_url"] == "https://img/5m.jpg"


def test_a_title_with_no_relations_is_still_recorded():
    """"Fetched, has none" is not "never fetched": only the second needs asking."""
    [row] = fr.flatten_relations(_response(10), "2026-09-11")

    assert row["mal_id"] == 10
    assert row["related_mal_id"] is None


def test_the_plan_fetches_the_new_first_then_what_can_still_change():
    catalogue = [(1, "finished"), (2, "current"), (3, "upcoming"), (4, "finished"), (5, "current")]

    ids = fr.plan(catalogue, fetched_ever={1, 2, 3, 5}, fetched_today={5})

    # 4 was never fetched; 2 and 3 can still gain sequels; 1 is finished and
    # known; 5 already landed today, so a resumed run skips it.
    assert ids == [4, 2, 3]


class _MAL:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def get(self, url, params=None):
        mal_id = int(url.rsplit("/", 1)[1])
        self.asked.append(mal_id)
        answer = self.answers.get(mal_id, "ok")
        if answer == 404:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)
        if answer == "down":
            raise RuntimeError("MAL request failed after 5 attempts")
        return _response(mal_id, [(mal_id + 1000, "sequel")])


def test_each_chunk_lands_as_it_is_fetched_under_its_own_name(tmp_path):
    result = fr.fetch_relations([1, 2, 3], tmp_path, "2026-09-11", client=_MAL({}), chunk=2)

    processed = sorted(p.name for p in (tmp_path / "processed" / "mal_relations" / "2026-09-11").iterdir())
    raw = sorted(p.name for p in (tmp_path / "raw" / "mal_relations" / "2026-09-11").iterdir())
    assert processed == ["from-1.parquet", "from-3.parquet"]
    assert raw == ["from-1.json", "from-3.json"]
    assert (result.titles, result.edges) == (3, 3)
    assert json.loads((tmp_path / "raw" / "mal_relations" / "2026-09-11" / "from-3.json").read_text())[0]["id"] == 3


def test_a_title_gone_from_mal_is_recorded_so_it_is_not_asked_for_again(tmp_path):
    result = fr.fetch_relations([7], tmp_path, "2026-09-11", client=_MAL({7: 404}))

    rows = pq.read_table(tmp_path / "processed" / "mal_relations" / "2026-09-11" / "from-7.parquet").to_pylist()
    assert result.gone == [7]
    assert [(r["mal_id"], r["related_mal_id"]) for r in rows] == [(7, None)]


def test_one_failing_title_is_skipped_and_left_for_the_next_run(tmp_path):
    result = fr.fetch_relations([1, 2, 3], tmp_path, "2026-09-11", client=_MAL({2: "down"}))

    assert result.failed == [2]
    rows = pq.read_table(tmp_path / "processed" / "mal_relations" / "2026-09-11" / "from-1.parquet").to_pylist()
    assert sorted({r["mal_id"] for r in rows}) == [1, 3]  # 2 not recorded, so it is retried


def test_a_run_of_failures_stops_the_fetch_and_keeps_what_landed(tmp_path):
    """Ten failures in a row is a refused key or MAL being down, not ten awkward
    titles. Stopping says so; grinding through 5,000 more would not."""
    answers = {i: "down" for i in range(3, 20)}
    client = _MAL(answers)

    with pytest.raises(RuntimeError, match="in a row"):
        fr.fetch_relations(list(range(1, 30)), tmp_path, "2026-09-11", client=client, chunk=50)

    assert len(client.asked) == 12  # 1, 2, then ten failures
    rows = pq.read_table(tmp_path / "processed" / "mal_relations" / "2026-09-11" / "from-1.parquet").to_pylist()
    assert sorted({r["mal_id"] for r in rows}) == [1, 2]
