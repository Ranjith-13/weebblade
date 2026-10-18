from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

SYSTEM_INSTRUCTION = (
    "You are writing a short, engaging weekly trend digest for WeebBlade, an anime "
    "trend-tracking site. Use only the data given below - don't invent titles, scores, "
    "studios, or facts not present here. Write 3-5 short paragraphs in a casual but "
    "informative tone, covering standout/highly-rated titles this season, genre trends, "
    "and anything notable about format breakdown. Plain prose, no markdown headers. "
    # Said as well as fixed. The figures below are now all out of ten, but a
    # model handed 8.4 can still write "84%" or "8.36" if it decides to be
    # precise, and the digest sits directly beneath the site's own numbers.
    "Quote every score exactly as given, out of 10 to one decimal, like 8.4. "
    "Never rescale one, add a decimal place to one, or turn one into a percentage."
)

# Only when there is a changes section. The model is told what the lines are
# because a list of "X: 7.2 to 7.4" reads like the season's stats otherwise.
_CHANGES_INSTRUCTION = (
    "The last section lists what the sources changed since last week, in any season. "
    "Give it one paragraph: the changes a fan would care about most - finales, delays, "
    "new titles, big score moves - named from that list only. Do not present these as "
    "this season's statistics."
)

_STATUS_WORDS = {"current": "airing", "finished": "finished", "upcoming": "not yet aired"}

# Most lines of one kind a prompt carries; a busy week says how many were left out.
_PER_KIND = 12
# The smallest score move a digest names, in tenths of a point out of 10 - in
# whole tenths because 7.3 - 7.0 is 0.2999... in floating point.
_SCORE_NEWS_TENTHS = 3


