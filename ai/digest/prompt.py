from __future__ import annotations

from typing import Any

SYSTEM_INSTRUCTION = (
    "You are writing a short, engaging weekly trend digest for WeebBlade, an anime "
    "trend-tracking site. Use only the data given below - don't invent titles, scores, "
    "studios, or facts not present here. Write 3-5 short paragraphs in a casual but "
    "informative tone, covering standout/highly-rated titles this season, genre trends, "
    "and anything notable about format breakdown. Plain prose, no markdown headers."
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
            # The biggest moves first: a tenth either way is barely news.
            rows = sorted(rows, key=lambda c: -abs(float(c["new"]) - float(c["old"] or c["new"])))
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
            f"- {title}: {row['score_100']}/100, genres: {genres} (source: {row['source']})"
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
            f"average score {row['avg_score']}"
        )

    if changes:
        lines += _changes_section(changes)

    return "\n".join(lines)
