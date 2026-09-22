from __future__ import annotations

import logging
from pathlib import Path

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType

from . import identity, matching
from .bridge import OUT_NAME as bridge_file
from .normalize import standardize_schema
from .spark import get_spark_session

logger = logging.getLogger(__name__)

SOURCE_DIR_NAMES = {
    "anilist": "anilist_media",
    "jikan": "jikan_media",
    "mal": "mal_media",
    "kitsu": "kitsu_media",
}

# Which source wins when two of them describe the same show. Lower is preferred.
#
# Kitsu leads not because it is richer but because it is the source that has been
# live throughout: every stored row already uses its vocabulary for `format` and
# `status`, and it is the only source carrying streaming links, trailers and
# cover art. MAL then fills the gaps Kitsu cannot - studios and source_material
# are null for 100% of Kitsu rows - and supplies scores for titles Kitsu has
# never rated.
#
# AniList comes after MAL. It was placed above MAL when this merge was written,
# while AniList was down, so the placement was never exercised; it first
# delivered data after five years of the catalogue had been built from Kitsu
# and MAL. Ranked second, its first run
# would have replaced MAL's score on every title it holds that Kitsu has not
# rated, and MAL's studio spellings with its own ("Studio DEEN", "J.C.STAFF").
# A new source fills gaps - a title the others lack, a score MAL has none for -
# and moving it up is a decision to make on evidence, not a side effect of
# switching it on.
#
# This is a field-level merge, not a row-level pick: for every column the first
# non-null value in this order wins, so a title takes its streaming links from
# Kitsu and its studios from MAL in the same row.
_SOURCE_PRIORITY = ["kitsu", "mal", "anilist", "jikan"]

# Carried through every merge pass as the union of its members, never as a winner.
_SOURCE_KEYS = "source_keys"


def _snapshots_upto(source_dir: Path, run_date: str) -> list[Path]:
    """Every snapshot a source has produced for this partition, oldest first.

    Bounded by `<= run_date` so re-running an old date reproduces what that run
    would have seen, rather than pulling in snapshots from its future.
    """
    if not source_dir.is_dir():
        return []
    return sorted(p for p in source_dir.glob("*.parquet") if p.stem <= run_date)


def _current_state(
    spark, source_dir: Path, run_date: str, keep_snapshot: bool = False
) -> DataFrame | None:
    """One source's current view of a season: the latest row per id across all of
    its snapshots, not just the file dated today.

    Reading a single dated file was the bug behind 12 duplicate pairs in live
    data. Sources are not fetched on the same day - Kitsu's Spring 2026 snapshot
    is dated 2026-06-15 and MAL's 2026-09-09 - so an exact-date lookup found no
    Kitsu file and skipped the source outright. `_merge_sources` can only merge
    rows it is handed, and nothing downstream could repair it: the DuckDB
    `anime_media_latest` view dedupes by (source, source_id), which differs
    between the two halves of a title, so both survived forever.

    Taking the newest earlier file instead would still have missed two more
    pairs, where the source WAS fetched today but had dropped the title from its
    listing, leaving its last good row in an older snapshot. Reducing over every
    snapshot covers both, and it is the same rule `anime_media_latest` already
    applies downstream - a title keeps its last-seen row until a source reports a
    newer one. Applying it here just means the merge gets to see that row.
    """
    paths = _snapshots_upto(source_dir, run_date)
    if not paths:
        return None

    df = None
    for path in paths:
        frame = standardize_schema(spark.read.parquet(str(path))).withColumn(
            "_snapshot", F.lit(path.stem)
        )
        df = frame if df is None else df.unionByName(frame)

    newest = Window.partitionBy("source", "source_id").orderBy(F.col("_snapshot").desc())
    df = df.withColumn("_rn", F.row_number().over(newest)).filter(F.col("_rn") == 1).drop("_rn")
    # Which snapshot a row came from is private to this function, except to a
    # caller that unions several partitions and has to apply the same rule again
    # across them - see consolidate_catalogue.
    return df if keep_snapshot else df.drop("_snapshot")


