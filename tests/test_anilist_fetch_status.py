"""AniList's own status for the titles the catalogue calls airing."""

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from ingestion.anilist import fetch_status as fs


def _warehouse(tmp_path, titles, corrected=None):
    """A data directory holding a warehouse with just the view the check reads.
    `corrected` gives the status the warehouse serves where the check has
    overruled the sources. A title is (source_keys, mal_id, merged_status) or
    that with a wb_id first."""
    path = tmp_path / "data" / "warehouse.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE t (wb_id VARCHAR, source_keys VARCHAR[], mal_id BIGINT, "
        "merged_status VARCHAR, status VARCHAR)"
    )
    for title in titles:
        wb_id, keys, mal_id, merged = title if len(title) == 4 else (None, *title)
        con.execute(
            "INSERT INTO t VALUES (?, ?, ?, ?, ?)",
            [wb_id, keys, mal_id, merged, (corrected or {}).get(mal_id, merged)],
        )
    con.execute("CREATE VIEW anime_media_latest AS SELECT * FROM t")
    con.close()
    return path.parent


def _resolved(data_dir, rows, searched_on="2026-09-21"):
    """What resolve_ids has written: (wb_id, anilist_id), the id null for a miss."""
    from ingestion.anilist.resolve_ids import SCHEMA

    out = data_dir / "processed" / "anilist_resolved"
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"wb_id": wb_id, "anilist_id": anilist_id,
                 "matched_by": "romaji" if anilist_id else "no match",
                 "title": wb_id, "searched_on": searched_on}
                for wb_id, anilist_id in rows
            ],
            schema=SCHEMA,
        ),
        out / f"{searched_on}.parquet",
    )


class _AniList:
    def __init__(self, known):
        self.known, self.asked = known, []

    def query(self, query, variables):
        by_mal = "idMal_in" in query
        self.asked.append(("mal" if by_mal else "anilist", list(variables["ids"])))
        media = [m for m in self.known if (m["idMal"] if by_mal else m["id"]) in variables["ids"]]
        return {"Page": {"media": media}}


def _media(anilist_id, mal_id, status, end=None, score=None, popularity=None):
    return {"id": anilist_id, "idMal": mal_id, "status": status, "averageScore": score,
            "popularity": popularity,
            "endDate": dict(zip(("year", "month", "day"), end or (None, None, None)))}


def test_only_titles_the_catalogue_calls_airing_are_asked_about(tmp_path):
    data_dir = _warehouse(tmp_path, [
        (["anilist:1", "kitsu:1"], 10, "current"),
        (["kitsu:2", "mal:20"], 20, "current"),      # no AniList id: asked by MAL id
        (["anilist:3", "mal:30"], 30, "finished"),   # already finished: no need to ask
        (["kitsu:4"], None, "current"),              # nothing to ask by
    ])

    assert fs.candidates(data_dir) == ([1], [20])


def test_a_title_the_check_has_overruled_is_still_asked_about(tmp_path):
    """Asked by the corrected status, a title AniList called finished yesterday
    would not be asked today, read as airing again tomorrow, and flip daily."""
    data_dir = _warehouse(tmp_path, [(["anilist:1"], 10, "current")], corrected={10: "finished"})

    assert fs.candidates(data_dir) == ([1], [])


def test_an_id_found_by_search_is_asked_about_the_day_it_is_found(tmp_path):
    """The 19 titles with no usable id at all had no way into this check. An id
    resolve_ids found is read from its files, not from the warehouse view the
    weekly refresh makes, so it is used the same day."""
    data_dir = _warehouse(tmp_path, [("wb_a", ["kitsu:4"], None, "current")])
    _resolved(data_dir, [("wb_a", 44), ("wb_b", 55)])  # wb_b is not airing

    assert fs.candidates(data_dir) == ([44], [])


def test_a_title_searched_for_and_not_found_is_still_asked_by_its_mal_id(tmp_path):
    """A recorded miss says AniList has no entry under that title. It must not
    take away the MAL id the check would otherwise have asked by."""
    data_dir = _warehouse(tmp_path, [("wb_a", ["kitsu:4"], 40, "current")])
    _resolved(data_dir, [("wb_a", None)])

    assert fs.candidates(data_dir) == ([], [40])


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
    assert dated == current == [{"anilist_id": 1, "mal_id": 10, "status": "finished", "score_100": None,
                                 "user_count": None, "ended_on": "2026-09-10",
                                 "fetched_on": "2026-09-14"}]


