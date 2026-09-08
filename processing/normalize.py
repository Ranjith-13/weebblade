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
_INT_COLUMNS = ["season_year", "episodes", "start_year", "start_month", "start_day"]
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
]
_ARRAY_COLUMNS = ["genres", "studios"]


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
    for col in _STRING_COLUMNS:
        if col not in df.columns:
            df = df.withColumn(col, F.lit(None).cast(StringType()))
    for col in _STRING_COLUMNS:
        df = df.withColumn(col, F.col(col).cast(StringType()))
    for col in _INT_COLUMNS:
        df = df.withColumn(col, F.col(col).cast(IntegerType()))
    for col in _DOUBLE_COLUMNS:
        df = df.withColumn(col, F.col(col).cast(DoubleType()))
    for col in _ARRAY_COLUMNS:
        df = df.withColumn(col, F.col(col).cast(ArrayType(StringType())))

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
