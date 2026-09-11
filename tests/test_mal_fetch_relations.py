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
        if answer == "slow":
            raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=30)")
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


def test_a_timeout_is_one_failed_title_not_a_failed_run(tmp_path):
    """The first full fetch died on a single read timeout inside its first chunk
    of a 73-minute job, and landed nothing."""
    result = fr.fetch_relations([1, 2, 3], tmp_path, "2026-09-11", client=_MAL({2: "slow"}))

    assert result.failed == [2]
    assert result.titles == 2


# --- past the catalogue ----------------------------------------------------------------

import pyarrow as pa  # noqa: E402

from processing.duckdb_catalog import refresh_catalog  # noqa: E402


def test_the_frontier_comes_after_the_catalogue_and_skips_what_is_known():
    ids = fr.plan([(10, "finished")], fetched_ever={10, 7}, fetched_today=set(), story_related={5, 7, 10})

    # 5 is named by a fetched title and never fetched itself; 7 was fetched
    # already; 10 is catalogue, and finished.
    assert ids == [5]


class _Graph:
    """MAL as a small graph: 30 is the catalogue's sequel, 20 and 10 the seasons
    before it, 99 a cameo special linked by shared characters only."""

    EDGES = {30: [(20, "prequel"), (99, "character")], 20: [(10, "prequel"), (30, "sequel")],
             10: [(20, "sequel")], 99: []}

    def __init__(self, fail=()):
        self.asked, self.fail = [], set(fail)

    def get(self, url, params=None):
        mal_id = int(url.rsplit("/", 1)[1])
        self.asked.append(mal_id)
        if mal_id in self.fail:
            raise RuntimeError("MAL request failed after 5 attempts")
        return _response(mal_id, self.EDGES[mal_id])


def _catalogue(tmp_path, *mal_ids):
    rows = [{"source": "mal", "source_id": str(m), "mal_id": m, "status": "finished",
             "title_english": f"T{m}", "run_date": "2026-09-11"} for m in mal_ids]
    path = tmp_path / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-11" / "p.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    refresh_catalog(tmp_path, tmp_path / "warehouse.duckdb")


def test_passes_follow_story_relations_back_to_the_first_season(tmp_path):
    """Fetching only the catalogue stopped at the prequel's door: Laid-Back Camp 3
    reached Season 2 and never Season 1."""
    _catalogue(tmp_path, 30)
    mal = _Graph()

    result = fr.fetch_until_complete(tmp_path, "2026-09-11", client=mal)

    assert mal.asked == [30, 20, 10]  # one hop per pass, and never the cameo
    assert result.titles == 3


def test_a_budget_stops_the_passes(tmp_path):
    _catalogue(tmp_path, 30)
    mal = _Graph()

    fr.fetch_until_complete(tmp_path, "2026-09-11", budget=2, client=mal)

    assert mal.asked == [30, 20]


def test_a_failing_title_is_tried_once_a_run_not_once_a_pass(tmp_path):
    _catalogue(tmp_path, 30)
    mal = _Graph(fail={20})

    result = fr.fetch_until_complete(tmp_path, "2026-09-11", client=mal)

    assert mal.asked == [30, 20]
    assert result.failed == [20]