def _out_of_ten(score_100: float | None) -> str | None:
    """A stored score as the site prints it: out of ten, one decimal.

    THE PROMPT WAS HANDING THE MODEL THE STORAGE SCALE. Scores are stored out of
    100 and displayed out of 10 everywhere a reader can see one
    (frontend/lib/types.scoreOutOfTen), and the top-rated list here passed
    "83.63/100" straight through. The model used what it was given, so the
    digest printed "an 83.63 rating" on a page whose every other element said
    8.4 - two numbers for one thing on one screen, and two decimal places of
    precision this product does not use anywhere.

    The prompt was also inconsistent with itself: score CHANGES were already
    described "out of 10" a few lines above, so the same paragraph could carry
    both scales.

    MATCHES scoreOutOfTen EXACTLY, which is the whole point of a shared scale.
    That function is `(score100 / 10).toFixed(1)`, and Python's round() is not
    the same operation: it rounds halves to even, so 72.5 became 7.2 where the
    site shows 7.3. Fixing the scale while leaving the rounding would have put
    the digest 0.1 away from the page on every exact tie, which is the same
    "two numbers for one thing" defect in a quieter form.

    Decimal over the FLOAT rather than over its string: 83.5 / 10 is not 8.35
    but 8.34999999999999964, and toFixed sees that too, so both answer 8.3.
    Quantizing Decimal("8.35") instead would answer 8.4 and disagree. Checked
    against node for 72.5, 83.5, 86.5, 83.63, 84.0, 68.5 and 79.95.
    """
    if score_100 is None:
        return None
    return str(Decimal(float(score_100) / 10).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _move(c: dict[str, Any]) -> int:
    """A score change's size in tenths; 0 for a first score, which has no move."""
    if c["old"] is None:
        return 0
    return abs(round(float(c["new"]) * 10) - round(float(c["old"]) * 10))


def _change_line(c: dict[str, Any]) -> str:
    title, old, new = c.get("title") or "Untitled", c.get("old"), c.get("new")
    field = c["field"]
    if field == "status":
        return f"{title}: now {_STATUS_WORDS.get(new, new)} (was {_STATUS_WORDS.get(old, old)})"
    if field == "listed":
        return f"{title} ({c.get('format') or 'format unknown'}): newly listed"
    if field == "score":
        return f"{title}: score {old or 'none'} to {new} out of 10"
    if field == "trailer":
        return f"{title}: trailer released"
    if field == "streaming":
        return f"{title}: now streaming on {c.get('label') or new}"
    what = {"episodes": "episode count", "premiere": "premiere date", "season": "season",
            "broadcast": "broadcast slot"}.get(field, field)
    return f"{title}: {what} {old or 'unknown'} to {new}"


def _changes_section(changes: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## What changed since last week (any season)"]
    by_field: dict[str, list[dict[str, Any]]] = {}
    for c in changes:
        by_field.setdefault(c["field"], []).append(c)
    for field in ("status", "season", "premiere", "listed", "episodes", "score", "trailer", "streaming", "broadcast"):
        rows = by_field.get(field, [])
        if field == "score":
            # Only moves a fan would notice, biggest first. The week to
            # 2026-09-13 had 51 score changes and every one was a tenth, several
            # crossing a rounding line and back: named, they read as news.
            small = [c for c in rows if c["old"] is not None and _move(c) < _SCORE_NEWS_TENTHS]
            rows = sorted((c for c in rows if c not in small), key=lambda c: -_move(c))
            if small:
                lines.append(f"- {len(small)} score moves under {_SCORE_NEWS_TENTHS / 10} out of 10, not listed")
        lines += [f"- {_change_line(c)}" for c in rows[:_PER_KIND]]
        if len(rows) > _PER_KIND:
            lines.append(f"- and {len(rows) - _PER_KIND} more {field} changes")
    return lines

# The season summary lists every season in the warehouse, not just the one being
# written about, so the model is told outright which rows are context and which
# are the subject. Without it a digest of Summer would happily quote Spring's
# numbers as its own.
_SCOPE_NOTE = (
    "The stats below describe {season} unless a section says otherwise. The season "
    "summary covers every season on record, for comparison only - do not present "
    "another season's figures as this season's."
)


def _season_name(stats: dict[str, list[dict[str, Any]]]) -> str | None:
    rows = stats.get("current_season") or []
    if not rows:
        return None
    row = rows[0]
    if not row.get("season") or not row.get("season_year"):
        return None
    return f"{row['season']} {row['season_year']}"


def build_prompt(stats: dict[str, list[dict[str, Any]]], changes: list[dict[str, Any]] | None = None) -> str:
    season = _season_name(stats)
    lines = [SYSTEM_INSTRUCTION]
    if changes:
        lines += ["", _CHANGES_INSTRUCTION]
    if season:
        lines += ["", _SCOPE_NOTE.format(season=season)]
    heading = f"## Top rated titles in {season}" if season else "## Top rated titles this season"
    lines += ["", heading]

    for row in stats["top_rated"]:
        title = row["title_english"] or row["title_romaji"] or "Untitled"
        genres = ", ".join(row["genres"]) if row["genres"] else "unlisted genres"
        lines.append(
            f"- {title}: {_out_of_ten(row['score_100'])} out of 10, "
            f"genres: {genres} (source: {row['source']})"
        )

    genres_heading = (
        f"## Most common genres in {season}" if season else "## Most common genres this season"
    )
    lines += ["", genres_heading]
    for row in stats["genre_counts"]:
        lines.append(f"- {row['genre']}: {row['title_count']} titles")

    formats_heading = (
        f"## Format breakdown for {season}" if season else "## Format breakdown"
    )
    lines += ["", formats_heading]
    for row in stats["format_counts"]:
        lines.append(f"- {row['format'] or 'unknown'}: {row['title_count']} titles")

    lines += ["", "## Season summary (every season on record, for comparison)"]
    for row in stats["season_summary"]:
        lines.append(
            f"- {row['season']} {row['season_year']}: {row['title_count']} titles, "
            f"average score {_out_of_ten(row['avg_score'])} out of 10"
        )

    if changes:
        lines += _changes_section(changes)

    return "\n".join(lines)
