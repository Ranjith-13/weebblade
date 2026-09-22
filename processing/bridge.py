"""Which Kitsu-only rows should carry a MAL id, out of what AniList said.

ingestion/anilist/bridge_ids.py records the MAL id AniList holds for each title
the catalogue has no MAL id for. Acting on every one of them would be wrong:
of the seventeen that named an id another title owns, six had to be refused, and
three of those because AniList's own cross-reference is stale - its entry for
Throne of Seal 3 carries the MAL id of Throne of Seal 2nd Season, which finished
two and a half years earlier, so adopting it would have merged a 2025 series
into a 2022 one and deleted a title.

The rule, and the only one: the two rows must have premiered on the same day,
both dates complete. It is matching.py's fourth rule read across sources - an
identical premiere date is strong evidence of one work - and it is exactly what
separated the eleven real pairs from the six refusals when measured. A window of
a day or two would have caught three more likely pairs (Santa Tell Me, the
Jujutsu Kaisen Modulo PVs, Changsheng Jie), and matching.py already explains why
it stays shut: a window wide enough to bridge them is wide enough to join a
series to its compilation film.

Nothing is adopted where MAL has no row for the id either. Then there is no
merge to verify, and an unverifiable id on a row is one that may merge something
later for no reason anyone can check.

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

# The newest thing each ledger says about a row, and only the rows AniList gave
# an id for.
_LEDGER = """
    SELECT source_key, mal_id FROM read_parquet({files})
    WHERE mal_id IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY source_key ORDER BY searched_on DESC) = 1
"""

# Every source's current row per id: the newest snapshot it appears in, which is
# the same rule consolidate._current_state applies before merging.
_CURRENT = """
    SELECT source, source_id, start_year, start_month, start_day FROM (
        SELECT source, source_id, start_year, start_month, start_day,
               regexp_extract(filename, '([0-9-]+)\\.parquet$', 1) AS _snapshot
        FROM read_parquet('{glob}', filename=true, union_by_name=true)
    ) QUALIFY ROW_NUMBER() OVER (PARTITION BY source, source_id ORDER BY _snapshot DESC) = 1
"""


def build_bridge(data_dir: Path) -> Path | None:
    """Write the source keys that should be given a MAL id, and return the file.

    None when there is nothing to say - no ledger yet, or nothing in it that
    survives the rule - and then the file is removed, so a stale mapping cannot
    go on merging titles after the evidence for it is gone.
    """
    files = sorted((data_dir / "processed" / "anilist_bridge").glob("*.parquet"))
    out = data_dir / "processed" / OUT_NAME
    if not files:
        logger.info("No AniList bridge ledger yet - no MAL ids to adopt")
        _remove(out)
        return None

    con = duckdb.connect()
    try:
        ledger = _LEDGER.format(files=[str(p) for p in files])
        current = _CURRENT.format(glob=data_dir / "processed" / "*_media" / "*" / "*.parquet")
        rows = con.execute(
            f"WITH ledger AS ({ledger}), current AS ({current}) "
            "SELECT l.source_key, l.mal_id FROM ledger l "
            "JOIN current k ON k.source || ':' || k.source_id = l.source_key "
            "JOIN current m ON m.source = 'mal' AND m.source_id = CAST(l.mal_id AS VARCHAR) "
            "WHERE k.start_year IS NOT NULL AND k.start_month IS NOT NULL AND k.start_day IS NOT NULL "
            "  AND k.start_year = m.start_year AND k.start_month = m.start_month "
            "  AND k.start_day = m.start_day "
            "ORDER BY l.source_key"
        ).fetch_arrow_table()
    except duckdb.IOException:  # no source snapshots at all
        logger.warning("No source snapshots to check a premiere against - no MAL ids to adopt")
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
    logger.info("Adopting a MAL id for %s row(s) that had none", rows.num_rows)
    return out


def _remove(out: Path) -> None:
    if out.exists():
        out.unlink()
