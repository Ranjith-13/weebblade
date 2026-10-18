from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# Each view is a glob over that source's dated Parquet snapshots. Anything that opens
# the resulting DuckDB file (the backend, a notebook, the future digest script) just
# queries these as normal tables without needing to know the on-disk layout.
_VIEWS = {
    "anime_media": "processed/anime_media_consolidated/*/*/*.parquet",
    "anime_media_anilist": "processed/anilist_media/*/*.parquet",
    "anime_media_kitsu": "processed/kitsu_media/*/*.parquet",
    "anime_media_mal": "processed/mal_media/*/*.parquet",
}


def refresh_catalog(data_dir: Path, db_path: Path) -> list[str]:
    """(Re)create views over the Parquet lake, and the one small table that places
    daily fetches (see _mapped_mal_ids). Returns the names that were actually
    (re)created - a source/partition with no files yet is skipped with a
    warning rather than failing the whole refresh, since this runs even when some
    upstream sources are down.
    """
    con = duckdb.connect(str(db_path))
    created = []
    try:
        for view_name, glob_suffix in _VIEWS.items():
            glob_path = str(data_dir / glob_suffix)
            try:
                con.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT * FROM read_parquet('{glob_path}', union_by_name=true)"
                )
                created.append(view_name)
                logger.info("Refreshed view %s -> %s", view_name, glob_path)
            except duckdb.IOException:
                logger.warning("No files yet for view %s (%s), skipping", view_name, glob_path)

        has_registry = _identity_views(con, data_dir)
        if has_registry:
            created += ["anime_identity", "anime_alias"]

        # One row per title, as the sources have it; anime_media_latest is it
        # with its status corrected.
        titles = _latest_view_sql(con, has_registry, data_dir) if "anime_media" in created else None
        mapped = _mapped_mal_ids(con, titles, has_registry)
        created += mapped

        # Before the placements: an answer AniList gave for an id found by
        # search is placed by this and nothing else.
        resolved = _resolved_view(con, data_dir, has_registry)
        created += resolved

        # Before anime_media_latest, which corrects its status from this.
        status_view = _anilist_status_view(con, data_dir, has_registry, bool(mapped), bool(resolved))
        created += status_view

        if titles:
            latest = _status_corrected(con, titles, bool(status_view))
            con.execute(f"CREATE OR REPLACE VIEW anime_media_latest AS {latest}")
            created.append("anime_media_latest")
            logger.info(
                "Refreshed view anime_media_latest (latest run per %s%s)",
                "identity" if has_registry else "source row",
                ", status checked against AniList" if status_view else "",
            )

        created += _franchise_views(con, data_dir)
        created += _change_view(con, data_dir, has_registry)
        created += _airing_view(con, data_dir, has_registry, bool(mapped), bool(resolved))
        created += _airing_history_view(con, data_dir, has_registry, bool(mapped), bool(resolved))
        created += _score_daily_view(con, data_dir, has_registry, bool(mapped), bool(resolved))
        created += _prose_views(con, data_dir)
    finally:
        con.close()
    return created


