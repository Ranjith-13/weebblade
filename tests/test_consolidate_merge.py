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

from processing.consolidate import (  # noqa: E402
    _current_state,
    _merge_sources,
    _snapshots_upto,
    consolidate_catalogue,
)

# An explicit schema, because Spark cannot infer a type for a column that is
# None in every row - which is the normal case here, since the whole point is
# that each source leaves different columns empty.
SCHEMA = StructType(
    [
        StructField("source", StringType()),
        StructField("source_id", StringType()),
        StructField("mal_id", LongType()),
        StructField("title_romaji", StringType()),
        StructField("title_english", StringType()),
        StructField("studios", ArrayType(StringType())),
        StructField("source_material", StringType()),
        StructField("streaming_urls", ArrayType(StringType())),
        StructField("score_100", DoubleType()),
        StructField("season_year", LongType()),
        StructField("start_year", LongType()),
        StructField("start_month", LongType()),
        StructField("start_day", LongType()),
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
        "title_english": None,
        "studios": None,
        "source_material": None,
        "streaming_urls": None,
        "score_100": None,
        # The title passes require a start year, so fixtures need one; a merge
        # across different years is its own test below.
        "season_year": 2026,
        # The premiere pass needs a complete date; fixtures that care override it.
        "start_year": None,
        "start_month": None,
        "start_day": None,
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


def test_standardize_schema_survives_an_array_column_that_lost_its_type(spark):
    """A column that is null for every row in a snapshot loses its type through
    Parquet and reads back as INT. Scalars cope, because null casts to anything.
    Arrays do not: Spark refuses "cannot cast INT to ARRAY<STRING>" and the whole
    consolidation dies.

    This broke a live run the moment MAL started reporting "no streaming data" as
    null instead of [], which is the correct thing for it to say.
    """
    from pyspark.sql.types import IntegerType

    from processing.normalize import standardize_schema

    schema = StructType(
        [
            StructField("source", StringType()),
            StructField("source_id", StringType()),
            # what an all-null array column looks like after a Parquet round trip
            StructField("streaming_urls", IntegerType()),
        ]
    )
    df = spark.createDataFrame([("mal", "1", None)], schema)

    out = standardize_schema(df)

    assert isinstance(dict(out.dtypes)["streaming_urls"], str)
    assert dict(out.dtypes)["streaming_urls"] == "array<string>"
    assert out.collect()[0]["streaming_urls"] is None


def test_standardize_schema_tolerates_a_snapshot_missing_the_derived_columns(spark):
    """mal_id, duration and average_score are used by name, and were never
    covered by the missing-column guard, so the docstring's promise held for
    every column except those three. A snapshot predating any of them would
    raise UNRESOLVED_COLUMN instead of carrying nulls forward - which is exactly
    the backfill case the guard exists for."""
    from processing.normalize import standardize_schema

    schema = StructType(
        [StructField("source", StringType()), StructField("source_id", StringType())]
    )
    df = spark.createDataFrame([("kitsu", "1")], schema)

    out = standardize_schema(df).collect()[0]

    assert out["mal_id"] is None
    assert out["duration_minutes"] is None
    assert out["score_100"] is None


def test_the_display_title_pass_merges_transliteration_variants(spark):
    """Romaji is a transliteration and the two sources transliterate differently,
    so an exact romaji match misses pairs that are obviously the same show. All
    five live examples agree on the English title instead.

    Two of them have no English title on the Kitsu side, which is why the key
    coalesces: Kitsu's romaji is matched against MAL's English.
    """
    pairs = [
        ("Otome Kaiju Caramelise", "Kaiju Girl Caramelise",
         "Otome Kaijuu Caraméliser", "Kaiju Girl Caramelise"),
        ("Magical Girl Lyrical Nanoha EXCEEDS Gun Blaze Vengeance", None,
         "Mahou Shoujo Lyrical Nanoha EXCEEDS: Gun Blaze Vengeance",
         "Magical Girl Lyrical Nanoha EXCEEDS Gun Blaze Vengeance"),
        ("Koukaku Kidoutai: THE GHOST IN THE SHELL", "THE GHOST IN THE SHELL",
         "Koukaku Kidoutai (TV)", "The Ghost in the Shell"),
        ("Mairimashita! Iruma-kun 4", "Welcome to Demon School! Iruma-kun Season 4",
         "Mairimashita! Iruma-kun 4th Season", "Welcome to Demon School! Iruma-kun Season 4"),
        ("Yoroi-Shinden Samurai Troopers Part 2", None,
         "Yoroi Shin Den Samurai Troopers Part 2", "Yoroi-Shinden Samurai Troopers Part 2"),
    ]

    for i, (k_romaji, k_english, m_romaji, m_english) in enumerate(pairs):
        df = spark.createDataFrame(
            [
                _row("kitsu", str(i), None, title_romaji=k_romaji, title_english=k_english,
                     streaming_urls=["https://crunchyroll.com/x"]),
                _row("mal", str(1000 + i), 1000 + i, title_romaji=m_romaji,
                     title_english=m_english, studios=["Studio"]),
            ],
            SCHEMA_F,
        )
        out = _merge_sources(df)

        assert out.count() == 1, f"{k_romaji!r} did not merge with {m_romaji!r}"
        row = out.collect()[0]
        assert row["streaming_urls"] == ["https://crunchyroll.com/x"]  # from Kitsu
        assert row["studios"] == ["Studio"]  # from MAL


def test_the_display_title_pass_still_will_not_merge_across_formats(spark):
    """The widened key must not widen the risk. A movie and a series sharing an
    English title in one season stay separate, exactly as they do for romaji."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_romaji="A", title_english="Same Name", fmt="TV"),
            _row("mal", "2", 999, title_romaji="B", title_english="Same Name", fmt="movie"),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).count() == 2


def test_rows_sharing_no_title_at_all_are_left_alone(spark):
    """Two rows with no title and no format must not collapse into each other
    just because their keys are both absent."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_romaji=None, title_english=None, fmt=None),
            _row("mal", "2", None, title_romaji=None, title_english=None, fmt=None),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).count() == 2


def _touch(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"")
    return path


def test_every_snapshot_up_to_the_run_date_is_considered(tmp_path):
    _touch(tmp_path, "2026-06-15.parquet")
    _touch(tmp_path, "2026-09-07.parquet")
    _touch(tmp_path, "2026-09-09.parquet")

    names = [p.name for p in _snapshots_upto(tmp_path, "2026-09-09")]

    assert names == ["2026-06-15.parquet", "2026-09-07.parquet", "2026-09-09.parquet"]


def test_a_snapshot_from_after_the_run_date_is_not_used(tmp_path):
    """Re-running an old date must reproduce what that run would have seen,
    rather than pulling in data from its future."""
    _touch(tmp_path, "2026-06-15.parquet")
    _touch(tmp_path, "2026-09-09.parquet")

    assert [p.name for p in _snapshots_upto(tmp_path, "2026-07-01")] == ["2026-06-15.parquet"]


def test_a_source_that_never_ran_contributes_nothing(tmp_path):
    """Still not a hard error: a source that has never produced a snapshot is
    skipped, which is the normal case for anilist and jikan today."""
    assert _snapshots_upto(tmp_path / "never", "2026-09-09") == []
    _touch(tmp_path, "2026-09-09.parquet")
    assert _snapshots_upto(tmp_path, "2026-01-01") == []


def _write_snapshot(spark, directory, run_date, rows):
    """A dated snapshot, written the way the ingestion layer writes them."""
    schema = StructType(
        [
            StructField("source", StringType()),
            StructField("source_id", StringType()),
            StructField("title_romaji", StringType()),
        ]
    )
    spark.createDataFrame(rows, schema).write.mode("overwrite").parquet(
        str(directory / f"{run_date}.parquet")
    )


def test_a_source_not_refetched_this_run_still_reaches_the_merge(spark, tmp_path):
    """The bug that put 12 duplicate pairs in live data. Kitsu's Spring snapshot
    is dated 2026-06-15; consolidating on 2026-09-09 found no file for that date
    and dropped the source, so the merge never saw both halves of a title."""
    _write_snapshot(spark, tmp_path, "2026-06-15", [("kitsu", "49746", "Re:Zero 4th Season")])

    out = _current_state(spark, tmp_path, "2026-09-09").collect()

    assert [r["source_id"] for r in out] == ["49746"]


def test_the_newest_row_for_an_id_wins(spark, tmp_path):
    """A source that reports a title again should update it, not double it."""
    _write_snapshot(spark, tmp_path, "2026-06-15", [("kitsu", "1", "Old Title")])
    _write_snapshot(spark, tmp_path, "2026-09-09", [("kitsu", "1", "New Title")])

    out = _current_state(spark, tmp_path, "2026-09-09").collect()

    assert len(out) == 1
    assert out[0]["title_romaji"] == "New Title"


def test_a_title_dropped_from_the_latest_listing_keeps_its_last_seen_row(spark, tmp_path):
    """The two pairs a newest-file-only fallback would still have missed. Kitsu
    listed these on 2026-09-07 and not on 2026-09-09, so their last good row sits
    in the older snapshot while MAL's half is current. This is also exactly what
    anime_media_latest does downstream; doing it here lets the merge see the row."""
    _write_snapshot(
        spark, tmp_path, "2026-09-07", [("kitsu", "1", "Yami Shibai 17"), ("kitsu", "2", "Other")]
    )
    _write_snapshot(spark, tmp_path, "2026-09-09", [("kitsu", "2", "Other")])

    out = {r["source_id"]: r["title_romaji"] for r in _current_state(spark, tmp_path, "2026-09-09").collect()}

    assert out == {"1": "Yami Shibai 17", "2": "Other"}


def test_the_title_passes_will_not_merge_across_years(spark):
    """Catalogue-wide merging removed season as an implicit guard, so the year is
    an explicit one. Generic names recur - a music video called "Dirty Look" in
    one year is not the one from another."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_romaji="Dirty Look", fmt="music", season_year=2026),
            _row("mal", "2", 999, title_romaji="Dirty Look", fmt="music", season_year=2011),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).count() == 2


def test_a_row_with_no_start_year_is_never_title_merged(spark):
    """Missing the guard means the pass cannot be trusted, so the row keeps its
    own identity rather than merging on a weaker key."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_romaji="Same", fmt="TV", season_year=None),
            _row("mal", "2", 999, title_romaji="Same", fmt="TV", season_year=None),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).count() == 2


