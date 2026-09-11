"""Franchises: titles joined into groups by MAL's story relations."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ingestion.mal.fetch_relations import SCHEMA
from processing.duckdb_catalog import refresh_catalog
from processing.franchise import build_franchises, franchises, latest_relations


def _edge(mal_id, related=None, relation=None, fetched_on="2026-09-11", **over):
    row = {
        "mal_id": mal_id, "title": f"T{mal_id}", "format": "TV", "start_date": "2024", "poster_url": None,
        "related_mal_id": related, "relation_type": relation,
        "related_title": f"T{related}" if related else None, "related_format": "movie" if related else None,
        "related_start_date": "2019" if related else None, "related_poster_url": None,
        "fetched_on": fetched_on,
    }
    row.update(over)
    return row


def _land(data_dir: Path, run_date: str, rows: list[dict]) -> None:
    out = data_dir / "processed" / "mal_relations" / run_date
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), out / f"from-{rows[0]['mal_id']}.parquet")


def _groups(members):
    groups = {}
    for m in members:
        groups.setdefault(m["franchise_id"], set()).add(m["mal_id"])
    return groups


def test_story_relations_join_a_chain_under_its_oldest_id():
    members = franchises([
        _edge(30, 20, "prequel"), _edge(20, 10, "prequel"), _edge(20, 30, "sequel"), _edge(40, 20, "side_story"),
    ])

    assert _groups(members) == {"fr_10": {10, 20, 30, 40}}


def test_character_and_other_links_do_not_merge_franchises():
    """A cameo special or a collaboration music video would otherwise chain
    unrelated franchises into one."""
    members = franchises([
        _edge(1, 2, "sequel"),
        _edge(8, 9, "sequel"),
        _edge(2, 9, "character"),
        _edge(1, 8, "other"),
    ])

    assert _groups(members) == {"fr_1": {1, 2}, "fr_8": {8, 9}}


def test_a_title_older_than_the_catalogue_is_a_member_with_what_mal_says_about_it():
    [old, new] = franchises([_edge(50, 7, "prequel")])

    assert (old["mal_id"], old["title"], old["format"], old["start_date"]) == (7, "T7", "movie", "2019")
    assert (new["mal_id"], new["size"]) == (50, 2)


def test_a_title_with_nothing_story_related_is_in_no_franchise():
    assert franchises([_edge(1), _edge(2, 3, "other")]) == []


def test_the_latest_fetch_is_a_titles_whole_current_list(tmp_path):
    """A relation MAL dropped between fetches is dropped here, not kept forever."""
    _land(tmp_path, "2026-09-01", [_edge(1, 2, "sequel", fetched_on="2026-09-01")])
    _land(tmp_path, "2026-09-11", [_edge(1, 3, "sequel", fetched_on="2026-09-11")])

    rows = latest_relations(tmp_path)

    assert [(r["mal_id"], r["related_mal_id"]) for r in rows] == [(1, 3)]


def test_the_built_table_and_the_relations_are_views_in_the_warehouse(tmp_path):
    _land(tmp_path, "2026-09-11", [_edge(20, 10, "prequel"), _edge(20, 30, "sequel")])
    build_franchises(tmp_path)

    views = refresh_catalog(tmp_path, tmp_path / "warehouse.duckdb")

    assert {"anime_relation", "franchise_member"} <= set(views)
    import duckdb

    con = duckdb.connect(str(tmp_path / "warehouse.duckdb"), read_only=True)
    assert con.execute("SELECT COUNT(*), MIN(franchise_id) FROM franchise_member").fetchone() == (3, "fr_10")
    assert con.execute("SELECT COUNT(*) FROM anime_relation").fetchone() == (2,)


def test_nothing_fetched_builds_nothing(tmp_path):
    assert build_franchises(tmp_path) is None