def _prose_views(con: duckdb.DuckDBPyConnection, data_dir: Path) -> list[str]:
    """The two things the API serves that were never rows: the weekly digest and
    each run's own check of its output.

    Both were read straight off the filesystem by their routers - DATA_DIR/digests
    for one, DATA_DIR/processed/runs for the other - which worked for exactly as
    long as the API and the pipeline shared a disk. They do not any more: the API
    runs on a container that downloads one published file and has no lake behind
    it, so anything it serves has to be IN that file. Four pages of the site are
    the digest, and they would have gone live permanently empty.

    VIEWS, NOT TABLES, AND NOT GUARDED ON THE FILES EXISTING. Both of these are
    written AFTER this function runs: generate_digest is three steps later in the
    weekly, and a run's check record is the last thing it writes at all (see
    pipeline/run.py). A table built here would hold every digest except the one
    the run just produced, and a view only created where files already exist
    would miss the first of each. A bare view over the glob has neither problem:
    read_text evaluates it when read, which is processing/publish.materialise at
    the end of the run, and an empty glob is zero rows rather than an error.

    The same laziness is why the franchise and change views can be created here
    before the steps that write their parquet.
    """
    created = []
    for name, sql in {
        "digest":
            "SELECT regexp_extract(filename, '([0-9]{4}-[0-9]{2}-[0-9]{2})\\.md$', 1) "
            "         AS run_date, content "
            f"FROM read_text('{data_dir / "digests"}/*.md') "
            "WHERE run_date <> ''",
        # The record is kept as the text it was written as, and parsed by the
        # router against its own schema. Splitting it into columns here would put
        # half of backend/app/schemas.py in this file and break the API every
        # time a check learned a new field.
        #
        # No ORDER BY: a materialised table has no promised row order, so the
        # ordering lives in the query that reads it.
        "run_check":
            "SELECT regexp_extract(filename, '([^/]+)/[^/]+\\.json$', 1) AS dag, "
            "       regexp_extract(filename, '([^/]+)\\.json$', 1) AS run_date, "
            "       content AS record "
            f"FROM read_text('{data_dir / "processed" / "runs"}/*/*.json')",
    }.items():
        try:
            con.execute(f"CREATE OR REPLACE VIEW {name} AS {sql}")
            created.append(name)
        except duckdb.Error:
            # Belt and braces across DuckDB versions: 1.5.6 binds a glob that
            # matches nothing without complaint, and an older one refusing to
            # should cost this one view and a warning, not the whole refresh.
            logger.warning("Could not create view %s over %s", name, data_dir, exc_info=True)
    return created


def _franchise_views(con: duckdb.DuckDBPyConnection, data_dir: Path) -> list[str]:
    """Related titles and franchises, where they have been built. See
    ingestion/mal/fetch_relations.py and processing/franchise.py.

    `anime_relation` is each title's current list of related titles: its most
    recent fetch, the edges only. `franchise_member` is the built table as is.
    """
    created = []
    relations = data_dir / "processed" / "mal_relations"
    if list(relations.glob("*/*.parquet")):
        con.execute(
            "CREATE OR REPLACE VIEW anime_relation AS "
            "SELECT * EXCLUDE (_latest) FROM ("
            "  SELECT *, MAX(fetched_on) OVER (PARTITION BY mal_id) AS _latest"
            f"  FROM read_parquet('{relations}/*/*.parquet', union_by_name=true)"
            ") WHERE fetched_on = _latest AND related_mal_id IS NOT NULL"
        )
        created.append("anime_relation")
    else:
        logger.warning("No related titles fetched yet (%s), skipping anime_relation", relations)

    members = data_dir / "processed" / "franchise" / "members.parquet"
    if members.exists():
        con.execute(f"CREATE OR REPLACE VIEW franchise_member AS SELECT * FROM read_parquet('{members}')")
        created.append("franchise_member")
    else:
        logger.warning("No franchises built yet (%s), skipping franchise_member", members)
    return created


def _change_view(con: duckdb.DuckDBPyConnection, data_dir: Path, has_registry: bool) -> list[str]:
    """Every change a source has reported about a title. See processing/changes.py.

    Each change is on the title it belongs to now, not when it was recorded: by
    its source key in the registry, which follows merges, then by the identity
    it was stamped with, through any alias. A title merged since keeps its
    history. The files are read per query, one a weekly run, tens of rows each.
    """
    changes = data_dir / "processed" / "changes"
    if not list(changes.glob("*.parquet")):
        logger.warning("No changes recorded yet (%s), skipping anime_change", changes)
        return []

    rows = f"read_parquet('{changes}/*.parquet', union_by_name=true)"
    if has_registry:
        sql = (
            f"SELECT c.* EXCLUDE (wb_id), COALESCE(k.wb_id, al.wb_id, c.wb_id) AS wb_id FROM {rows} c "
            "LEFT JOIN anime_identity k ON k.source_key = c.source || ':' || c.source_id "
            "LEFT JOIN anime_alias al ON al.alias = c.wb_id"
        )
    else:
        sql = f"SELECT * FROM {rows}"
    con.execute(f"CREATE OR REPLACE VIEW anime_change AS {sql}")
    return ["anime_change"]


