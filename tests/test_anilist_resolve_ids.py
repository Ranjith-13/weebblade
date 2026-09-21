"""AniList ids found by title search, for the airing titles the daily status
check has no id to ask by."""

import duckdb
import pytest

from ingestion.anilist import resolve_ids as ri


def _warehouse(tmp_path, titles):
    """A data directory whose warehouse holds the columns the search reads.
    A title is (wb_id, title_english, title_romaji, format, year, merged_status,
    anilist_status)."""
    path = tmp_path / "data" / "warehouse.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE t (wb_id VARCHAR, title_english VARCHAR, title_romaji VARCHAR, "
        "format VARCHAR, season_year BIGINT, start_year BIGINT, start_month BIGINT, "
        "start_day BIGINT, merged_status VARCHAR, anilist_status VARCHAR)"
    )
    for wb_id, english, romaji, fmt, year, merged, anilist in titles:
        con.execute(
            "INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [wb_id, english, romaji, fmt, year, year, 4, 1, merged, anilist],
        )
    con.execute("CREATE VIEW anime_media_latest AS SELECT * FROM t")
    con.close()
    return path.parent


def _media(anilist_id, romaji, fmt="ONA", year=2022, english=None, mal_id=None):
    return {
        "id": anilist_id,
        "idMal": mal_id,
        "title": {"romaji": romaji, "english": english},
        "format": fmt,
        "seasonYear": year,
        "startDate": {"year": year, "month": 4, "day": 1},
    }


class _AniList:
    """Answers each search with whatever the test says that title returns."""

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def query(self, query, variables):
        self.asked.append(variables["q"])
        return {"Page": {"media": self.answers.get(variables["q"], [])}}


def test_an_exact_title_of_the_same_format_and_year_is_accepted(tmp_path):
    data_dir = _warehouse(tmp_path, [("wb_a", None, "Demon Rush", "ONA", 2022, "current", None)])
    client = _AniList({"Demon Rush": [_media(700, "Demon Rush")]})

    assert ri.land_resolved(data_dir, "2026-09-21", client=client) == 1
    assert ri.resolved_ids(data_dir) == {"wb_a": 700}


def test_the_same_title_in_another_year_is_refused(tmp_path):
    """Music videos and specials reuse names from one year to the next, which is
    why matching.py keys on the year at all."""
    data_dir = _warehouse(tmp_path, [("wb_a", None, "Moonlight", "music", 2024, "current", None)])
    client = _AniList({"Moonlight": [_media(700, "Moonlight", fmt="MUSIC", year=2019)]})

    assert ri.land_resolved(data_dir, "2026-09-21", client=client) == 0
    assert ri.resolved_ids(data_dir) == {}


def test_two_entries_under_one_name_are_refused_rather_than_guessed_between(tmp_path):
    data_dir = _warehouse(tmp_path, [("wb_a", None, "Dragon Raja", "TV", 2022, "current", None)])
    client = _AniList(
        {"Dragon Raja": [_media(700, "Dragon Raja", fmt="TV"), _media(701, "Dragon Raja", fmt="TV")]}
    )

    assert ri.land_resolved(data_dir, "2026-09-21", client=client) == 0
    assert ri.match(
        {"title_romaji": "Dragon Raja", "format": "TV", "season_year": 2022},
        [_media(700, "Dragon Raja", fmt="TV"), _media(701, "Dragon Raja", fmt="TV")],
    ) == (None, "ambiguous")


def test_only_titles_the_sources_call_airing_and_anilist_has_not_answered_for(tmp_path):
    data_dir = _warehouse(
        tmp_path,
        [
            ("wb_a", None, "Unanswered", "ONA", 2022, "current", None),
            ("wb_b", None, "Answered", "ONA", 2022, "current", "current"),
            ("wb_c", None, "Finished", "ONA", 2022, "finished", None),
        ],
    )

    assert [row["wb_id"] for row in ri.unresolved(data_dir, "2026-09-21")] == ["wb_a"]


def test_a_title_already_searched_for_is_not_searched_again(tmp_path):
    """Including one AniList had no entry for: a recorded miss is what stops the
    same fruitless search running every day."""
    data_dir = _warehouse(tmp_path, [("wb_a", None, "Nowhere", "ONA", 2022, "current", None)])
    client = _AniList({})

    ri.land_resolved(data_dir, "2026-09-21", client=client)

    assert ri.unresolved(data_dir, "2026-09-22") == []
    assert [row["wb_id"] for row in ri.unresolved(data_dir, "2026-11-30")] == ["wb_a"]


def test_the_budget_leaves_the_rest_for_the_next_run(tmp_path):
    data_dir = _warehouse(
        tmp_path,
        [(f"wb_{i}", None, f"Title {i}", "ONA", 2022, "current", None) for i in range(5)],
    )
    client = _AniList({})

    ri.land_resolved(data_dir, "2026-09-21", budget=2, client=client)

    assert client.asked == ["Title 0", "Title 1"]
    assert [row["wb_id"] for row in ri.unresolved(data_dir, "2026-09-21")] == ["wb_2", "wb_3", "wb_4"]


def test_a_later_search_replaces_an_earlier_answer(tmp_path):
    """A miss is retried monthly because AniList gains entries."""
    data_dir = _warehouse(tmp_path, [("wb_a", None, "Late Arrival", "ONA", 2022, "current", None)])

    ri.land_resolved(data_dir, "2026-09-21", client=_AniList({}))
    ri.land_resolved(
        data_dir, "2026-11-30", client=_AniList({"Late Arrival": [_media(700, "Late Arrival")]})
    )

    assert ri.resolved_ids(data_dir) == {"wb_a": 700}


def test_the_english_title_is_searched_and_matched_on(tmp_path):
    """Kitsu titles some of these in English only, and AniList files them under
    romaji - which is the case matching.py's display rule exists for."""
    data_dir = _warehouse(tmp_path, [("wb_a", "Ghost Meets Gal!", None, "TV", 2026, "current", None)])
    client = _AniList(
        {"Ghost Meets Gal!": [_media(700, "Yuurei to Gal", fmt="TV", year=2026, english="Ghost Meets Gal!")]}
    )

    assert ri.land_resolved(data_dir, "2026-09-21", client=client) == 1
    assert client.asked == ["Ghost Meets Gal!"]


@pytest.mark.parametrize("missing", ["format", "season_year"])
def test_a_title_with_nothing_to_match_on_is_recorded_as_unmatchable(missing):
    """Without a format or a year there is no key at all, and a bare title is
    exactly the fuzzy match matching.py refuses to make."""
    row = {"title_romaji": "Bebefinn", "format": "ONA", "season_year": 2022}
    row[missing] = None

    assert ri.match(row, [_media(700, "Bebefinn")]) == (None, "unmatchable")