def consolidate_partition(data_dir: Path, partition: str, run_date: str) -> Path | None:
    """Union whichever sources have a snapshot for this partition, newest first.

    Sources that failed to fetch (or haven't run at all) are skipped with a warning,
    not treated as a hard error - this is meant to run even when some upstream
    sources are down, which is the normal case right now (see PROGRESS.md).

    Each source contributes its CURRENT state for the partition - the latest row
    per id across all of its snapshots - rather than only the file dated today, so
    the merge always sees every source that has ever reported on the season. See
    `_current_state`.
    """
    spark = get_spark_session("weebblade-consolidate")
    frames: list[DataFrame] = []

    for source, dir_name in SOURCE_DIR_NAMES.items():
        source_dir = data_dir / "processed" / dir_name / partition
        snapshots = _snapshots_upto(source_dir, run_date)
        df = _current_state(spark, source_dir, run_date)
        if df is None:
            logger.warning("No snapshot for %s under %s, skipping", source, source_dir)
            continue
        logger.info(
            "Loaded %s rows from %s (%s snapshot(s), newest %s)",
            df.count(),
            source,
            len(snapshots),
            snapshots[-1].stem,
        )
        frames.append(df)

    if not frames:
        logger.warning(
            "No source data available for partition %s / %s - nothing to consolidate",
            partition,
            run_date,
        )
        spark.stop()
        return None

    consolidated = frames[0]
    for df in frames[1:]:
        consolidated = consolidated.unionByName(df)

    consolidated = _merge_sources(consolidated)

    # run_date as a real column, not just a path component - lets the DuckDB catalog
    # pick the latest snapshot per title once multiple weekly runs have landed (see
    # duckdb_catalog.anime_media_latest), and supports trend-over-time queries later.
    consolidated = consolidated.withColumn("run_date", F.lit(run_date))

    out_dir = data_dir / "processed" / "anime_media_consolidated" / partition / run_date
    consolidated.coalesce(1).write.mode("overwrite").parquet(str(out_dir))
    logger.info("Wrote consolidated output to %s", out_dir)

    spark.stop()
    return out_dir


def consolidate_catalogue(data_dir: Path, run_date: str) -> Path | None:
    """Consolidate every season at once, rather than one season at a time.

    Fetching is per season because that is how the upstream APIs are shaped, but
    entity resolution is not a per-season question: a show is one entity, and the
    sources do not always agree which season it belongs to. Kitsu placed nine live
    titles in Summer 2026 that MAL placed in Spring 2026, so each pair sat in a
    different partition and no per-partition merge could ever collapse them. They
    were visible as duplicates on the site for exactly that reason.

    Writing one output for the whole catalogue also keeps `anime_media_latest`
    unambiguous: with per-partition outputs at the same run_date, a title that
    moved between partitions had two rows with equal run_date and no tiebreak.
    """
    spark = get_spark_session("weebblade-consolidate")
    frames: list[DataFrame] = []

    for source, dir_name in SOURCE_DIR_NAMES.items():
        base = data_dir / "processed" / dir_name
        if not base.is_dir():
            logger.warning("No data at all for %s, skipping", source)
            continue
        for partition_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            df = _current_state(spark, partition_dir, run_date, keep_snapshot=True)
            if df is None:
                continue
            df = df.withColumn("_partition", F.lit(partition_dir.name))
            logger.info("Loaded %s rows from %s/%s", df.count(), source, partition_dir.name)
            frames.append(df)

    if not frames:
        logger.warning("No source data available at all - nothing to consolidate")
        spark.stop()
        return None

    consolidated = frames[0]
    for df in frames[1:]:
        consolidated = consolidated.unionByName(df)

    # _current_state keeps one row per id WITHIN a partition. One source can hold
    # a row for the same id under two of them: the pipeline fetches the next
    # season alongside the running one, and a source that re-files a title
    # between the two leaves its old row behind in the old partition, where it
    # stays by design - a source's last word about a title is kept until it says
    # something newer. Both rows reach the merge, and its tiebreak (priority,
    # source, source_id) is identical for the pair, so without this the winner,
    # and the season the title is filed under, would be whichever Spark read
    # first. Newest snapshot wins: a source's latest word about a title is the
    # one that counts.
    #
    # The earlier season breaks the remaining tie, where ONE fetch listed the
    # title under both - a split-cour, listed in the season it starts in and
    # again in the season it runs into. A title is filed under the season it
    # premiered in (the season index says so in as many words), so the earlier
    # listing is the right one. Partition name cannot decide this: sorted as
    # text, 2026-SUMMER comes after 2026-FALL. It is the last resort only for
    # rows whose season is unknown, where any fixed answer will do.
    quarter = F.create_map(
        *[
            x
            for s, q in (("WINTER", 1), ("SPRING", 2), ("SUMMER", 3), ("FALL", 4))
            for x in (F.lit(s), F.lit(q))
        ]
    )
    across = Window.partitionBy("source", "source_id").orderBy(
        F.col("_snapshot").desc(),
        (F.col("season_year") * 10 + quarter[F.col("season")]).asc_nulls_last(),
        F.col("_partition").asc(),
    )
    consolidated = (
        consolidated.withColumn("_rn", F.row_number().over(across))
        .filter(F.col("_rn") == 1)
        .drop("_rn", "_snapshot", "_partition")
    )

    consolidated = _adopt_bridged_mal_ids(consolidated, data_dir)

    before = consolidated.count()
    consolidated = _merge_sources(consolidated).withColumn("run_date", F.lit(run_date))
    logger.info("Merged %s source rows into %s titles", before, consolidated.count())

    consolidated = _stamp_identities(spark, consolidated, data_dir, run_date)

    out_dir = data_dir / "processed" / "anime_media_consolidated" / "_catalogue" / run_date
    consolidated.coalesce(1).write.mode("overwrite").parquet(str(out_dir))
    logger.info("Wrote consolidated catalogue to %s", out_dir)

    spark.stop()
    return out_dir