def _fresh_session():
    """consolidate_catalogue stops the session it uses, exactly as the DAG task
    expects. The module fixture cannot survive that, so the catalogue tests own
    their sessions instead of borrowing it."""
    return (
        SparkSession.builder.master("local[1]")
        .appName("weebblade-test-catalogue")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )


def _write_source(spark, data_dir, dir_name, partition, run_date, rows):
    schema = StructType(
        [
            StructField("source", StringType()),
            StructField("source_id", StringType()),
            StructField("title_romaji", StringType()),
            StructField("format", StringType()),
            StructField("season", StringType()),
            StructField("season_year", LongType()),
        ]
    )
    out = data_dir / "processed" / dir_name / partition / f"{run_date}.parquet"
    spark.createDataFrame(rows, schema).write.mode("overwrite").parquet(str(out))


def test_sources_that_disagree_about_the_season_still_merge(tmp_path):
    """The nine live duplicates that survived every per-partition fix.

    Kitsu files "Baki-dou Part 2" under Summer 2026 and MAL files it under Spring
    2026, so the two halves land in different partitions and a per-season merge
    never sees them together. Consolidating the catalogue as a whole does.
    """
    session = _fresh_session()
    _write_source(
        session, tmp_path, "kitsu_media", "2026-SUMMER", "2026-09-09",
        [("kitsu", "50635", "BAKI-DOU Part 2", "ONA", "SUMMER", 2026)],
    )
    _write_source(
        session, tmp_path, "mal_media", "2026-SPRING", "2026-09-09",
        [("mal", "63833", "Baki-dou Part 2", "ONA", "SPRING", 2026)],
    )

    out_dir = consolidate_catalogue(tmp_path, "2026-09-09")
    rows = _fresh_session().read.parquet(str(out_dir)).collect()

    assert len(rows) == 1
    assert rows[0]["source"] == "kitsu"  # priority order decides the survivor
    assert rows[0]["season"] == "SUMMER"  # and it keeps its own season


