from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from ..db import get_db, run_query
from ..schemas import (
    ArrivalPoint,
    ScoreArrival,
    ScoreSettling,
    SeasonSettling,
    SettlingBand,
    SourceReasks,
)
from ..seasons import PHASE_ORDER, QUARTER, SEASON_START, season_phase

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
