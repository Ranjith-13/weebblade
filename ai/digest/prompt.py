from __future__ import annotations

from typing import Any

SYSTEM_INSTRUCTION = (
    "You are writing a short, engaging weekly trend digest for WeebBlade, an anime "
    "trend-tracking site. Use only the data given below - don't invent titles, scores, "
    "studios, or facts not present here. Write 3-5 short paragraphs in a casual but "
    "informative tone, covering standout/highly-rated titles this season, genre trends, "
    "and anything notable about format breakdown. Plain prose, no markdown headers."
)

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


def build_prompt(stats: dict[str, list[dict[str, Any]]]) -> str:
    season = _season_name(stats)
    lines = [SYSTEM_INSTRUCTION]
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

    return "\n".join(lines)