def test_the_catalogue_keeps_titles_that_are_genuinely_distinct(tmp_path):
    """The merge must not be so eager that consolidating everything at once
    starts deleting separate shows."""
    session = _fresh_session()
    _write_source(
        session, tmp_path, "kitsu_media", "2026-SPRING", "2026-09-09",
        [("kitsu", "1", "Spring Show", "TV", "SPRING", 2026)],
    )
    _write_source(
        session, tmp_path, "kitsu_media", "2026-SUMMER", "2026-09-09",
        [("kitsu", "2", "Summer Show", "TV", "SUMMER", 2026)],
    )

    out_dir = consolidate_catalogue(tmp_path, "2026-09-09")
    rows = _fresh_session().read.parquet(str(out_dir)).collect()

    assert sorted(r["title_romaji"] for r in rows) == ["Spring Show", "Summer Show"]


def test_sources_that_disagree_about_the_format_still_merge(spark):
    """The eight live pairs the format guard blocked. MAL files the Re:Zero
    break-time shorts as `special` and Kitsu as `ONA`, so every pass that keys on
    format misses them, and neither side carries a mal_id to match on.

    An identical title premiering on the identical day is the evidence here.
    """
    df = spark.createDataFrame(
        [
            _row("kitsu", "50665", None,
                 title_romaji="Re:Zero kara Hajimeru Kyuukei Jikan (Break Time) 4th Season",
                 title_english="Re:ZERO ~Starting Break Time From Zero~ Season 4",
                 fmt="ONA", start_year=2026, start_month=4, start_day=8),
            _row("mal", "63830", 63830,
                 title_romaji="Re:Zero kara Hajimeru Break Time 4th Season",
                 title_english="Re:ZERO ~Starting Break Time From Zero~ Season 4",
                 fmt="special", start_year=2026, start_month=4, start_day=8,
                 studios=["White Fox"]),
        ],
        SCHEMA_F,
    )
    out = _merge_sources(df)

    assert out.count() == 1
    row = out.collect()[0]
    assert row["source"] == "kitsu"
    assert row["studios"] == ["White Fox"]  # MAL's, kept through the merge