def test_a_check_that_finds_nothing_still_writes_a_readable_file(tmp_path):
    _warehouse(tmp_path, [])

    fs.land_status(tmp_path / "data", "2026-09-14", _AniList([]))

    table = pq.read_table(tmp_path / "data" / "processed" / "anilist_status" / "2026-09-14.parquet")
    assert (table.num_rows, table.schema.names) == (0, fs.SCHEMA.names)


def test_the_score_and_its_vote_count_ride_along_on_the_status_check(tmp_path):
    """The whole point of #2: no extra request, two more fields on the query
    that was already going out every morning."""
    assert "averageScore" in fs._FIELDS and "popularity" in fs._FIELDS

    _warehouse(tmp_path, [(["anilist:1"], 10, "current")])
    fs.land_status(
        tmp_path / "data", "2026-10-16",
        _AniList([_media(1, 10, "RELEASING", score=78, popularity=40_112)]),
    )

    row = pq.read_table(
        tmp_path / "data" / "processed" / "anilist_status" / "2026-10-16.parquet"
    ).to_pylist()[0]
    # Out of 100, which is the scale the warehouse stores; /10 is display only.
    assert (row["score_100"], row["user_count"]) == (78, 40_112)


def test_a_title_nobody_has_rated_yet_carries_no_score_rather_than_a_zero():
    """A premiere with no rating has not been measured. Zero would be a
    measurement, and would drag any average it ever reached."""
    row = fs.flatten_status(_media(1, 10, "RELEASING", score=None, popularity=3), "2026-10-16")

    assert row["score_100"] is None
    assert row["user_count"] == 3


# THE SEASON JUST ENDED IS WHERE SCORES MOVE MOST
#
# Measured over the catalogue's own history: 51% of the airing season's TV
# titles had visibly moved their score against 71% of the season just ended -
# votes keep arriving for weeks after a finale and the average is still
# settling. Asking only about titles the sources call current stopped watching
# each show at the point it moves fastest.
#
# Defined by the episode archive rather than by season arithmetic, because "the
# season just ended" is a nuisance to compute - a show is filed under the
# quarter it began and may finish two quarters later - while "an episode went
# out recently" is a fact anime_airing_history already holds per title.


def _with_archive(data_dir, episodes):
    """Add the episode archive the cohort is widened by: (wb_id, days_ago)."""
    con = duckdb.connect(str(data_dir / "warehouse.duckdb"))
    con.execute("CREATE TABLE h (wb_id VARCHAR, airing_at BIGINT, episode INTEGER)")
    for wb_id, days_ago in episodes:
        con.execute(
            "INSERT INTO h VALUES (?, epoch(now() - INTERVAL (?) DAY)::BIGINT, 1)",
            [wb_id, days_ago],
        )
    con.execute("CREATE VIEW anime_airing_history AS SELECT * FROM h")
    con.close()
    return data_dir


def test_a_title_that_finished_recently_is_still_asked_about(tmp_path):
    data_dir = _warehouse(tmp_path, [
        ("wb_1", ["anilist:1"], 10, "current"),
        ("wb_2", ["anilist:2"], 20, "finished"),   # finished, but aired this month
    ])
    _with_archive(data_dir, [("wb_1", 2), ("wb_2", 10)])

    assert fs.candidates(data_dir) == ([1, 2], [])


def test_a_title_whose_last_episode_is_long_past_is_left_alone(tmp_path):
    """The window has to end somewhere, or the cohort grows without limit and
    the check spends its requests on shows nobody is still rating."""
    data_dir = _warehouse(tmp_path, [
        ("wb_1", ["anilist:1"], 10, "current"),
        ("wb_2", ["anilist:2"], 20, "finished"),
    ])
    _with_archive(data_dir, [("wb_1", 2), ("wb_2", fs.RECENT_DAYS + 5)])

    assert fs.candidates(data_dir) == ([1], [])


def test_a_future_episode_does_not_pull_a_title_in(tmp_path):
    """The archive holds the weeks ahead as well as behind. A title whose only
    episode is scheduled rather than aired has nothing to have moved yet."""
    data_dir = _warehouse(tmp_path, [("wb_2", ["anilist:2"], 20, "finished")])
    _with_archive(data_dir, [("wb_2", -7)])

    assert fs.candidates(data_dir) == ([], [])


def test_without_the_archive_the_cohort_is_what_it_always_was(tmp_path):
    """A warehouse built before the archive existed has no such view, and the
    check must not go down over it: it is the only thing correcting a finished
    show's status, and 986 finished titles once counted down to a slot for a
    series that was over."""
    data_dir = _warehouse(tmp_path, [
        ("wb_1", ["anilist:1"], 10, "current"),
        ("wb_2", ["anilist:2"], 20, "finished"),
    ])

    assert fs.candidates(data_dir) == ([1], [])
