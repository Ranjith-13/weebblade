# SQL run against the DuckDB warehouse's `anime_media_latest` view (see
# processing/duckdb_catalog.py) to gather the raw material for a digest prompt.
# `_latest` matters here specifically: `anime_media` keeps one row per title per
# weekly run, which would double/triple-count the same title once a few weeks of
# runs have accumulated.

# The industry's quarterly order, which is not the alphabetical one. Sorting
# season names DESC as text puts WINTER first and FALL last, exactly backwards,
# so "the newest season" would have been wrong the moment a Winter or Fall
# partition landed. The frontend has the same table in lib/api.ts.
_QUARTER = """
        CASE season
            WHEN 'WINTER' THEN 1
            WHEN 'SPRING' THEN 2
            WHEN 'SUMMER' THEN 3
            WHEN 'FALL' THEN 4
            ELSE 0
        END
"""

# Every "this season" query is scoped through this CTE.
#
# anime_media_latest spans every season ever ingested - 475 titles across two of
# them as of 2026-09-10 - while the prompt asks for a digest of "this season".
# Unscoped, the model was handed the whole catalogue and told it was one season,
# so its title counts and genre trends described a mixture of Spring and Summer
# and called it Summer.
_NEWEST_SEASON = f"""
    WITH newest AS (
        SELECT season, season_year
        FROM anime_media_latest
        WHERE season IS NOT NULL AND season_year IS NOT NULL
        GROUP BY season, season_year
        ORDER BY season_year DESC, {_QUARTER} DESC
        LIMIT 1
    )
"""

_IN_NEWEST = """
    FROM anime_media_latest m
    JOIN newest n ON m.season = n.season AND m.season_year = n.season_year
"""

# Named explicitly rather than inferred from season_summary's first row, so the
# prompt can say which season it means instead of leaving the model to guess.
CURRENT_SEASON = _NEWEST_SEASON + """
    SELECT season, season_year FROM newest
"""

TOP_RATED = _NEWEST_SEASON + f"""
    SELECT m.title_english, m.title_romaji, m.score_100, m.genres, m.source
    {_IN_NEWEST}
    WHERE m.score_100 IS NOT NULL
    ORDER BY m.score_100 DESC
    LIMIT 10
"""

GENRE_COUNTS = _NEWEST_SEASON + f"""
    SELECT genre, COUNT(*) AS title_count
    FROM (
        SELECT UNNEST(m.genres) AS genre
        {_IN_NEWEST}
    )
    GROUP BY genre
    ORDER BY title_count DESC
    LIMIT 10
"""

FORMAT_COUNTS = _NEWEST_SEASON + f"""
    SELECT m.format AS format, COUNT(*) AS title_count
    {_IN_NEWEST}
    GROUP BY m.format
    ORDER BY title_count DESC
"""

# Deliberately NOT scoped: this is the one section that earns its keep by being
# comparative. A digest of a season is more useful when the model can see how that
# season's size and average score sit against the ones before it.
SEASON_SUMMARY = f"""
    SELECT season, season_year, COUNT(*) AS title_count, ROUND(AVG(score_100), 1) AS avg_score
    FROM anime_media_latest
    WHERE season IS NOT NULL AND season_year IS NOT NULL
    GROUP BY season, season_year
    ORDER BY season_year DESC, {_QUARTER} DESC
"""

STATS_QUERIES = {
    "current_season": CURRENT_SEASON,
    "top_rated": TOP_RATED,
    "genre_counts": GENRE_COUNTS,
    "format_counts": FORMAT_COUNTS,
    "season_summary": SEASON_SUMMARY,
}

# What the sources changed in the week up to the newest fetch compared - this
# run's, since the digest runs after record_changes. Any season: a delay or a
# finale is news whichever season it belongs to. One row per title and change,
# however many sources told it. Kept out of STATS_QUERIES, which fail together:
# a warehouse with no changes recorded yet must still get its digest.
CHANGES_THIS_WEEK = """
    WITH newest AS (SELECT MAX(run_date) AS d FROM anime_change)
    SELECT c.field, c.old, c.new, ANY_VALUE(c.label) AS label, LIST(DISTINCT c.source) AS sources,
           COALESCE(m.title_english, m.title_romaji) AS title, m.format
    FROM anime_change c
    JOIN anime_media_latest m ON m.wb_id = c.wb_id
    CROSS JOIN newest
    WHERE c.run_date > strftime(CAST(newest.d AS DATE) - INTERVAL 7 DAY, '%Y-%m-%d')
    GROUP BY c.wb_id, c.field, c.old, c.new, m.title_english, m.title_romaji, m.format
    ORDER BY c.field, title, c.new
"""
