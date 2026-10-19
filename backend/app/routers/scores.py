from __future__ import annotations

import logging
from datetime import date, timedelta

import duckdb
from fastapi import APIRouter, Depends, Query

from ..db import get_db, run_query
from ..schemas import (
    ArrivalPoint,
    DailyScorePoint,
    DailyScores,
    Gaining,
    Mover,
    Moving,
    PrintedMove,
    ScoreArrival,
    ScoreSettling,
    SeasonSettling,
    SettlingBand,
    SourceReasks,
)
from ..seasons import PHASE_ORDER, QUARTER, SEASON_START, season_phase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scores", tags=["scores"])

# TV only, which is what /browse shows by default and for the same reason: a
# season's music videos and ONAs are mostly unscored, so a figure over every
# format is mostly a statement about them. Measured over all formats the shape
# below is the same to within a point or two.
_TV = "format = 'TV'"

# WHY THE UNIT IS A RE-ASK AND NOT A SNAPSHOT
#
# anime_media holds every dated snapshot of the catalogue, but a snapshot is not
# an observation. The weekly run refetches the season being covered; every other
# title's row is written again unchanged. Measured on 2026-10-14: the 68 Fall
# 2021 TV titles carry a row on all ten dated snapshots and their user_count
# sums to exactly 592,705 on every one of them. So "no Fall 2021 score moved"
# is a statement about what was asked, not about what changed, and a table built
# on snapshots would read the pipeline's own schedule as a fact about anime.
#
# A pair of consecutive readings therefore counts only when user_count moved,
# which no carry-forward can fake.
#
# AND THE DETECTOR MUST NOT BE THE SCORE
#
# The tempting version - count a pair when anything at all differs - throws
# away precisely the refetches that returned the same number, so every
# "nothing changed" observation disappears and the rate it reports is near 100%
# by construction. user_count is independent of the score and moves on every
# real fetch of a title anyone is watching, so it detects the fetch without
# looking at the answer.
#
# What that costs: a refetch that returns an identical vote count is
# indistinguishable from a copy and is dropped. 40 of Kitsu's 431 score moves
# sit in such a pair, so re-asks are under-counted by a few percent and the
# rates below are, if anything, conservative.
#
# PER SOURCE ROW, NOT PER TITLE
#
# Three sources rate the same show differently and the merge picks a winner each
# run. Comparing merged titles would read a change of winner as a revision
# nobody made, so each source's own reading is followed on its own.
_REASKS = f"""
WITH reading AS (
  SELECT source, source_id, wb_id, run_date,
         MAX(user_count) AS votes, MAX(score_100) AS score
  FROM anime_media
  WHERE wb_id IS NOT NULL AND score_100 IS NOT NULL AND user_count IS NOT NULL
  GROUP BY source, source_id, wb_id, run_date
), paired AS (
  SELECT source, wb_id, votes, score,
         LAG(votes) OVER (PARTITION BY source, source_id ORDER BY run_date) AS was_votes,
         LAG(score) OVER (PARTITION BY source, source_id ORDER BY run_date) AS was_score
  FROM reading
), bounds AS (
  SELECT MIN(run_date) AS first_run, MAX(run_date) AS last_run FROM reading
), tv AS (
  SELECT wb_id, ANY_VALUE(season) AS season, ANY_VALUE(season_year) AS season_year
  FROM anime_media_latest
  WHERE {_TV} AND season IS NOT NULL AND season_year IS NOT NULL
  GROUP BY wb_id
), reask AS (
  SELECT t.season, t.season_year, p.source, p.wb_id,
         p.score, p.was_score,
         ABS(p.score - p.was_score) AS moved_by,
         -- Visible means visible on this site: a score is stored out of 100 and
         -- printed out of 10 to one decimal, so 83.41 to 83.36 is not a change
         -- anyone can see and printing it would invent precision the product
         -- does not use anywhere else.
         ROUND(p.score / 10, 1) <> ROUND(p.was_score / 10, 1) AS visible,
         -- Was this season on air while the pipeline was watching? The question
         -- the table is really asking, and a cleaner instrument than each
         -- title's own status: a show that finished inside the window did most
         -- of its moving while it was still running, and counting it as
         -- "finished" would blunt both sides.
         {season_phase("b.first_run::DATE", "b.last_run::DATE")} AS phase
  FROM paired p
  JOIN tv t ON t.wb_id = p.wb_id
  CROSS JOIN bounds b
  WHERE p.was_votes IS NOT NULL AND p.votes <> p.was_votes
)
"""