def _adopt_bridged_mal_ids(df: DataFrame, data_dir: Path) -> DataFrame:
    """Give a row the MAL id it should carry, where its sources are silent or
    wrong.

    Silent: the catalogue held eleven shows twice, each a Kitsu row with no MAL
    id whose twin was already there under another name - Zhu Xian Final beside
    Jade Dynasty Final Season. No rule here could see it: one name is a
    romanised Chinese title and the other its English name, or one says "2" and
    the other "2nd Season".

    Wrong: Kitsu maps its row for Yao Shen Ji 6 to the MAL id of Yao Shen Ji
    7th Season, and the first rule then merged two different seasons into one
    title, confidently, because a wrong MAL id looks exactly like a right one.

    Either way the merge itself is unchanged - a row carries the id it should,
    and the rules do the rest. Which id that is, and on what evidence, is
    processing/bridge.py's decision. A fill never overrules a source; only a
    correction does, and only where a second source contradicted the first and
    MAL's own row for the proposed id premiered on this row's day.

    Here only in consolidate_catalogue, not in consolidate_partition: the twin
    is usually in another season's partition, which is the whole reason the
    catalogue is consolidated as a whole.
    """
    bridge = data_dir / "processed" / bridge_file
    if not bridge.exists():
        return df

    ids = (
        df.sparkSession.read.parquet(str(bridge))
        .withColumnRenamed("mal_id", "_bridged_mal_id")
        .withColumnRenamed("source_key", "_bridged_key")
        .withColumnRenamed("action", "_bridged_action")
    )
    joined = df.join(
        ids, F.concat_ws(":", F.col("source"), F.col("source_id")) == F.col("_bridged_key"), "left"
    )
    counts = {
        row["_bridged_action"]: row["n"]
        for row in joined.filter(F.col("_bridged_key").isNotNull())
        .groupBy("_bridged_action").count().withColumnRenamed("count", "n").collect()
    }
    logger.info(
        "MAL ids: %s row(s) given one that had none, %s corrected",
        counts.get("fill", 0), counts.get("replace", 0),
    )
    return joined.withColumn(
        "mal_id",
        F.when(F.col("_bridged_action") == "replace", F.col("_bridged_mal_id").cast("long"))
        .otherwise(F.coalesce(F.col("mal_id"), F.col("_bridged_mal_id").cast("long"))),
    ).drop("_bridged_key", "_bridged_mal_id", "_bridged_action")


def _stamp_identities(spark, df: DataFrame, data_dir: Path, run_date: str) -> DataFrame:
    """Give every merged title its stable WeebBlade identity.

    The assignment itself is plain Python over a few hundred rows (see
    processing/identity.py) - the catalogue is small, the logic is branchy, and
    keeping it out of Spark is what makes it testable on a machine without a
    JVM. Spark only does the join back.

    The registry is saved BEFORE the catalogue is written. If the write then
    fails, the identities minted this run are already on record and the retry
    reuses them rather than minting a second set.
    """
    rows = df.select("source", "source_id", _SOURCE_KEYS).collect()
    groups = [list(r[_SOURCE_KEYS]) for r in rows]

    ids, registry, report = identity.assign(groups, identity.load(data_dir), run_date)
    path = identity.save(data_dir, registry)
    logger.info("Identities for %s titles: %s (registry %s)", len(ids), report, path)

    mapping = spark.createDataFrame(
        [(r["source"], r["source_id"], wb_id) for r, wb_id in zip(rows, ids)],
        "source string, source_id string, wb_id string",
    )
    # (source, source_id) is unique per merged row - each is the winner of exactly
    # one group - so this join cannot fan out.
    return df.join(mapping, ["source", "source_id"], "left")


