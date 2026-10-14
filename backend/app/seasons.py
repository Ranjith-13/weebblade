"""The broadcast year, as SQL fragments.

Two expressions, shared rather than copied, because both encode a fact about
the industry that no column in the warehouse states: a season is a quarter, and
its order is Winter, Spring, Summer, Fall. Sorted as text, FALL would open a
year instead of closing it and SUMMER would follow SPRING only by luck.

Kept here and not in a router because /catalogue and /scores both need them and
a CASE expression copied into two files is a CASE expression that will disagree
with itself. ai/digest/queries.py has its own copy deliberately: it runs inside
the pipeline, against the lake, and the API is not allowed to import from there
(see app/warehouse.py on why the serving process stays free of pipeline code).
"""

from __future__ import annotations

# Sort key for the quarter a title premiered in.
QUARTER = (
    "CASE season WHEN 'WINTER' THEN 0 WHEN 'SPRING' THEN 1 "
    "WHEN 'SUMMER' THEN 2 WHEN 'FALL' THEN 3 END"
)

# The first day of a season, which is how a season the pipeline has fetched but
# that has not started yet can say so. The pipeline fetches the next season as
# soon as the sources list it (ingestion/seasons.capture_both), months before it
# airs, and a client that simply took the newest season on file would default
# every page to a season with no scores and nothing aired.
SEASON_START = (
    "make_date(season_year, CASE season WHEN 'WINTER' THEN 1 WHEN 'SPRING' THEN 4 "
    "WHEN 'SUMMER' THEN 7 ELSE 10 END, 1)"
)

# Where a season sits relative to a window of run dates: not yet started, on
# air during it, or already over before it began. Takes the window's bounds as
# SQL expressions, so a caller can pass columns or literals.
#
# A season is on air for its own quarter. Three months is the quarter, not any
# one show's run: a two-cour series from Summer is still airing in Fall, and a
# season-level figure cannot say which of its titles those are.
def season_phase(first_run: str, last_run: str) -> str:
    return (
        f"CASE WHEN {SEASON_START} > {last_run} THEN 'upcoming' "
        f"     WHEN {SEASON_START} + INTERVAL '3 months' > {first_run} THEN 'airing' "
        "      ELSE 'over' END"
    )


# The order the phases are read in: what is on now, what is finished, and last
# the season nobody has seen yet.
PHASE_ORDER = "CASE phase WHEN 'airing' THEN 0 WHEN 'over' THEN 1 ELSE 2 END"
