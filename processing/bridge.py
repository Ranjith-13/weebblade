"""Which MAL id a row should carry, out of what AniList said.

Two questions, one rule. A row with no MAL id may be given one, and a row whose
MAL id cannot be right may have it corrected.

ingestion/anilist/bridge_ids.py records the MAL id AniList holds for each title
the catalogue has no MAL id for. Acting on every one of them would be wrong:
of the seventeen that named an id another title owns, six had to be refused, and
three of those because AniList's own cross-reference is stale - its entry for
Throne of Seal 3 carries the MAL id of Throne of Seal 2nd Season, which finished
two and a half years earlier, so adopting it would have merged a 2025 series
into a 2022 one and deleted a title.

The rule: the row and everything already carrying that MAL id must have
premiered within FILL_WINDOW_DAYS of each other, every date complete. It is
matching.py's fourth rule read across sources - a shared premiere is strong
evidence of one work.

The window started at zero, on matching.py's argument that one wide enough to
bridge a near-miss is wide enough to join a series to its compilation film. Then
it was measured over the sixteen candidates the ledger holds, and the argument
did not survive contact:

    exact day   11 adopted
    +/- 1 day   13
    +/- 3 days  14
    +/- 7 days  14
    +/- 14 days 14
    +/- 31 days 14

Flat from three days out. The feared join never appears, because the window is
not what decides whether two rows are one title - the strict title match that
accepted the AniList entry already did that, and this only asks whether the id
is already spoken for by something that disagrees. Three days buys the two
Jujutsu Kaisen Modulo PVs, the two Santa Tell Me entries, and Changsheng Jie
beside World of Immortals - the same show under its Chinese and English names.
Widening further buys nothing at all, which is the best argument for stopping
there.

"Everything already carrying it", not just MAL's own row, because an id can
already be on rows that disagree - and then it names a group that is wrong
before this ever touches it. Kitsu maps Yao Shen Ji 6 (23 April 2022) to the MAL
id of Yao Shen Ji 7 (14 January 2023), so those two are one catalogue title
today, wrongly. The Kitsu row for season 7 premieres on MAL's exact day and
would be let in by a rule that only looked at MAL - joining a correct title to
an incorrect group. Refused instead, which leaves the existing bad merge
visible as its own problem rather than growing it.

Nothing is adopted where no row carries the id either. Then there is no merge to
verify, and an unverifiable id on a row is one that may merge something later
for no reason anyone can check.

CORRECTING A MAPPING

Kitsu maps its row for Yao Shen Ji 6 to the MAL id of Yao Shen Ji 7th Season, so
the catalogue held two different seasons as one title. Nothing in the pipeline
could see it: a MAL id is the first and most trusted rule, and a wrong one is
indistinguishable from a right one.

A date alone cannot find these. Of 4,654 rows carrying a MAL id that MAL's own
row can be compared with, 4,075 premiere on the same day and 482 within a week -
sources arguing about a date. Beyond that the gap stops being an argument: 53
are more than a month apart, and among the 15 that are also months apart AND
share no name with MAL's row, most are one work under a punctuation or
transliteration variant (Gwangjang against Gwang-jang, Journey against Journey
(2022)), or one source has the year wrong - 26 pairs sit at exactly 365 days.
Distrusting a mapping on the gap would have broken those.

So the gap only selects who to ask about. AniList answers, and of those 15 it
agreed with the mapping for 8, had no entry matching strictly for 4, and named a
different id for 2. A named id is used only when MAL's own row for it premiered
on the row's exact day: true for Yao Shen Ji 6 (both 23 April 2022), and not
checkable for Fei Ren Zai 2 Part 2, whose proposed id MAL has never been fetched
for - so that one is left alone rather than guessed at.

Corrections are computed before fills, because they change the answer: with
Kitsu's row for season 6 no longer carrying season 7's id, season 7's id is left
naming one row, and Kitsu's own row for season 7 can then be given it.

Plain Python and DuckDB over a few hundred rows, like identity.py: the logic is
branchy, and this way it is testable on any machine rather than only on one with
a JVM. consolidate.py reads the file it writes.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

OUT_NAME = Path("bridge") / "mal_ids.parquet"

# How far apart two premieres must be before a mapping is worth questioning. A
# season is thirteen weeks: inside that the sources are arguing about a date,
# beyond it they are describing different works. Nothing is decided on this - it
# only chooses which rows AniList is asked about.
SUSPECT_DAYS = 92

# How far apart the premieres may be before an id is treated as spoken for by
# something else. Three, because that is where the measurement above goes flat:
# every real pair is inside it and nothing new appears outside it. Correcting a
# mapping stays exact-day - see the replacement rule below - because that
# overrules a source rather than filling a gap it left.
FILL_WINDOW_DAYS = 3

# The newest thing each ledger says about a row, and only the rows AniList gave
# an id for.
_LEDGER = """
    SELECT source_key, mal_id FROM read_parquet({files})
    WHERE mal_id IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY source_key ORDER BY searched_on DESC) = 1