def _current_placed(
    con: duckdb.DuckDBPyConnection,
    view: str,
    name: str,
    data_dir: Path,
    has_registry: bool,
    mapped: bool,
    resolved: bool = False,
) -> list[str]:
    """A view over a daily fetch's current file, each row placed on the title it
    belongs to: by AniList id, then the AniList id found for a title by search,
    then MAL id, then the MAL id a title only Kitsu lists is mapped to. See
    ingestion.storage.write_daily.

    The file is read per query, not when the view is made. These are fetched
    daily and the views are made weekly, and neither waits for the other: a new
    day's file is served the moment it is moved into place, with nothing opening
    the warehouse to write. One file, not the dated glob, because the dated glob
    would cost every query a file more each day - and the status check is joined
    into anime_media_latest, which every request reads.

    AniList id first, then MAL id: 13 of the 102 catalogue titles airing in the
    week first measured were missing from AniList's season listing, so only
    the MAL id placed them. A row none of them places has a null wb_id and is
    still served - One Piece is on the schedule whether or not the catalogue
    holds it.

    A searched id outranks the answer's own MAL id because the answer was got by
    asking about this title, and an entry's idMal is a cross-reference AniList
    keeps, not a fact about the entry. Live, on the first day this ran, all four
    disagreements went the searched id's way: AniList files Throne of Seal 3
    under the MAL id of Throne of Seal 2nd Season, and Dou Po Cangqiong: Nian
    Fan 4 under Battle Through The Heavens Season 5's, so placing by idMal put
    2025's answer on a series that finished in 2022. A source's own id still
    wins over both: that one is not a cross-reference but this title's address.
    """
    current = data_dir / "processed" / "current" / f"{name}.parquet"
    if not current.exists():
        logger.warning("Nothing fetched yet for %s (%s), skipping it", view, current)
        return []

    sql = _placed_sql(f"read_parquet('{current}')", has_registry, mapped, resolved)
    con.execute(f"CREATE OR REPLACE VIEW {view} AS {sql}")
    return [view]


def _placed_sql(rows: str, has_registry: bool, mapped: bool, resolved: bool) -> str:
    """The placement itself, over any expression that yields AniList answers.

    Extracted so the daily score series can read the *dated* files with exactly
    the same rules the served file is read by. Two copies of this join would
    drift, and a row placed on a different title in one of them than the other
    is the hardest kind of wrong to notice."""
    if not has_registry:
        return f"SELECT *, CAST(NULL AS VARCHAR) AS wb_id FROM {rows}"
    placed, joins = ["a.wb_id"], [
        "LEFT JOIN anime_identity a ON a.source_key = 'anilist:' || CAST(l.anilist_id AS VARCHAR)",
    ]
    if resolved:
        placed.append("r.wb_id")
        joins.append(
            "LEFT JOIN anime_anilist_resolved r ON r.anilist_id = CAST(l.anilist_id AS BIGINT)"
        )
    placed.append("m.wb_id")
    joins.append(
        "LEFT JOIN anime_identity m ON m.source_key = 'mal:' || CAST(l.mal_id AS VARCHAR)"
    )
    if mapped:
        placed.append("k.wb_id")
        joins.append("LEFT JOIN anime_mapped_mal_id k ON k.mal_id = CAST(l.mal_id AS BIGINT)")
    return f"SELECT l.*, COALESCE({', '.join(placed)}) AS wb_id FROM {rows} l {' '.join(joins)}"


def _mapped_mal_ids(con: duckdb.DuckDBPyConnection, titles: str | None, has_registry: bool) -> list[str]:
    """The titles neither AniList nor MAL knows by key, by the MAL id they carry.

    A title only Kitsu lists has no `mal:` key, since no MAL row carries it, but
    Kitsu maps most titles to a MAL id and the merged row keeps it. The status
    check asks AniList about such a title by that id (fetch_status.candidates),
    and AniList answers - but nothing placed the answer. On 2026-09-14 that was
    three of the 241 answers: Dongitsune Season 2, finished in February 2024,
    and A Record of Mortal's Journey to Immortality Season 4 both went on
    showing as airing.

    Only titles with no AniList or MAL key at all: one they know under another
    id is another work. And only where one title alone carries the id, because
    Kitsu's mapping is not always MAL's - it gives some titles AniList's id
    instead (see processing/matching.py).

    The one table in the warehouse, made here rather than viewed. As a view it
    derived every title again inside every request that reads
    anime_media_latest, which the status check is joined into: a season went
    from 13ms to 27ms. It changes only when the catalogue or the identities do,
    and this runs straight after both.
    """
    columns = {row[0] for row in con.execute(f"DESCRIBE {titles}").fetchall()} if titles else set()
    if not (has_registry and "mal_id" in columns):
        con.execute("DROP TABLE IF EXISTS anime_mapped_mal_id")
        return []
    con.execute(
        "CREATE OR REPLACE TABLE anime_mapped_mal_id AS "
        "SELECT t.mal_id, t.wb_id FROM ("
        "  SELECT CAST(mal_id AS BIGINT) AS mal_id, MIN(wb_id) AS wb_id, COUNT(*) AS n"
        f"  FROM ({titles}) WHERE mal_id IS NOT NULL GROUP BY 1"
        ") t WHERE t.n = 1 AND t.wb_id IS NOT NULL AND NOT EXISTS ("
        "  SELECT 1 FROM anime_identity i WHERE i.wb_id = t.wb_id"
        "  AND (i.source_key LIKE 'anilist:%' OR i.source_key LIKE 'mal:%'))"
    )
    return ["anime_mapped_mal_id"]


