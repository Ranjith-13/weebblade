"""AniList's airing schedule: the episodes countdowns are built from."""

import json

import pyarrow.parquet as pq

from ingestion.anilist import fetch_airing as fa


def _node(schedule_id, anilist_id, episode, at, *, mal=None, adult=False, fmt="TV", english=None, romaji="Romaji"):
    return {
        "id": schedule_id, "episode": episode, "airingAt": at,
        "media": {"id": anilist_id, "idMal": mal, "isAdult": adult, "format": fmt, "episodes": 12,
                  "title": {"romaji": romaji, "english": english},
                  "coverImage": {"medium": f"https://s4.anilist.co/{anilist_id}.jpg"}},
    }


class _AniList:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def query(self, query, variables):
        self.asked.append(variables)
        page = self.pages[variables["page"] - 1]
        return {"Page": {"pageInfo": {"hasNextPage": variables["page"] < len(self.pages)},
                         "airingSchedules": page}}


def test_the_window_runs_from_the_run_for_the_set_number_of_days(tmp_path):
    client = _AniList([[]])

    fa.land_airing(tmp_path, "2026-09-14", 1_789_000_000, client)

    assert client.asked[0]["from"] == 1_789_000_000
    assert client.asked[0]["to"] == 1_789_000_000 + fa.WINDOW_DAYS * 86400


def test_every_page_is_read_and_an_episode_listed_twice_is_kept_once():
    client = _AniList([[_node(1, 10, 5, 100), _node(2, 11, 3, 200)], [_node(2, 11, 3, 200), _node(3, 12, 1, 300)]])

    found = fa.fetch_airing(0, 1000, client)

    assert [n["id"] for n in found] == [1, 2, 3]
    assert [v["page"] for v in client.asked] == [1, 2]


def test_adult_titles_are_left_out_as_the_season_query_leaves_them_out():
    found = fa.fetch_airing(0, 1000, _AniList([[_node(1, 10, 5, 100), _node(2, 11, 1, 200, adult=True)]]))

    assert [n["id"] for n in found] == [1]


def test_an_episode_carries_enough_to_draw_a_title_the_catalogue_lacks():
    row = fa.flatten_airing(_node(1, 21, 1150, 1_789_500_000, mal=21, fmt="TV_SHORT", english="ONE PIECE"),
                            "2026-09-14")

    assert row == {"anilist_id": 21, "mal_id": 21, "episode": 1150, "airing_at": 1_789_500_000,
                   "title": "ONE PIECE", "format": "TV", "episodes": 12,
                   "poster_url": "https://s4.anilist.co/21.jpg", "fetched_on": "2026-09-14"}
    assert fa.flatten_airing(_node(1, 5, 1, 0), "d")["title"] == "Romaji"


def test_a_run_lands_raw_and_processed_under_its_date(tmp_path):
    fa.land_airing(tmp_path, "2026-09-14", 0, _AniList([[_node(1, 10, 5, 100)]]))

    raw = json.loads((tmp_path / "raw" / "anilist_airing" / "2026-09-14.json").read_text())
    rows = pq.read_table(tmp_path / "processed" / "anilist_airing" / "2026-09-14.parquet").to_pylist()
    assert raw[0]["id"] == 1
    assert [(r["anilist_id"], r["episode"], r["fetched_on"]) for r in rows] == [(10, 5, "2026-09-14")]


def test_a_run_that_finds_nothing_still_writes_a_readable_file(tmp_path):
    """The warehouse view reads every column by name; a file with none would
    break it the first quiet week."""
    fa.land_airing(tmp_path, "2026-09-14", 0, _AniList([[]]))

    table = pq.read_table(tmp_path / "processed" / "anilist_airing" / "2026-09-14.parquet")
    assert table.num_rows == 0
    assert table.schema.names == fa.SCHEMA.names