_FIGURES = """
  COUNT(*) AS reasks,
  COUNT(DISTINCT wb_id) AS titles,
  COUNT(*) FILTER (WHERE moved_by > 0) AS revised,
  COUNT(*) FILTER (WHERE visible) AS visible,
  ROUND(MEDIAN(moved_by), 2) AS median_change,
  COUNT(*) FILTER (WHERE score > was_score) AS up,
  COUNT(*) FILTER (WHERE score < was_score) AS down
"""


@router.get("/settling", response_model=ScoreSettling)
def settling(con: duckdb.DuckDBPyConnection = Depends(get_db)) -> ScoreSettling:
    """What a score does over its life, read down the warehouse's time axis.

    THE LONGITUDINAL HALF OF A WAREHOUSE THAT WAS ONLY EVER READ ACROSS. Every
    other endpoint answers "what is true now" from anime_media_latest, which is
    the top slice of anime_media's 66,098 dated rows. This one asks what those
    rows say about the numbers themselves: when a score appears, how long it
    keeps moving, and what happens to it afterwards.

    It is one endpoint and not a shape the frontend could derive, which is the
    whole reason it exists: the answer is 544 comparisons drawn from 66,098
    rows, and the site is built never to fetch more than a season.

    Everything rests on the re-ask, explained at length above the SQL: a
    snapshot is not an observation, because most rows in most runs are carried
    forward unchanged.

    Nothing new is fetched, stored or published for this. An early warehouse
    with a single snapshot has no pairs to compare and gets empty lists, which
    is a true answer rather than an error.
    """
    seasons = run_query(
        con,
        _REASKS + f"SELECT season, season_year, phase, {_FIGURES}, "
        "  ROUND(MAX(moved_by), 2) AS largest_change "
        "FROM reask GROUP BY season, season_year, phase "
        f"ORDER BY season_year DESC, {QUARTER} DESC",
    )
    bands = run_query(
        con,
        _REASKS + "SELECT phase, "
        "  COUNT(DISTINCT season_year::VARCHAR || season) AS seasons, "
        f"{_FIGURES} FROM reask GROUP BY phase ORDER BY {PHASE_ORDER}",
    )
    sources = run_query(
        con,
        _REASKS + "SELECT source, COUNT(*) AS reasks FROM reask GROUP BY source ORDER BY 2 DESC",
    )
    window = run_query(
        con,
        "SELECT COUNT(DISTINCT run_date) AS snapshots, MIN(run_date) AS first_run, "
        "  MAX(run_date) AS last_run FROM anime_media "
        "WHERE wb_id IS NOT NULL AND score_100 IS NOT NULL",
    )[0]
    held = run_query(
        con,
        "SELECT COUNT(*) AS n FROM (SELECT DISTINCT season, season_year "
        f"FROM anime_media_latest WHERE {_TV} AND season IS NOT NULL AND season_year IS NOT NULL)",
    )[0]["n"]

    return ScoreSettling(
        first_run=window["first_run"],
        last_run=window["last_run"],
        snapshots=window["snapshots"],
        seasons_held=held,
        reasks=sum(row["reasks"] for row in sources),
        sources=[SourceReasks(**row) for row in sources],
        seasons=[SeasonSettling(**row) for row in seasons],
        bands=[SettlingBand(**row) for row in bands],
        arrival=_arrival(con),
    )