"""

# Every source's current row per id: the newest snapshot it appears in, which is
# the same rule consolidate._current_state applies before merging. `premiered` is
# null unless the whole date is known; CAST because make_date takes INTEGER and
# these columns are BIGINT from Parquet.
_CURRENT = """
    SELECT source || ':' || source_id AS source_key, source, source_id, mal_id,
           title_romaji, title_english, format, season_year,
           start_year, start_month, start_day,
           make_date(CAST(start_year AS INTEGER), CAST(start_month AS INTEGER),
                     CAST(start_day AS INTEGER)) AS premiered
    FROM (
        SELECT *, regexp_extract(filename, '([0-9-]+)\\.parquet$', 1) AS _snapshot
        FROM read_parquet('{glob}', filename=true, union_by_name=true)
    ) QUALIFY ROW_NUMBER() OVER (PARTITION BY source, source_id ORDER BY _snapshot DESC) = 1
"""

# A mapping worth questioning: months away from the row MAL keeps under that id,
# and sharing none of its names. Neither alone is enough - the sources argue
# about dates constantly, and 26 pairs sit at exactly 365 days under one name,
# which is a wrong year and a right mapping. COALESCE around each comparison
# because a null title must not make the whole test null and quietly excuse the
# row from being asked about.
_DOUBTFUL = """
    SELECT r.source_key, r.mal_id, r.title_romaji, r.title_english, r.format, r.season_year,
           r.start_year, r.start_month, r.start_day
    FROM current r JOIN current m ON m.source = 'mal' AND m.source_id = CAST(r.mal_id AS VARCHAR)
    WHERE r.source <> 'mal' AND r.mal_id IS NOT NULL
      AND r.premiered IS NOT NULL AND m.premiered IS NOT NULL
      AND abs(datediff('day', r.premiered, m.premiered)) > {days}
      AND NOT (COALESCE(lower(trim(r.title_romaji)) = lower(trim(m.title_romaji)), false)
            OR COALESCE(lower(trim(r.title_romaji)) = lower(trim(m.title_english)), false)
            OR COALESCE(lower(trim(r.title_english)) = lower(trim(m.title_romaji)), false)
            OR COALESCE(lower(trim(r.title_english)) = lower(trim(m.title_english)), false))
"""

# What every row carrying a MAL id says about when it began. One day, or the id
# names rows that disagree and is no use for deciding anything. A partial date
# says nothing either way and is left out.
_CARRIERS = """
    SELECT mal_id, MIN(premiered) AS first_day, MAX(premiered) AS last_day
    FROM {rows} WHERE mal_id IS NOT NULL AND premiered IS NOT NULL GROUP BY mal_id
