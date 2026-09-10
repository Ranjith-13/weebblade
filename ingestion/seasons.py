def season_for_month(month: int) -> str:
    """Map a calendar month to the anime industry's quarterly season (WINTER = Jan-Mar).

    Shared across sources — AniList, Jikan/MAL, and Kitsu all use this same quarterly
    convention, just with different casing in their own APIs.
    """
    if month in (1, 2, 3):
        return "WINTER"
    if month in (4, 5, 6):
        return "SPRING"
    if month in (7, 8, 9):
        return "SUMMER"
    return "FALL"


def partition_for(season: str, season_year: int) -> str:
    """The directory a season's snapshots live under, e.g. "2026-SUMMER"."""
    return f"{season_year}-{season}"


def capture_for(at) -> tuple[str, int, str, str]:
    """The season, year, run_date and partition for a run capturing data at `at`.

    `at` is Airflow's data_interval_end, NOT its logical_date. For a weekly
    schedule those are seven days apart: logical_date is the START of the
    interval, so a run that fires on the 13th is stamped the 6th - a date on
    which its data did not yet exist.

    That is not cosmetic. run_date is what anime_media_latest ranks by to decide
    which snapshot of a title is current, so a run stamped a week in the past
    loses to anything newer already in the warehouse: it would fetch,
    consolidate, write, report success, and change nothing anyone can see.
    Verified against the live DAG - the run created on 2026-09-13 carries
    logical_date 2026-09-06, and a catalogue written on 2026-09-10 would have
    beaten it.

    data_interval_end is when the data is "as of", it is when the run actually
    fires, and it is still a fixed property of the run rather than a wall clock,
    so a retry rewrites the same paths instead of adding a second set.

    The season comes from the same instant, because what is airing is decided by
    when the fetch happens - at a quarter boundary the interval's start is still
    the season before.

    strftime rather than pendulum's to_date_string, so this stays callable with
    anything date-shaped and testable without Airflow installed.
    """
    season = season_for_month(at.month)
    season_year = at.year
    return season, season_year, at.strftime("%Y-%m-%d"), partition_for(season, season_year)