@router.get("/daily/{wb_id}", response_model=DailyScores)
def daily(wb_id: str, con: duckdb.DuckDBPyConnection = Depends(get_db)) -> DailyScores:
    """One title's score as it was asked every morning, oldest first.

    THE DENSE HALF OF /settling ABOVE, AND THE ONLY SERIES HERE THAT IS NOT
    WEEKLY. Everything else on this router reads anime_media, which the pipeline
    writes once a week: a score that moves on Tuesday and again on Friday is one
    move there, and a score that moves and moves back is none. The daily AniList
    status check already asks about exactly the titles the catalogue calls
    airing, so the readings were being written and kept and nothing read them.

    AN ENDPOINT RATHER THAN A FIELD ON THE TITLE RESPONSE, which is the opposite
    call from score_history and for a reason that one did not have:
    anime_score_daily reads a DATED GLOB that gains a file every morning, so
    attaching it would make all 11,992 title pages pay a growing scan for an
    answer only the ~199 airing ones have. The frontend asks for this only where
    isAiring() is true, which is also the only place it would print anything.

    THE UNIT IS A RE-ASK, exactly as it is for /settling, and the reasoning
    above _REASKS applies here unchanged - a pair counts only where the vote
    count moved. It matters less than it does weekly, because every row here
    comes from a real fetch rather than a carry-forward, but the rule is the
    same rule and two different definitions of "a reading changed" on one router
    would be worse than either.

    Empty rather than 404 for a title with no readings: a finished show is not
    asked about, a warehouse published before the score columns existed carries
    none, and both are ordinary states of a catalogue. See DailyScores.
    """
    points = _series(con, wb_id)
    moves, reasks = [], 0
    for was, now in zip(points, points[1:]):
        if was["user_count"] is None or now["user_count"] is None:
            continue
        if now["user_count"] == was["user_count"]:
            continue
        reasks += 1
        # Printed, not stored: 83.41 to 83.36 is not a change anyone can see on
        # a site that shows one decimal out of ten. Same test as _REASKS.
        if round(now["score_100"] / 10, 1) != round(was["score_100"] / 10, 1):
            moves.append(
                PrintedMove(
                    on=now["fetched_on"],
                    was=was["score_100"],
                    now=now["score_100"],
                    votes_gained=now["user_count"] - was["user_count"],
                )
            )
    gained = None
    if len(points) > 1 and points[0]["user_count"] is not None and points[-1]["user_count"] is not None:
        gained = points[-1]["user_count"] - points[0]["user_count"]
    return DailyScores(
        wb_id=wb_id,
        points=[DailyScorePoint(**row) for row in points],
        reasks=reasks,
        moves=moves,
        votes_gained=gained,
    )


# How much of the daily series a reader is shown at once.
#
# A week, because that is the unit the question is asked in - "what has this
# season's scores done lately" - and because the series is published daily now,
# so a week of it is seven readings rather than one. Longer would turn a page
# about what is happening into an archive, and /scores/settling already answers
# the long question properly.
MOVING_DAYS = 7

# THE SAME SHAPE AS /settling AND FOR THE SAME REASON: a pair counts only where
# the vote count moved. The daily check writes a row every morning whether or
# not anything changed, so without this the page would report the schedule.
#
# Aggregated per title rather than per pair. A title that goes 6.8 to 6.9 to 7.0
# across a week moved once, by two tenths, on the sum of the week's votes - and
# three rows saying so would read as three shows. FIRST and LAST over the
# window, so a score that wandered and came back is correctly not a mover.
_MOVING = f"""
WITH reading AS (
  SELECT wb_id, fetched_on, score_100, user_count FROM anime_score_daily
  WHERE fetched_on > ?
), paired AS (
  SELECT wb_id, fetched_on, score_100, user_count,
         LAG(user_count) OVER (PARTITION BY wb_id ORDER BY fetched_on) AS was_votes,
         LAG(score_100)  OVER (PARTITION BY wb_id ORDER BY fetched_on) AS was_score
  FROM reading
), reask AS (
  SELECT * FROM paired WHERE was_votes IS NOT NULL AND user_count <> was_votes
), moved AS (
  SELECT wb_id,
         FIRST(was_score ORDER BY fetched_on) AS was,
         LAST(score_100 ORDER BY fetched_on) AS now,
         SUM(user_count - was_votes) AS votes_gained,
         COUNT(*) AS reasks,
         MAX(fetched_on) AS on
  FROM reask GROUP BY wb_id
)
"""


