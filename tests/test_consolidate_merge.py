"""Cross-source merge.

Adding a second live source doubles the catalogue unless rows describing the
same show are collapsed: Kitsu and MAL both carry BLEACH under different ids, so
a plain union puts every popular title in the UI twice.

These tests need a real SparkSession, so they only run where PySpark is
installed (CI). The merge is a window function over every column, which is
exactly the kind of thing that looks right and behaves differently at runtime.
"""

import pytest

pyspark = pytest.importorskip("pyspark", reason="PySpark not installed in this environment")

from pyspark.sql import SparkSession  # noqa: E402
from pyspark.sql.types import (  # noqa: E402
    ArrayType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from processing.consolidate import _merge_sources  # noqa: E402

# An explicit schema, because Spark cannot infer a type for a column that is
# None in every row - which is the normal case here, since the whole point is
# that each source leaves different columns empty.
SCHEMA = StructType(
    [
        StructField("source", StringType()),
        StructField("source_id", StringType()),
        StructField("mal_id", LongType()),
        StructField("title_romaji", StringType()),
        StructField("studios", ArrayType(StringType())),
        StructField("source_material", StringType()),
        StructField("streaming_urls", ArrayType(StringType())),
        StructField("score_100", DoubleType()),
    ]
)


@pytest.fixture(scope="module")
def spark():
    session = (
        SparkSession.builder.master("local[1]")
        .appName("weebblade-test-merge")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


def _row(source, source_id, mal_id, **overrides):
    row = {
        "source": source,
        "source_id": source_id,
        "mal_id": mal_id,
        "title_romaji": "BLEACH",
        "studios": None,
        "source_material": None,
        "streaming_urls": None,
        "score_100": None,
    }
    row.update(overrides)
    return tuple(row[f.name] for f in SCHEMA.fields)


def test_two_sources_describing_one_show_collapse_to_a_single_row(spark):
    df = spark.createDataFrame(
        [_row("kitsu", "49444", 41467), _row("mal", "41467", 41467)], SCHEMA
    )
    assert _merge_sources(df).count() == 1


def test_the_merge_is_per_column_not_a_row_level_pick(spark):
    """The point of the merge: one output row holding Kitsu's streaming links
    AND MAL's studios, neither of which the other source has."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "49444", 41467, streaming_urls=["https://hulu.com/x"]),
            _row("mal", "41467", 41467, studios=["Pierrot"], source_material="manga"),
        ],
        SCHEMA,
    )
    out = _merge_sources(df).collect()[0]

    assert out["streaming_urls"] == ["https://hulu.com/x"]  # only Kitsu had this
    assert out["studios"] == ["Pierrot"]  # only MAL had this
    assert out["source_material"] == "manga"


def test_kitsu_wins_a_genuine_conflict(spark):
    """Priority order is deliberate: every stored row already uses Kitsu's
    vocabulary, so it stays canonical where both sources disagree."""
    df = spark.createDataFrame(
        [
            _row("mal", "41467", 41467, title_romaji="Bleach: Sennen Kessen-hen"),
            _row("kitsu", "49444", 41467, title_romaji="BLEACH"),
        ],
        SCHEMA,
    )
    out = _merge_sources(df).collect()[0]

    assert out["title_romaji"] == "BLEACH"
    assert out["source"] == "kitsu"
    assert out["source_id"] == "49444"


def test_rows_without_a_mal_id_are_never_merged(spark):
    """A row with no join key cannot be matched to anything. Keeping it separate
    is the safe default: a false merge silently deletes a title, while a missed
    merge leaves a visible duplicate."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_romaji="Some Music Video"),
            _row("kitsu", "2", None, title_romaji="Another Music Video"),
        ],
        SCHEMA,
    )
    assert _merge_sources(df).count() == 2


def test_a_mal_id_cannot_collide_with_an_unrelated_source_id(spark):
    """Without namespacing the key, a title whose mal_id is 5 and an unrelated
    one whose source_id is "5" would merge into one row and a title would vanish."""
    df = spark.createDataFrame(
        [
            _row("mal", "5", 5, title_romaji="Has mal id five"),
            _row("kitsu", "5", None, title_romaji="Has source id five"),
        ],
        SCHEMA,
    )
    out = _merge_sources(df)

    assert out.count() == 2
    assert sorted(r["title_romaji"] for r in out.collect()) == [
        "Has mal id five",
        "Has source id five",
    ]


def test_merging_is_deterministic_across_repeated_runs(spark):
    """`first` inside a groupBy has no defined order, so an earlier version of
    this could return a different winning source between runs. The window is
    ordered for exactly this reason."""
    df = spark.createDataFrame(
        [
            _row("mal", "41467", 41467, title_romaji="from-mal"),
            _row("kitsu", "49444", 41467, title_romaji="from-kitsu"),
            _row("jikan", "41467", 41467, title_romaji="from-jikan"),
        ],
        SCHEMA,
    )
    winners = {_merge_sources(df).collect()[0]["title_romaji"] for _ in range(5)}

    assert winners == {"from-kitsu"}
