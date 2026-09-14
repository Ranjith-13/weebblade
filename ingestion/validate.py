"""Schema checks applied to flattened rows before they are written.

Every source's transform independently decides units and vocabulary, and nothing
ever checked the result. That is one root cause with a long tail - eleven
instances of it were found and fixed in this project, and two of them reached
production and stayed there for days:

  * MAL's `mean` is 0-10 and Kitsu's averageRating is 0-100. Both were written to
    a column called score_100. 124 of 227 scored titles sat on the wrong scale,
    sorted to the bottom of a score-ranked catalogue.
  * MAL's media_type is "tv" where Kitsu's subtype is "TV", so the frontend saw
    two different formats for one thing and the airing-now count missed every MAL
    row.
  * MAL's average_episode_duration is in SECONDS.
  * An empty list beat a populated one in the cross-source merge, because
    ignorenulls treats [] as a value.

None of those is exotic. They are all the same mistake - reconciling a source's
words while ignoring its units, or its shapes - and the next source added will
make it again unless something asserts the invariants.

WHAT THIS DELIBERATELY DOES NOT DO is fail on a single odd row. Sources publish
odd rows, and killing a season's ingest over one is a worse outcome than the odd
row. It fails on evidence of a CODE bug - a whole column on the wrong scale, a
vocabulary that differs only by case - and warns about everything else.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

logger = logging.getLogger(__name__)


class SchemaViolation(ValueError):
    """Raised when rows show evidence of a transform bug rather than odd data.

    A distinct type so a DAG task log reads "our code is wrong" rather than
    "the upstream API is being strange", which are very different things to be
    woken up by.
    """


# Kitsu's vocabulary, because Kitsu passes subtype and status straight through
# and every stored row already uses it. Other sources map onto these.
_FORMATS = {"TV", "movie", "OVA", "ONA", "special", "music"}
_STATUSES = {"current", "finished", "upcoming", "unreleased", "tba"}
_SEASONS = {"WINTER", "SPRING", "SUMMER", "FALL"}
# MAL's tokens, because MAL was the only source of this column until AniList,
# and the "adapted from" facet is built from them. AniList's "MANGA" would have
# sat beside MAL's "manga" as a second chip, and nothing checked.
_SOURCE_MATERIALS = {
    "original", "manga", "4_koma_manga", "web_manga", "digital_manga", "novel",
    "light_novel", "web_novel", "visual_novel", "game", "card_game", "book",
    "picture_book", "radio", "music", "mixed_media", "other",
}

_ENUMS = {
    "format": _FORMATS,
    "status": _STATUSES,
    "season": _SEASONS,
    "source_material": _SOURCE_MATERIALS,
}

# Checked for type, not emptiness - see _check_list_columns for why [] is only
# worth a warning here.
_LIST_COLUMNS = ("genres", "studios", "streaming_services", "streaming_urls")

# A scored column whose every value fits in 0-10 is not a 0-100 column. Needs
# enough rows to mean anything: a season with three scored titles could sit that
# low by chance, a season with twenty could not.
_SCALE_SAMPLE_MIN = 20
_TEN_POINT_CEILING = 10.0

# Nothing episodic runs five hours. A median above this is a unit error, not a
# long film - films are checked more loosely below because they genuinely vary.
_DURATION_MEDIAN_CEILING = 300

# Unknown enum values below this are treated as the source publishing something
# new; above it, as our mapping having broken.
_UNKNOWN_ENUM_FRACTION = 0.2


def validate_rows(rows: list[dict[str, Any]], source: str) -> None:
    """Check flattened rows for evidence of a transform bug. Raises SchemaViolation.

    Call between flattening and writing - that is the boundary where a source's
    own vocabulary and units are supposed to have become this project's.
    """
    if not rows:
        logger.warning("[%s] no rows to validate", source)
        return

    problems: list[str] = []
    problems += _check_identity(rows, source)
    problems += _check_enums(rows, source)
    problems += _check_score_scale(rows, source)
    problems += _check_duration_units(rows, source)
    problems += _check_list_columns(rows, source)

    if problems:
        raise SchemaViolation(
            f"{source}: {len(problems)} schema problem(s) in {len(rows)} rows:\n  - "
            + "\n  - ".join(problems)
        )

    logger.info("[%s] %s rows passed schema validation", source, len(rows))


def _check_identity(rows: list[dict[str, Any]], source: str) -> list[str]:
    """source and source_id are the merge's join key and the view's dedupe key.
    A row missing either cannot be addressed by anything downstream."""
    missing = sum(1 for r in rows if not r.get("source") or not r.get("source_id"))
    if missing:
        return [f"{missing} row(s) missing source or source_id"]

    wrong_source = {r["source"] for r in rows} - {source}
    if wrong_source:
        return [f"rows labelled with an unexpected source: {sorted(wrong_source)}"]
    return []


def _check_enums(rows: list[dict[str, Any]], source: str) -> list[str]:
    """Vocabulary drift, of which case is the tell.

    A value that matches a known one case-insensitively but not exactly is
    always a mapping bug - "tv" for "TV" is the exact shape of the MAL bug, and
    no source legitimately publishes both. A value that matches nothing at all is
    more likely the source having added something, so it only fails when it has
    spread across a fifth of the rows.
    """
    problems = []
    for field, allowed in _ENUMS.items():
        present = [r.get(field) for r in rows if r.get(field) is not None]
        if not present:
            continue

        lower_allowed = {a.lower(): a for a in allowed}
        case_wrong, unknown = set(), set()
        for value in present:
            if value in allowed:
                continue
            if str(value).lower() in lower_allowed:
                case_wrong.add(value)
            else:
                unknown.add(value)

        for value in sorted(case_wrong):
            problems.append(
                f"{field}={value!r} differs only in case from "
                f"{lower_allowed[str(value).lower()]!r} - the vocabulary was not reconciled"
            )

        if unknown:
            share = sum(1 for v in present if v in unknown) / len(present)
            message = f"{field} has unrecognised value(s) {sorted(unknown)}"
            if share > _UNKNOWN_ENUM_FRACTION:
                problems.append(f"{message} across {share:.0%} of rows - mapping looks broken")
            else:
                logger.warning("[%s] %s (%.0f%% of rows) - new upstream value?", source, message, share * 100)
    return problems


def _check_score_scale(rows: list[dict[str, Any]], source: str) -> list[str]:
    """The bug that shipped. 0-10 stored in a column called score_100.

    A range check alone would never have caught it: 8.72 is a perfectly valid
    score out of 100. What gives it away is the ceiling - every MAL score sat
    under 10 while Kitsu's spanned 5 to 87.
    """
    scores = [r["average_score"] for r in rows if r.get("average_score") is not None]
    if not scores:
        return []

    problems = []
    out_of_range = [s for s in scores if s < 0 or s > 100]
    if out_of_range:
        problems.append(
            f"average_score outside 0-100: {sorted(out_of_range)[:3]} "
            f"({len(out_of_range)} of {len(scores)})"
        )

    if len(scores) >= _SCALE_SAMPLE_MIN and max(scores) <= _TEN_POINT_CEILING:
        problems.append(
            f"all {len(scores)} scores are <= {_TEN_POINT_CEILING:g} (max {max(scores):g}) - "
            "this looks like a 0-10 scale in a 0-100 column; multiply by 10 in the transform"
        )
    return problems


def _check_duration_units(rows: list[dict[str, Any]], source: str) -> list[str]:
    """MAL reports average_episode_duration in seconds; the column is minutes.

    Uses the median, not the max: a single long value is a feature-length special,
    while a whole column an order of magnitude too big is a unit error.
    """
    durations = [r["duration"] for r in rows if r.get("duration")]
    if not durations:
        return []

    median = statistics.median(durations)
    if median > _DURATION_MEDIAN_CEILING:
        return [
            f"median duration is {median:g} (over {_DURATION_MEDIAN_CEILING}) - "
            "this looks like seconds in a minutes column"
        ]

    negative = [d for d in durations if d < 0]
    if negative:
        return [f"negative duration(s): {sorted(negative)[:3]}"]
    return []


def _check_list_columns(rows: list[dict[str, Any]], source: str) -> list[str]:
    """A wrong type here is a bug. An empty list is only untidy.

    The first version of this failed on [] and would have broken every ingest run
    in the project: MAL emits studios=[] for 82 of 219 Spring rows, Kitsu emits
    genres=[] and streaming_services=[] routinely, and all of it is written by
    ordinary list comprehensions over nothing.

    [] beating real data WAS a live bug, but it was fixed where it actually
    mattered - `F.when(F.size(col) > 0, col)` in the merge, with a test - so a
    source emitting [] no longer costs anything. Failing an ingest over it would
    be enforcing a convention the system does not need, at the price of the data.
    Worth a warning, because None is still the clearer signal, and worth nothing
    more than that.
    """
    problems = []
    for field in _LIST_COLUMNS:
        empties = sum(1 for r in rows if r.get(field) == [])
        if empties:
            logger.warning(
                "[%s] %s is [] in %s of %s rows - None reads better, though the merge "
                "already treats an empty list as absence",
                source,
                field,
                empties,
                len(rows),
            )
        wrong_type = sum(
            1 for r in rows if r.get(field) is not None and not isinstance(r.get(field), list)
        )
        if wrong_type:
            problems.append(f"{field} is not a list in {wrong_type} row(s)")
    return problems