@router.get("/moving", response_model=Moving)
def moving(
    limit: int = Query(40, ge=1, le=100),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Moving:
    """Which of the season's scores have moved lately, and on how many votes.

    THE FRONT DOOR THE MEASUREMENT DID NOT HAVE. /settling explains how a score
    behaves over its life and is read once; this is the same instrument pointed
    at this week, and is the only page here that answers "what is happening" with
    titles rather than with rates. Before it, the daily series could be seen only
    by landing on the right title's page and knowing to look.

    RANKED BY THE VOTES BEHIND THE MOVE, not by its size. A score stored out of
    100 and shown out of 10 crosses a rounding boundary on a single vote, so the
    biggest-looking change on a page sorted by size is routinely the least
    meaningful one. Sorted by weight, the top of the list is where the most
    people actually changed their minds.

    Empty rather than an error on a warehouse with no daily readings - one
    published before the series existed, or a catalogue with nothing airing.
    """
    rows = _optional(
        con,
        _MOVING + """
        SELECT d.wb_id, d.was, d.now, d.votes_gained, d.reasks, d.on,
               COALESCE(m.title_english, m.title_romaji) AS title,
               m.poster_url, m.format, m.season, m.season_year
        FROM moved d JOIN anime_media_latest m ON m.wb_id = d.wb_id
        WHERE ROUND(d.now / 10, 1) <> ROUND(d.was / 10, 1)
        ORDER BY d.votes_gained DESC NULLS LAST, d.wb_id
        LIMIT ?
        """,
        [_since(), limit],
    )
    window = _optional(
        con,
        _MOVING + """
        SELECT (SELECT MIN(fetched_on) FROM reading) AS first_day,
               (SELECT MAX(fetched_on) FROM reading) AS last_day,
               (SELECT COUNT(DISTINCT fetched_on) FROM reading) AS days,
               (SELECT COUNT(*) FROM reask) AS reasks,
               (SELECT COUNT(DISTINCT wb_id) FROM reask) AS titles_reasked,
               COUNT(*) FILTER (WHERE ROUND(now / 10, 1) = ROUND(was / 10, 1)) AS steady
        FROM moved
        """,
        [_since()],
    )
    # THE OTHER QUESTION, over the same readings. FIRST and LAST of the vote
    # count rather than the sum of the re-asked pairs: the audience a title has
    # is a level, not a flow, and summing pairs would miss a day the check could
    # not run. Measured against AniList's own first reading, never the merged
    # count on anime_media_latest - that may be another source's number
    # entirely, and subtracting two sources gave +892% where the truth was
    # +10.8%.
    gaining = _optional(
        con,
        """
        WITH f AS (
          SELECT wb_id,
                 FIRST(user_count ORDER BY fetched_on) AS started,
                 LAST(user_count ORDER BY fetched_on) AS ended,
                 FIRST(score_100 ORDER BY fetched_on) AS was,
                 LAST(score_100 ORDER BY fetched_on) AS now
          FROM anime_score_daily WHERE fetched_on > ? GROUP BY wb_id
        )
        SELECT f.wb_id, f.started, f.ended, f.ended - f.started AS gained,
               ROUND((f.ended - f.started) * 100.0 / NULLIF(f.started, 0), 1) AS share,
               f.now AS score_100,
               ROUND(f.now / 10, 1) <> ROUND(f.was / 10, 1) AS moved,
               COALESCE(m.title_english, m.title_romaji) AS title,
               m.poster_url, m.format, m.season, m.season_year
        FROM f JOIN anime_media_latest m ON m.wb_id = f.wb_id
        WHERE f.ended > f.started
        ORDER BY gained DESC, f.wb_id
        LIMIT ?
        """,
        [_since(), limit],
    )
    totals = _optional(
        con,
        _MOVING + """
        SELECT SUM(votes_gained) AS votes_total,
               SUM(votes_gained) FILTER (WHERE ROUND(now / 10, 1) = ROUND(was / 10, 1))
                 AS votes_on_steady
        FROM moved
        """,
        [_since()],
    )
    counted = totals[0] if totals else {}

    head = window[0] if window else {}
    return Moving(
        first_day=head.get("first_day"),
        last_day=head.get("last_day"),
        days=head.get("days") or 0,
        reasks=head.get("reasks") or 0,
        titles_reasked=head.get("titles_reasked") or 0,
        steady=head.get("steady") or 0,
        movers=[Mover(**row) for row in rows],
        gaining=[Gaining(**row) for row in gaining],
        votes_total=counted.get("votes_total") or 0,
        votes_on_steady=counted.get("votes_on_steady") or 0,
    )


def _since() -> str:
    """The first day of the window, exclusive.

    Counted back from today rather than from the newest reading, deliberately:
    if the pipeline stops, "this week" should empty out and say so rather than
    quietly becoming the last week it managed to run.
    """
    return (date.today() - timedelta(days=MOVING_DAYS)).isoformat()


def _optional(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    """A query against the daily series, which a warehouse may not carry.

    anime_score_daily appears only once a dated status file holds score_100, so
    an older published warehouse has no such view - and the API and the site
    deploy separately, so a build can reach a container serving one. An empty
    answer, never the 503 that would take the block down.

    AND IT SAYS WHAT IT SWALLOWED. A BinderException is usually the view being
    absent, but it is equally what a column this query names and the warehouse
    does not raises - and that failure looks exactly like "nothing moved this
    week". It cost twenty minutes of reading a correct query while a missing
    poster_url returned an empty page in silence. An empty answer is still the
    right answer for a reader; a log line is the difference between knowing why
    and guessing.
    """
    try:
        return con.execute(sql, params).fetch_arrow_table().to_pylist()
    except (duckdb.CatalogException, duckdb.BinderException) as exc:
        logger.info("Daily series unavailable, answering empty: %s", str(exc).splitlines()[0])
        return []


def _series(con: duckdb.DuckDBPyConnection, wb_id: str) -> list[dict]:
    """The readings themselves, or nothing where the view does not exist.

    anime_score_daily appears only once a dated status file carries score_100
    (processing/duckdb_catalog._score_daily_view), so a warehouse published
    before that has no such view and this is not an error - unlike the 503
    run_query would raise, which would take a title page's block down on every
    older warehouse the separately-deployed API might be serving.
    """
    try:
        return con.execute(
            "SELECT fetched_on, score_100, user_count FROM anime_score_daily "
            "WHERE wb_id = ? ORDER BY fetched_on",
            [wb_id],
        ).fetch_arrow_table().to_pylist()
    except (duckdb.CatalogException, duckdb.BinderException):
        return []


def _arrival(con: duckdb.DuckDBPyConnection) -> ScoreArrival | None:
    """How the newest started season acquired its scores, run by run.

    The other half of the story, and the one the design is already built around:
    a title with no score prints screened back to halftone, and this is that
    state draining to colour over three weeks. A season reaches the catalogue
    months before anyone has rated it - the sources list it as soon as it is
    announced - so its first snapshots carry titles and no numbers.

    Carried-forward rows are counted here, deliberately: the question is what
    the catalogue held on that date, and a copy of yesterday's row is still what
    it held. A first score, though, can only arrive from a real fetch.

    The newest season that has STARTED, matching the site's default view. The
    newest on file is usually one nobody has rated at all, which would draw a
    flat line at nought.
    """
    season = run_query(
        con,
        "SELECT season, season_year FROM anime_media_latest "
        f"WHERE {_TV} AND season IS NOT NULL AND season_year IS NOT NULL "
        f"  AND {SEASON_START} <= current_date "
        f"GROUP BY season, season_year ORDER BY season_year DESC, {QUARTER} DESC LIMIT 1",
    )
    if not season:
        return None

    points = run_query(
        con,
        "WITH cohort AS (SELECT wb_id FROM anime_media_latest "
        f" WHERE {_TV} AND season = ? AND season_year = ? AND wb_id IS NOT NULL) "
        "SELECT m.run_date, COUNT(DISTINCT m.wb_id) AS listed, "
        "  COUNT(DISTINCT m.wb_id) FILTER (WHERE m.score_100 IS NOT NULL) AS scored "
        "FROM anime_media m JOIN cohort c ON c.wb_id = m.wb_id "
        "GROUP BY m.run_date ORDER BY m.run_date",
        [season[0]["season"], season[0]["season_year"]],
    )
    return ScoreArrival(
        season=season[0]["season"],
        season_year=season[0]["season_year"],
        points=[ArrivalPoint(**row) for row in points],
    )
