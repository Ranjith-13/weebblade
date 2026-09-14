from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import duckdb
from fastapi import APIRouter, Depends, Query

from ..db import get_db
from ..schemas import AiringEpisode, Schedule, ScheduledEpisode

router = APIRouter(prefix="/schedule", tags=["schedule"])
logger = logging.getLogger(__name__)

# Broadcasts keep Japan's calendar: most air after midnight there, and a
# schedule's days are the days they air in Tokyo. JST has no daylight saving.
JST = timezone(timedelta(hours=9))


def now() -> float:
    """The clock, as a function so tests can set it."""
    return time.time()


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _airing(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    """A query against anime_airing, which exists only once the schedule has been
    fetched. Before that there is nothing airing to report: an empty answer, not
    an error. Anything else wrong with the query is raised - an empty schedule
    would hide it."""
    try:
        return con.execute(sql, params).fetch_arrow_table().to_pylist()
    except duckdb.CatalogException:
        return []


def upcoming_episodes(con: duckdb.DuckDBPyConnection, wb_id: str, limit: int = 4) -> list[AiringEpisode]:
    """A title's next episodes, soonest first, from the newest schedule fetched.

    A title page must never fail because of its countdown, so any failure here
    costs the page its countdown, logged, and nothing more."""
    try:
        rows = _airing(
            con,
            "SELECT DISTINCT episode, airing_at, fetched_on FROM anime_airing "
            "WHERE wb_id = ? AND airing_at > ? ORDER BY airing_at LIMIT ?",
            [wb_id, int(now()), limit],
        )
    except duckdb.Error:
        logger.warning("Could not read upcoming episodes for %s", wb_id, exc_info=True)
        return []
    return [AiringEpisode(episode=r["episode"], airing_at=iso(r["airing_at"]), fetched_on=r["fetched_on"]) for r in rows]


@router.get("", response_model=Schedule)
def schedule(
    days: int = Query(7, ge=1, le=14),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Schedule:
    """Every episode airing from midnight today in Japan, for `days` days.

    From today's start rather than from now, so the day in progress is whole:
    an episode that aired this morning in Tokyo is still today's. A title in the
    catalogue comes as the catalogue has it; a show it does not hold comes as
    AniList describes it, with no wb_id.
    """
    today = datetime.fromtimestamp(now(), JST).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = int(today.timestamp()), int((today + timedelta(days=days)).timestamp())

    rows = _airing(
        con,
        "SELECT a.wb_id, a.anilist_id, a.mal_id, a.episode, a.episodes, a.airing_at, a.fetched_on, "
        "a.title AS anilist_title, a.format AS anilist_format, a.poster_url AS anilist_poster, "
        "m.wb_id AS held, m.title_english, m.title_romaji, m.format, m.poster_url, m.score_100 "
        "FROM anime_airing a LEFT JOIN anime_media_latest m ON m.wb_id = a.wb_id "
        "WHERE a.airing_at >= ? AND a.airing_at < ? ORDER BY a.airing_at, a.anilist_id, a.episode",
        [start, end],
    )
    episodes = [
        ScheduledEpisode(
            # Only a title the catalogue serves gets a page to link to.
            wb_id=r["held"],
            anilist_id=r["anilist_id"],
            mal_id=r["mal_id"],
            title=r["title_english"] or r["title_romaji"] or r["anilist_title"],
            format=r["format"] or r["anilist_format"],
            poster_url=r["poster_url"] or r["anilist_poster"],
            score_100=r["score_100"],
            episode=r["episode"],
            episodes=r["episodes"],
            airing_at=iso(r["airing_at"]),
        )
        for r in rows
    ]
    fetched = _airing(con, "SELECT MAX(fetched_on) AS d FROM anime_airing", [])
    return Schedule(
        start=iso(start), end=iso(end), fetched_on=fetched[0]["d"] if fetched else None, episodes=episodes
    )
