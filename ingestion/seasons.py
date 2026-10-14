def season_for_month(month: int) -> str:
    """Map a calendar month to the anime industry's quarterly season (WINTER = Jan-Mar).

    Shared across sources — AniList, MAL and Kitsu all use this same quarterly
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


def next_season(season: str, season_year: int) -> tuple[str, int]:
    """The season after this one, rolling the year over after FALL."""
    order = ["WINTER", "SPRING", "SUMMER", "FALL"]
    i = order.index(season)
    return (order[0], season_year + 1) if i == len(order) - 1 else (order[i + 1], season_year)


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


def capture_both(at) -> list[tuple[str, int, str, str]]:
    """This run's season and the one after it, each as capture_for returns it.

    The sources list a season months before it airs, and until 2026-09-21 the
    pipeline fetched only the season it was running in: nine days before Fall
    2026 began the catalogue held no Fall title at all, and the site could not
    answer "what is coming next", which is the front page of every comparable
    site. Both seasons are fetched every run, so the next one fills in as it is
    announced rather than appearing the day it starts.

    Same run_date for both - one run, one date - and separate partitions, so a
    title that moves between them is a season change like any other (see
    processing/changes.py) rather than two rows at one address.
    """
    season, season_year, run_date, partition = capture_for(at)
    after, after_year = next_season(season, season_year)
    return [(season, season_year, run_date, partition),
            (after, after_year, run_date, partition_for(after, after_year))]