def _resolved_view(con: duckdb.DuckDBPyConnection, data_dir: Path, has_registry: bool) -> list[str]:
    """The AniList id found by title search for a title that had none the daily
    check could ask by. See ingestion/anilist/resolve_ids.py.

    Newest answer per title, matches only: a recorded miss says AniList has no
    such entry, which stops the search being repeated but places nothing. One
    title per id as well - two titles claiming one AniList id would each be
    given the other's status - keeping the one searched for most recently.
    """
    files = data_dir / "processed" / "anilist_resolved"
    if not (has_registry and list(files.glob("*.parquet"))):
        return []
    con.execute(
        "CREATE OR REPLACE VIEW anime_anilist_resolved AS "
        "SELECT wb_id, anilist_id, matched_by, searched_on FROM ("
        f"  SELECT * FROM read_parquet('{files}/*.parquet', union_by_name=true)"
        "  WHERE anilist_id IS NOT NULL"
        "  QUALIFY ROW_NUMBER() OVER (PARTITION BY wb_id ORDER BY searched_on DESC) = 1"
        ") QUALIFY ROW_NUMBER() OVER (PARTITION BY anilist_id ORDER BY searched_on DESC) = 1"
    )
    return ["anime_anilist_resolved"]


def _airing_view(
    con: duckdb.DuckDBPyConnection, data_dir: Path, has_registry: bool, mapped: bool, resolved: bool
) -> list[str]:
    """AniList's airing schedule. See ingestion/anilist/fetch_airing.py."""
    return _current_placed(
        con, "anime_airing", "anilist_airing", data_dir, has_registry, mapped, resolved
    )


def _airing_history_view(
    con: duckdb.DuckDBPyConnection, data_dir: Path, has_registry: bool, mapped: bool, resolved: bool
) -> list[str]:
    """Every episode airdate the schedule has ever carried, aired ones included.

    THE DATED GLOB, for the same reason _score_daily_view reads one and on the
    opposite trade-off from anime_airing beside it. That view reads
    processed/current/ because /schedule and every title page's countdown query
    it, and the glob would cost those a file more each day. Here the history IS
    the subject, the dated files were already being written and kept by
    ingestion.storage.write_daily - 30 of them by 2026-10-19, back to the
    daily DAG's first run on 09-14 - and nothing but this reads it.

    Which means the site has been throwing this away on every page load. A
    finished episode leaves processed/current/ the next morning, so the site
    could say an episode is coming and never that one had been: "Episode 7 of
    12 airs Monday" became silence the day after it aired, on a show mid-season.

    NEWEST READING PER EPISODE, not the first. A broadcast slips - that is why
    the fetch is daily rather than weekly - and the last thing AniList said
    about an episode is the accurate one. Keeping the earliest would preserve
    the schedule as first announced, which is a different and much less useful
    question.

    Per (anilist_id, episode) rather than per (wb_id, episode): a row no
    identity places has a null wb_id and is still kept, exactly as anime_airing
    keeps One Piece whether or not the catalogue holds it. Grouping those
    together under one null would collapse every unplaced show into a single
    series.
    """
    # NOT gated on the registry, unlike the score series below and like
    # anime_airing beside it: a row no identity places keeps a null wb_id and is
    # still served, which is how One Piece reaches /schedule whether or not the
    # catalogue holds it. A warehouse built before identities therefore still
    # has this view, with nothing placed - the same shape anime_airing has.
    files = data_dir / "processed" / "anilist_airing"
    if not list(files.glob("*.parquet")):
        return []
    rows = f"read_parquet('{files}/*.parquet', union_by_name=true)"
    con.execute(
        "CREATE OR REPLACE VIEW anime_airing_history AS SELECT * FROM ("
        f"  {_placed_sql(rows, has_registry, mapped, resolved)}"
        ") QUALIFY ROW_NUMBER() OVER ("
        "  PARTITION BY anilist_id, episode ORDER BY fetched_on DESC) = 1"
    )
    return ["anime_airing_history"]


