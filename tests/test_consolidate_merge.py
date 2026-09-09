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

# The title fallback keys on format, so the fixtures need one.
SCHEMA_F = StructType(list(SCHEMA.fields) + [StructField("format", StringType())])


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
    fmt = overrides.pop("fmt", "TV")
    row.update(overrides)
    row["format"] = fmt
    return tuple(row[f.name] for f in SCHEMA_F.fields)


def test_two_sources_describing_one_show_collapse_to_a_single_row(spark):
    df = spark.createDataFrame(
        [_row("kitsu", "49444", 41467), _row("mal", "41467", 41467)], SCHEMA_F
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
        SCHEMA_F,
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
        SCHEMA_F,
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
        SCHEMA_F,
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
        SCHEMA_F,
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
        SCHEMA_F,
    )
    winners = {_merge_sources(df).collect()[0]["title_romaji"] for _ in range(5)}

    assert winners == {"from-kitsu"}


def test_a_kitsu_row_with_no_mal_mapping_still_merges_with_its_mal_twin(spark):
    """The second pass. 14 Kitsu rows in the live Summer 2026 data carry no MAL
    mapping, so their MAL twins survived the id pass as visible duplicates."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "50804", None, title_romaji="Aware! Meisaku-kun (2026)",
                 streaming_urls=["https://crunchyroll.com/x"]),
            _row("mal", "63219", 63219, title_romaji="Aware! Meisaku-kun (2026)",
                 studios=["Shin-Ei"]),
        ],
        SCHEMA_F,
    )
    out = _merge_sources(df)

    assert out.count() == 1
    row = out.collect()[0]
    assert row["streaming_urls"] == ["https://crunchyroll.com/x"]  # from Kitsu
    assert row["studios"] == ["Shin-Ei"]  # from MAL
    assert row["mal_id"] == 63219  # the id the Kitsu row lacked


def test_the_title_pass_will_not_merge_across_different_formats(spark):
    """A movie and a TV series can share a title in the same season. Requiring
    the format to match keeps the fallback from deleting one of them."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_romaji="Same Name", fmt="TV"),
            _row("mal", "2", 999, title_romaji="Same Name", fmt="movie"),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).count() == 2


def test_rows_with_no_format_are_not_merged_by_title(spark):
    """Without a format to corroborate it, a bare title match is too weak."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_romaji="Untitled", fmt=None),
            _row("mal", "2", 888, title_romaji="Untitled", fmt=None),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).count() == 2


def test_an_empty_array_loses_to_a_populated_one_from_a_lower_priority_source(spark):
    """An empty array is an absence, not a value.

    This is a real bug that shipped: Kitsu emitted studios as [] meaning "no
    studio data here", ignorenulls accepted it as a value, and because Kitsu
    outranks MAL every merged row came out with no studios while MAL's populated
    list sat right there. Verified live on BLEACH before the fix.
    """
    df = spark.createDataFrame(
        [
            _row("kitsu", "49444", 41467, studios=[]),
            _row("mal", "41467", 41467, studios=["Pierrot"]),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).collect()[0]["studios"] == ["Pierrot"]
