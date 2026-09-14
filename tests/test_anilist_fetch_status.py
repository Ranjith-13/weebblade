"""AniList's own status for the titles the catalogue calls airing."""

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from ingestion.anilist import fetch_status as fs


def _warehouse(tmp_path, titles, corrected=None):
    """A warehouse with just the view the check reads. `corrected` gives the
    status the warehouse serves where the check has overruled the sources."""
    path = tmp_path / "data" / "warehouse.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (source_keys VARCHAR[], mal_id BIGINT, merged_status VARCHAR, status VARCHAR)")
    for keys, mal_id, merged in titles:
        con.execute("INSERT INTO t VALUES (?, ?, ?, ?)", [keys, mal_id, merged, (corrected or {}).get(mal_id, merged)])
    con.execute("CREATE VIEW anime_media_latest AS SELECT * FROM t")
    con.close()
    return path


class _AniList:
    def __init__(self, known):
        self.known, self.asked = known, []

    def query(self, query, variables):
        by_mal = "idMal_in" in query
        self.asked.append(("mal" if by_mal else "anilist", list(variables["ids"])))
        media = [m for m in self.known if (m["idMal"] if by_mal else m["id"]) in variables["ids"]]
        return {"Page": {"media": media}}


def _media(anilist_id, mal_id, status, end=None):
    return {"id": anilist_id, "idMal": mal_id, "status": status,
            "endDate": dict(zip(("year", "month", "day"), end or (None, None, None)))}


def test_only_titles_the_catalogue_calls_airing_are_asked_about(tmp_path):
    db = _warehouse(tmp_path, [
        (["anilist:1", "kitsu:1"], 10, "current"),
        (["kitsu:2", "mal:20"], 20, "current"),      # no AniList id: asked by MAL id
        (["anilist:3", "mal:30"], 30, "finished"),   # already finished: no need to ask
        (["kitsu:4"], None, "current"),              # nothing to ask by
    ])

    assert fs.candidates(db) == ([1], [20])


def test_a_title_the_check_has_overruled_is_still_asked_about(tmp_path):
    """Asked by the corrected status, a title AniList called finished yesterday
    would not be asked today, read as airing again tomorrow, and flip daily."""
    db = _warehouse(tmp_path, [(["anilist:1"], 10, "current")], corrected={10: "finished"})

    assert fs.candidates(db) == ([1], [])


def test_ids_are_asked_in_chunks_and_a_title_answered_twice_is_kept_once():
    known = [_media(i, 1000 + i, "RELEASING") for i in range(1, 121)]
    client = _AniList(known)

    found = fs.fetch_status(list(range(1, 121)), [1001], client)

    assert [len(ids) for kind, ids in client.asked] == [50, 50, 20, 1]
    assert len(found) == 120  # 1001 is anilist:1 again


def test_statuses_arrive_in_the_catalogues_words_and_keep_the_two_it_lacks():
    words = [fs.flatten_status(_media(1, None, s), "d")["status"]
             for s in ("FINISHED", "RELEASING", "NOT_YET_RELEASED", "CANCELLED", "HIATUS")]

    assert words == ["finished", "current", "upcoming", "cancelled", "hiatus"]


def test_an_end_date_is_kept_to_the_precision_anilist_has_it():
    ended = lambda end: fs.flatten_status(_media(1, None, "FINISHED", end), "d")["ended_on"]  # noqa: E731

    assert [ended((2026, 9, 10)), ended((2026, 9, None)), ended((2026, None, 4)), ended(None)] == [
        "2026-09-10", "2026-09", "2026", None]
    # A month and day with no year is no date at all, not "09-10".
    assert ended((None, 9, 10)) is None


def test_a_check_lands_under_its_date(tmp_path):
    _warehouse(tmp_path, [(["anilist:1"], 10, "current")])

    fs.land_status(tmp_path / "data", "2026-09-14", _AniList([_media(1, 10, "FINISHED", (2026, 9, 10))]))

    dated = pq.read_table(tmp_path / "data" / "processed" / "anilist_status" / "2026-09-14.parquet").to_pylist()
    current = pq.read_table(tmp_path / "data" / "processed" / "current" / "anilist_status.parquet").to_pylist()
    assert dated == current == [{"anilist_id": 1, "mal_id": 10, "status": "finished", "ended_on": "2026-09-10",
                                 "fetched_on": "2026-09-14"}]


def test_a_check_that_finds_nothing_still_writes_a_readable_file(tmp_path):
    _warehouse(tmp_path, [])

    fs.land_status(tmp_path / "data", "2026-09-14", _AniList([]))

    table = pq.read_table(tmp_path / "data" / "processed" / "anilist_status" / "2026-09-14.parquet")
    assert (table.num_rows, table.schema.names) == (0, fs.SCHEMA.names)