def test_the_premiere_pass_will_not_merge_titles_that_premiered_on_different_days(spark):
    """Three of the eight disagree on the date as well as the format, by one to
    four days. Left alone deliberately: a window wide enough to bridge them is
    wide enough to join a series to its compilation film."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_english="The Food Diary of Miss Maid",
                 fmt="ONA", start_year=2026, start_month=4, start_day=1),
            _row("mal", "2", 999, title_english="The Food Diary of Miss Maid",
                 fmt="TV", start_year=2026, start_month=4, start_day=5),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).count() == 2


def test_the_premiere_pass_needs_a_complete_date(spark):
    """A partial date would match far too much - every title that knows only its
    year would collide with every other one sharing a name."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_english="Same Name", fmt="ONA",
                 start_year=2026, start_month=None, start_day=None),
            _row("mal", "2", 999, title_english="Same Name", fmt="special",
                 start_year=2026, start_month=None, start_day=None),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).count() == 2


def test_a_series_and_its_film_sharing_a_title_and_year_stay_separate(spark):
    """The case the format guard exists for. The premiere pass drops format, so
    the date has to carry the weight: different works release on different days."""
    df = spark.createDataFrame(
        [
            _row("kitsu", "1", None, title_english="Franchise", fmt="TV",
                 start_year=2026, start_month=4, start_day=1),
            _row("kitsu", "2", None, title_english="Franchise", fmt="movie",
                 start_year=2026, start_month=11, start_day=20),
        ],
        SCHEMA_F,
    )
    assert _merge_sources(df).count() == 2