"""

# Corrections first, then fills over the corrected rows: with Kitsu's row for
# Yao Shen Ji 6 no longer carrying season 7's id, that id is left naming one row,
# and Kitsu's own row for season 7 can be given it in the same pass.
_DECIDE = """
    WITH ledger AS ({ledger}), current AS ({current}), doubtful AS ({doubtful}),
    carriers AS ({carriers_now}),
    replacement AS (
        SELECT d.source_key, l.mal_id
        FROM doubtful d
        JOIN ledger l ON l.source_key = d.source_key
        JOIN current r ON r.source_key = d.source_key
        JOIN carriers c ON c.mal_id = l.mal_id
        WHERE l.mal_id IS DISTINCT FROM d.mal_id
          AND r.premiered IS NOT NULL AND c.first_day = c.last_day AND c.first_day = r.premiered
    ),
    corrected AS (
        SELECT c.* EXCLUDE (mal_id), COALESCE(r.mal_id, c.mal_id) AS mal_id
        FROM current c LEFT JOIN replacement r ON r.source_key = c.source_key
    ),
    settled AS ({carriers_settled}),
    fill AS (
        SELECT l.source_key, l.mal_id
        FROM ledger l
        JOIN corrected k ON k.source_key = l.source_key
        JOIN settled c ON c.mal_id = l.mal_id
        WHERE k.mal_id IS NULL
          AND k.premiered IS NOT NULL
          AND c.first_day = c.last_day
          AND abs(datediff('day', c.first_day, k.premiered)) <= {window}
    )
    SELECT source_key, mal_id, 'fill' AS action FROM fill
    UNION ALL SELECT source_key, mal_id, 'replace' AS action FROM replacement
    ORDER BY source_key
"""


def _parts(data_dir: Path) -> dict[str, str]:
    files = sorted((data_dir / "processed" / "anilist_bridge").glob("*.parquet"))
    return {
        "ledger": _LEDGER.format(files=[str(p) for p in files]),
        "current": _CURRENT.format(glob=data_dir / "processed" / "*_media" / "*" / "*.parquet"),
        "doubtful": _DOUBTFUL.format(days=SUSPECT_DAYS),
        "carriers_now": _CARRIERS.format(rows="current"),
        "carriers_settled": _CARRIERS.format(rows="corrected"),
        "window": FILL_WINDOW_DAYS,
    }


def doubtful_mappings(data_dir: Path) -> list[dict]:
    """The rows whose MAL id is worth asking AniList about. Shaped for
    matching.keys(), which is what decides whether an answer is this row."""
    parts = _parts(data_dir)
    con = duckdb.connect()
    try:
        return con.execute(
            f"WITH current AS ({parts['current']}) SELECT * FROM ({parts['doubtful']}) "
            "ORDER BY source_key"
        ).fetch_arrow_table().to_pylist()
    except duckdb.IOException:  # no source snapshots yet
        return []
    finally:
        con.close()


def build_bridge(data_dir: Path) -> Path | None:
    """Write which MAL id each row should carry, and return the file.

    None when there is nothing to say - no ledger yet, or nothing in it that
    survives the rule - and then the file is removed, so a stale mapping cannot
    go on merging titles after the evidence for it is gone.
    """
    files = sorted((data_dir / "processed" / "anilist_bridge").glob("*.parquet"))
    out = data_dir / "processed" / OUT_NAME
    if not files:
        logger.info("No AniList bridge ledger yet - no MAL ids to decide")
        _remove(out)
        return None

    con = duckdb.connect()
    try:
        rows = con.execute(_DECIDE.format(**_parts(data_dir))).fetch_arrow_table()
    except duckdb.IOException:  # no source snapshots to check a premiere against
        logger.warning("No source snapshots to check a premiere against - no MAL ids to decide")
        _remove(out)
        return None
    finally:
        con.close()

    if not rows.num_rows:
        logger.info("Nothing in the AniList bridge ledger survives the premiere check")
        _remove(out)
        return None

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    pq.write_table(rows, tmp)
    tmp.replace(out)
    actions = rows.column("action").to_pylist()
    logger.info(
        "MAL ids: %s row(s) given one that had none, %s corrected",
        actions.count("fill"), actions.count("replace"),
    )
    return out


def _remove(out: Path) -> None:
    if out.exists():
        out.unlink()