def _merge_sources(df: DataFrame) -> DataFrame:
    """Collapse rows from different sources that describe the same show.

    Without this, adding a second live source doubles the catalogue: Kitsu and
    MAL both carry BLEACH under different ids, and a plain union keeps both, so
    every popular title appears twice in the UI.

    Which rows are one title is decided in processing/matching.py, over every
    row's own ids and titles; Spark then merges each group. The merge is
    per-column, taking the first non-null value in source-priority order, so one
    output row holds Kitsu's streaming links and MAL's studios at once.

    Every output row also carries `source_keys`: the source:source_id of every
    input row that collapsed into it. The merge picks one winner per column, but
    identity needs all of them - a title must keep its address when a different
    member wins next week, and the only way to know it is the same title is to
    know every key it was ever made of. See processing/identity.py.
    """
    own_key = F.concat_ws(":", F.col("source"), F.col("source_id"))
    df = df.withColumn(_SOURCE_KEYS, F.array(own_key))

    rows = [r.asDict() for r in df.select(*matching.FIELDS).collect()]
    groups, report = matching.group(rows)
    logger.info("Matched %s", report)

    mapping = df.sparkSession.createDataFrame(
        sorted(groups.items()), "_node string, _group string"
    )
    # The coalesce is a guard, not a path: every row's node is in the mapping.
    # A row somehow missing from it must stay a title of its own, never share a
    # null key with every other such row.
    df = (
        df.withColumn("_node", own_key)
        .join(mapping, "_node", "left")
        .withColumn("_group", F.coalesce(F.col("_group"), F.col("_node")))
        .drop("_node")
    )
    return _merge_on(df, F.col("_group")).drop("_group")


def _merge_on(df: DataFrame, key: "F.Column") -> DataFrame:
    """Group by `key` and take the first non-null value of every column in
    source-priority order.

    An ORDERED window, not groupBy(...).agg(first(...)): inside a groupBy,
    `first` has no defined order, so which source won would vary between runs.
    The frame must span the whole partition or `first` only sees rows up to the
    current one.
    """
    priority = F.create_map(
        *[x for i, s in enumerate(_SOURCE_PRIORITY) for x in (F.lit(s), F.lit(i))]
    )
    df = df.withColumn(
        "_priority", F.coalesce(priority[F.col("source")], F.lit(len(_SOURCE_PRIORITY)))
    ).withColumn("_key", key)

    # source and source_id break ties within one priority. Two rows of a group can
    # share a source - a source listing one show twice - and priority alone then
    # leaves both `first` and the genre order to whatever Spark reads first.
    window = (
        Window.partitionBy("_key")
        .orderBy("_priority", "source", "source_id")
        .rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing)
    )
    # An EMPTY ARRAY is not a value, it is an absence, and treating it as a value
    # is a real bug this hit: Kitsu emitted studios as [] meaning "no studio data
    # here", ignorenulls accepted it, and because Kitsu outranks MAL every merged
    # row ended up with no studios at all while MAL's populated list sat right
    # there. Sources now emit null instead, and this makes the merge immune
    # regardless of what any future source does.
    fields = {f.name: f.dataType for f in df.schema.fields}

    def meaningful(name: str) -> "F.Column":
        col = F.col(name)
        if isinstance(fields.get(name), ArrayType):
            return F.when(F.size(col) > 0, col)
        return col

    def aggregate(name: str) -> "F.Column":
        # Every other column takes one winner. source_keys takes the union: it is
        # the record of which rows became this one, and dropping all but the
        # winner's would lose exactly what identity needs to recognise the title
        # when a different member wins. Sorted so the result is deterministic.
        if name == _SOURCE_KEYS:
            return F.array_sort(
                F.array_distinct(F.flatten(F.collect_list(F.col(name)).over(window)))
            ).alias(name)

        # Genres are tags, and tags add: a title is Iyashikei if any source says
        # so. Taking one winner's whole list threw away every tag the other
        # source had - MAL's Iyashikei appeared 13 times across its snapshots
        # but on 3 catalogue titles, because wherever Kitsu also held the show,
        # Kitsu's list won outright and MAL's was dropped.
        #
        # NOT sorted, unlike source_keys: collected in window order, so the
        # higher-priority source's genres lead and the other's follow. A title's
        # first genre stays Kitsu's canonical one.
        #
        # Safe only because MAL's genre names are mapped onto Kitsu's at ingest.
        # Without that, a union would put "Sci-Fi" and "Science Fiction" on the
        # same title - the source split moved inside a single row.
        #
        # The other list columns are deliberately left alone. streaming_services
        # and streaming_urls are PARALLEL arrays, services[i] labelling urls[i];
        # unioning them independently would pair every link with the wrong name.
        if name == "genres":
            union = F.array_distinct(F.flatten(F.collect_list(F.col(name)).over(window)))
            return F.when(F.size(union) > 0, union).alias(name)

        return F.first(meaningful(name), ignorenulls=True).over(window).alias(name)

    columns = [c for c in df.columns if c not in ("_key", "_priority")]
    merged = df.select(F.col("_key"), *[aggregate(c) for c in columns])
    return merged.dropDuplicates(["_key"]).drop("_key")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("partition", help="e.g. 2026-SUMMER")
    parser.add_argument("run_date", help="e.g. 2026-09-07")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    result = consolidate_partition(args.data_dir, args.partition, args.run_date)
    print(f"Wrote: {result}" if result else "Nothing to consolidate")