def _anilist_status_view(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    has_registry: bool,
    mapped: bool,
    resolved: bool = False,
) -> list[str]:
    """AniList's own status for the titles the sources call airing. See
    ingestion/anilist/fetch_status.py. Without identities there is nothing to
    place a check on, so no view."""
    if not has_registry:
        return []
    return _current_placed(
        con, "anime_anilist_status", "anilist_status", data_dir, has_registry, mapped, resolved
    )


def _score_daily_view(
    con: duckdb.DuckDBPyConnection, data_dir: Path, has_registry: bool, mapped: bool, resolved: bool
) -> list[str]:
    """One row per airing title per day it was asked about, with the score and
    the vote count AniList gave that morning.

    THE DATED GLOB, DELIBERATELY, and it is the only view here that reads one.
    Every other daily view reads processed/current/*.parquet because it is
    joined into anime_media_latest, which every request reads, and the glob
    would cost those queries a file more each day. This one is the opposite: the
    history IS the subject, the files were already being written and kept by
    ingestion.storage.write_daily, and nothing but this reads it - so a page
    that plots a score pays the cost and a page that does not never touches it.

    Weekly snapshots record a score that moved twice in a week as one move, and
    /scores exists to say how scores move while a season airs. This is the dense
    half of that series, and it costs no new fetch: fetch_status already asks
    AniList about exactly the airing titles, every morning.

    Rows with no score are dropped rather than carried as nulls - a title nobody
    has rated yet has not been measured, which is a different thing from one
    measured at the same value - and user_count is kept because a reading is
    only a re-ask where the vote count moved (see backend/app/routers/scores.py).

    Guarded on the column existing: dated files written before this shipped have
    neither field, union_by_name fills them with nulls once ANY file has them,
    and until the first new-schema file lands there is no column to select."""
    files = data_dir / "processed" / "anilist_status"
    if not (has_registry and list(files.glob("*.parquet"))):
        return []
    rows = f"read_parquet('{files}/*.parquet', union_by_name=true)"
    columns = {row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {rows}").fetchall()}
    if "score_100" not in columns:
        logger.info("No daily score readings yet (no file carries score_100), skipping the series")
        return []
    con.execute(
        "CREATE OR REPLACE VIEW anime_score_daily AS "
        "SELECT wb_id, fetched_on, score_100, user_count FROM ("
        f"  {_placed_sql(rows, has_registry, mapped, resolved)}"
        ") WHERE wb_id IS NOT NULL AND score_100 IS NOT NULL "
        "QUALIFY ROW_NUMBER() OVER (PARTITION BY wb_id, fetched_on ORDER BY anilist_id) = 1"
    )
    return ["anime_score_daily"]


def _status_corrected(con: duckdb.DuckDBPyConnection, latest: str, has_status: bool) -> str:
    """anime_media_latest's rows, with their status checked against AniList.

    The merged status is the winner's - Kitsu's, mostly - as of the snapshot a
    title was filed in, and only the current season is refetched, so it goes on
    calling shows airing long after their finale: 81 on 2026-09-14, Yu-Gi-Oh! Go
    Rush!! a year and a half after its last episode. AniList is asked daily about
    exactly the titles the sources call airing, and where it says one has
    stopped, that is what the catalogue says - in lists, on the browse grid's
    airing tabs, in the front page's counts and the digest, not only on the
    title's own page.

    Finished and cancelled become "finished"; not yet aired becomes "upcoming".
    A hiatus leaves the status "current" - the series is still running, and the
    shared vocabulary has no word for a pause - but anilist_status says so, and a
    page reads it before offering a weekly slot.

    The sources' own answer is kept as merged_status. The check asks about titles
    by it, not by the corrected status - see fetch_status.candidates - and it is
    what the sources still say where AniList overrules them.

    What is left is the titles AniList never answered for: 67 of the 296 the
    sources call airing, 48 of them with a premiere over a year old. Nothing can
    confirm those, and a title whose only evidence of airing is a source snapshot
    from years ago should not be read the same as one AniList confirmed this
    morning. airing_unconfirmed says which is which, and the site stops short of
    calling them airing: no countdown to a weekly slot, no place in an airing
    count, and a status that says plainly it could not be checked. A recent
    premiere is not flagged - the sources' word is fresh, and it is all anyone
    has for a show that started last week. See ingestion/anilist/resolve_ids.py,
    which is what shrinks this set.
    """
    columns = {row[0] for row in con.execute(f"DESCRIBE {latest}").fetchall()}
    if "status" not in columns:
        return latest

    # Explicit casts: make_date takes INTEGER, and these columns are BIGINT from
    # Parquet. The year alone where the rest is missing - a premiere known only
    # as "2022" is over a year old either way - and nothing flagged at all where
    # the premiere is unknown, or the snapshot predates the column: an
    # unconfirmed title is one known to be old, not one that cannot be dated.
    def _part(name: str) -> str:
        return f"CAST(COALESCE(b.{name}, 1) AS INTEGER)" if name in columns else "1"

    if "start_year" in columns:
        premiered = f"make_date(CAST(b.start_year AS INTEGER), {_part('start_month')}, {_part('start_day')})"
        old_enough = f"b.start_year IS NOT NULL AND {premiered} < current_date - INTERVAL 1 YEAR"
    else:
        old_enough = "FALSE"
    if has_status:
        return (
            "SELECT b.* EXCLUDE (status), "
            "CASE WHEN b.status = 'current' AND s.status IN ('finished', 'cancelled') THEN 'finished' "
            "     WHEN b.status = 'current' AND s.status = 'upcoming' THEN 'upcoming' "
            "     ELSE b.status END AS status, "
            "b.status AS merged_status, s.status AS anilist_status, "
            "s.ended_on AS anilist_ended_on, s.fetched_on AS anilist_checked_on, "
            f"(b.status = 'current' AND s.status IS NULL AND {old_enough}) AS airing_unconfirmed "
            f"FROM ({latest}) b "
            "LEFT JOIN (SELECT * FROM anime_anilist_status WHERE wb_id IS NOT NULL "
            "           QUALIFY ROW_NUMBER() OVER (PARTITION BY wb_id ORDER BY anilist_id) = 1) s "
            "  ON s.wb_id = b.wb_id"
        )
    # No check has ever run, so nothing airing is confirmed: the same rule, with
    # every answer missing. The column means one thing however it was built.
    return (
        "SELECT b.*, b.status AS merged_status, CAST(NULL AS VARCHAR) AS anilist_status, "
        "CAST(NULL AS VARCHAR) AS anilist_ended_on, CAST(NULL AS VARCHAR) AS anilist_checked_on, "
        f"(b.status = 'current' AND {old_enough}) AS airing_unconfirmed "
        f"FROM ({latest}) b"
    )


def _identity_views(con: duckdb.DuckDBPyConnection, data_dir: Path) -> bool:
    """Expose the identity registry, if one exists yet. See processing/identity.py.

    `anime_identity` maps every source key ever seen to the title it belongs to;
    `anime_alias` maps retired identities to the one that absorbed them. The
    registry keeps both flattened - every key points at a live identity and every
    alias at its final target - so each resolves in a single join.
    """
    registry = data_dir / "identity" / "registry.parquet"
    if not registry.exists():
        logger.warning("No identity registry at %s yet - titles keyed by source row", registry)
        return False

    path = str(registry)
    con.execute(
        "CREATE OR REPLACE VIEW anime_identity AS "
        f"SELECT key AS source_key, wb_id FROM read_parquet('{path}') WHERE kind = 'key'"
    )
    con.execute(
        "CREATE OR REPLACE VIEW anime_alias AS "
        f"SELECT key AS alias, wb_id FROM read_parquet('{path}') WHERE kind = 'alias'"
    )
    return True


def _newest_catalogue(data_dir: Path) -> Path | None:
    """The newest catalogue snapshot that finished being written, or None.

    Finished means Spark's _SUCCESS marker, written when the job commits: a run
    that died mid-write leaves a directory without one, and serving it would
    serve a partial catalogue. Chosen when the views are made, which the weekly
    DAG does straight after consolidating.
    """
    snapshots = data_dir / "processed" / "anime_media_consolidated" / "_catalogue"
    complete = [d for d in snapshots.glob("*") if (d / "_SUCCESS").exists() and any(d.glob("*.parquet"))]
    return max(complete, key=lambda d: d.name) if complete else None


def _latest_view_sql(con: duckdb.DuckDBPyConnection, has_registry: bool, data_dir: Path) -> str:
    """The query for the newest row per TITLE, where title means its stable identity.

    Read from the newest complete catalogue snapshot alone, where there is one.
    Consolidation reads every source snapshot up to its run, so the newest
    catalogue already holds every title; the older ones are history, and stay in
    anime_media for anything that wants it. Deduplicating across all of them on
    every request cost a query ten times as much and grew by a snapshot a week:
    a season took 156ms over five snapshots, 15ms from the newest alone, with
    the same 238 titles. Without a complete catalogue snapshot - a lake from
    before consolidation ran catalogue-wide - it falls back to all of anime_media.

    anime_media keeps one row per title per run, which is right for history, but
    everything that renders the catalogue wants one row per title. It used to
    partition by (source, source_id). That is the address that moves: when the
    merge picks a different winner between two runs - a new pass, a source coming
    back online and outranking another - the same title arrives under two keys
    and survives twice, a duplicate made by nothing but a change of winner.

    Partitioning by identity closes that. It has to cope with every row the lake
    already holds, most of which predate identities entirely, so each row's
    identity is resolved in order of authority:

      1. the registry's current answer for the row's own source key, which is
         authoritative and already follows merges;
      2. the identity stamped on the row, run through the aliases, for a row
         whose key the registry no longer lists under that identity;
      3. the stamped identity as written;
      4. the source key itself, for a row nothing knows about - which is exactly
         the old behaviour, so a lake with no registry yet is unaffected.

    Casts are explicit because DuckDB types a column that is NULL in every row of
    a file as INTEGER, and 1.1.3 (the version CI pins) refuses to COALESCE it with
    VARCHAR; that has turned a sort into a 500 in this project once already.
    """
    newest = _newest_catalogue(data_dir)
    rows = f"read_parquet('{newest}/*.parquet', union_by_name=true)" if newest else "anime_media"
    columns = {row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {rows}").fetchall()}
    stamped = "wb_id" in columns
    own_key = "CAST(m.source AS VARCHAR) || ':' || CAST(m.source_id AS VARCHAR)"

    candidates, joins = [], []
    if has_registry:
        candidates.append("CAST(k.wb_id AS VARCHAR)")
        joins.append(f"LEFT JOIN anime_identity k ON k.source_key = {own_key}")
    if stamped:
        if has_registry:
            candidates.append("CAST(al.wb_id AS VARCHAR)")
            joins.append("LEFT JOIN anime_alias al ON al.alias = CAST(m.wb_id AS VARCHAR)")
        candidates.append("CAST(m.wb_id AS VARCHAR)")

    if not candidates:
        # No identities anywhere yet: exactly the old view.
        return (
            "SELECT * EXCLUDE (_rn) FROM ("
            "  SELECT *, ROW_NUMBER() OVER ("
            "    PARTITION BY source, source_id ORDER BY run_date DESC"
            f"  ) AS _rn FROM {rows}"
            ") WHERE _rn = 1"
        )

    base = "m.* EXCLUDE (wb_id)" if stamped else "m.*"
    resolved = (
        f"SELECT {base}, COALESCE({', '.join(candidates)}) AS wb_id "
        f"FROM {rows} m {' '.join(joins)}"
    )
    return (
        "SELECT * EXCLUDE (_rn) FROM ("
        "  SELECT *, ROW_NUMBER() OVER ("
        "    PARTITION BY COALESCE(wb_id, CAST(source AS VARCHAR) || ':' || CAST(source_id AS VARCHAR))"
        "    ORDER BY run_date DESC"
        f"  ) AS _rn FROM ({resolved})"
        ") WHERE _rn = 1"
    )


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()

    db_path = args.db_path or args.data_dir / "warehouse.duckdb"
    views = refresh_catalog(args.data_dir, db_path)
    print(f"Refreshed {len(views)} view(s) at {db_path}: {views}")
