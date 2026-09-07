from __future__ import annotations

from typing import Any

SYSTEM_INSTRUCTION = (
    "You are writing a short, engaging weekly trend digest for WeebBlade, an anime "
    "trend-tracking site. Use only the data given below - don't invent titles, scores, "
    "studios, or facts not present here. Write 3-5 short paragraphs in a casual but "
    "informative tone, covering standout/highly-rated titles this season, genre trends, "
    "and anything notable about format breakdown. Plain prose, no markdown headers."
)


def build_prompt(stats: dict[str, list[dict[str, Any]]]) -> str:
    lines = [SYSTEM_INSTRUCTION, "", "## Top rated titles this season"]

    for row in stats["top_rated"]:
        title = row["title_english"] or row["title_romaji"] or "Untitled"
        genres = ", ".join(row["genres"]) if row["genres"] else "unlisted genres"
        lines.append(
            f"- {title}: {row['score_100']}/100, genres: {genres} (source: {row['source']})"
        )

    lines += ["", "## Most common genres this season"]
    for row in stats["genre_counts"]:
        lines.append(f"- {row['genre']}: {row['title_count']} titles")

    lines += ["", "## Format breakdown"]
    for row in stats["format_counts"]:
        lines.append(f"- {row['format'] or 'unknown'}: {row['title_count']} titles")

    lines += ["", "## Season summary"]
    for row in stats["season_summary"]:
        lines.append(
            f"- {row['season']} {row['season_year']}: {row['title_count']} titles, "
            f"average score {row['avg_score']}"
        )

    return "\n".join(lines)
