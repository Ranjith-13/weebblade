from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, DoubleType, IntegerType, StringType

# Popularity/favourites are kept as raw, source-native numbers - NOT normalized -
# because their semantics genuinely differ across sources: AniList's popularity is a
# follower-style count, while Jikan's and Kitsu's are RANKS (lower = more popular).
# Averaging or comparing them directly across sources would be meaningless. Only
# average_score gets normalized here, into score_100, since "rating out of 100" is a
# well-defined comparable scale once Jikan's 0-10 is rescaled.
_DOUBLE_COLUMNS = ["popularity", "favourites"]
_INT_COLUMNS = [
    "season_year",
    "episodes",
    "start_year",
    "start_month",
    "start_day",
    # rating_rank is a genuine rank over scored titles; user_count is a raw magnitude.
    # Both are source-native and NOT normalized across sources, for the same reason
    # popularity is not - see the note above.
    "rating_rank",
    "user_count",
]
_STRING_COLUMNS = [
    "source",
    "source_id",
    "title_romaji",
    "title_english",
    "title_native",
    "synopsis",
    "format",
    "status",
    "season",
    "source_material",
    "poster_url",
    # Added 2026-09: fields Kitsu already returned and the transform was discarding.
    "cover_url",      # wide banner art; 17% of the season - a rare enhancement, never a layout assumption
    "trailer_id",     # YouTube id; 57% of the season
    "slug",           # lets the UI link back to the source record
    "age_rating",
    # MAL's weekly broadcast slot, e.g. ("saturday", "23:30") in JST. Stored as
    # the slot rather than a computed next-airing date: the pipeline runs weekly,
    # so any precomputed date is stale within days, while a slot holds for a cour.
    "broadcast_day",
    "broadcast_time",
]
_ARRAY_COLUMNS = [
    "genres",
    "studios",
    # Parallel arrays rather than an array<struct>: every other list column here is
    # array<string>, and keeping that uniform means standardize_schema stays a set of
    # simple casts instead of needing struct reconciliation across three sources.
    # streaming_services[i] is the provider for streaming_urls[i].
    "streaming_services",
    "streaming_urls",
]


def standardize_schema(df: DataFrame) -> DataFrame:
    """Cast every shared column to a canonical type so DataFrames from different
    sources can be safely unioned.

    Each source's Parquet file otherwise carries whatever type its own JSON values
    happened to infer as (e.g. AniList's average_score is an int, Jikan's and Kitsu's
    are floats) - Spark's union refuses to reconcile mismatched types on its own.

    Columns this expects but the input doesn't have are added as typed NULLs rather
    than raising. Snapshots written before a field was introduced genuinely lack it
    (poster_url was added in 2026-09), and re-consolidating an older run_date - which
    is exactly what an Airflow backfill does - would otherwise fail on a missing
    column instead of just carrying nulls forward.
    """
    # The missing-column guard applies to EVERY type group, not just strings. It
    # used to cover strings only, which meant the docstring's promise above held for
    # poster_url but would have broken on the first new int or array column: a
    # backfill of a snapshot predating that column would raise instead of carrying
    # nulls forward. Adding rating_rank/user_count/streaming_* in 2026-09 is exactly
    # that case.
    for col, spark_type in (
        [(c, StringType()) for c in _STRING_COLUMNS]
        + [(c, IntegerType()) for c in _INT_COLUMNS]
        + [(c, DoubleType()) for c in _DOUBLE_COLUMNS]
        + [(c, ArrayType(StringType())) for c in _ARRAY_COLUMNS]
    ):
        if col not in df.columns:
            df = df.withColumn(col, F.lit(None).cast(spark_type))
        df = df.withColumn(col, F.col(col).cast(spark_type))

    df = df.withColumn("mal_id", F.col("mal_id").cast(IntegerType()))

    # duration arrives as an int (minutes) from AniList/Kitsu but a free-text string
    # from Jikan (e.g. "24 min per ep") - cast to string first so every row can be
    # parsed the same way regardless of source, then pull the leading number out.
    df = df.withColumn(
        "duration_minutes",
        F.regexp_extract(F.col("duration").cast(StringType()), r"(\d+)", 1).cast(IntegerType()),
    ).drop("duration")

    df = df.withColumn(
        "score_100",
        F.when(
            F.col("source") == "jikan", F.col("average_score").cast(DoubleType()) * 10
        ).otherwise(F.col("average_score").cast(DoubleType())),
    ).drop("average_score")

    return df
