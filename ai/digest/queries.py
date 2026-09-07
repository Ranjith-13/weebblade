# SQL run against the DuckDB warehouse's `anime_media_latest` view (see
# processing/duckdb_catalog.py) to gather the raw material for a digest prompt.
# `_latest` matters here specifically: `anime_media` keeps one row per title per
# weekly run, which would double/triple-count the same title once a few weeks of
# runs have accumulated.

TOP_RATED = """
    SELECT title_english, title_romaji, score_100, genres, source
    FROM anime_media_latest
    WHERE score_100 IS NOT NULL
    ORDER BY score_100 DESC
    LIMIT 10
"""

GENRE_COUNTS = """
    SELECT genre, COUNT(*) AS title_count
    FROM (SELECT UNNEST(genres) AS genre FROM anime_media_latest)
    GROUP BY genre
    ORDER BY title_count DESC
    LIMIT 10
"""

FORMAT_COUNTS = """
    SELECT format, COUNT(*) AS title_count
    FROM anime_media_latest
    GROUP BY format
    ORDER BY title_count DESC
"""

SEASON_SUMMARY = """
    SELECT season, season_year, COUNT(*) AS title_count, ROUND(AVG(score_100), 1) AS avg_score
    FROM anime_media_latest
    GROUP BY season, season_year
    ORDER BY season_year DESC, season DESC
"""

STATS_QUERIES = {
    "top_rated": TOP_RATED,
    "genre_counts": GENRE_COUNTS,
    "format_counts": FORMAT_COUNTS,
    "season_summary": SEASON_SUMMARY,
}
