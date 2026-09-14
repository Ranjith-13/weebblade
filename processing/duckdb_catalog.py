from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# Each view is a glob over that source's dated Parquet snapshots. Anything that opens
# the resulting DuckDB file (the backend, a notebook, the future digest script) just
# queries these as normal tables without needing to know the on-disk layout.
_VIEWS = {
    "anime_media": "processed/anime_media_consolidated/*/*/*.parquet",
    "anime_media_anilist": "processed/anilist_media/*/*.parquet",
    "anime_media_jikan": "processed/jikan_media/*/*.parquet",
    "anime_media_kitsu": "processed/kitsu_media/*/*.parquet",
    "anime_media_mal": "processed/mal_media/*/*.parquet",
}


def refresh_catalog(data_dir: Path, db_path: Path) -> list[str]:
    """(Re)create views over the Parquet lake. Returns the view names that were
    actually (re)created - a source/partition with no files yet is skipped with a
    warning rather than failing the whole refresh, since this runs even when some
    upstream sources are down.
    """
    con = duckdb.connect(str(db_path))
    created = []
    try:
        for view_name, glob_suffix in _VIEWS.items():
            glob_path = str(data_dir / glob_suffix)
            try:
                con.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT * FROM read_parquet('{glob_path}', union_by_name=true)"
                )
                created.append(view_name)
                logger.info("Refreshed view %s -> %s", view_name, glob_path)
            except duckdb.IOException:
                logger.warning("No files yet for view %s (%s), skipping", view_name, glob_path)

        has_registry = _identity_views(con, data_dir)
        if has_registry:
            created += ["anime_identity", "anime_alias"]

        if "anime_media" in created:
            con.execute(_latest_view_sql(con, has_registry))
            created.append("anime_media_latest")
            logger.info(
                "Refreshed view anime_media_latest (latest run per %s)",
                "identity" if has_registry else "source row",
            )

        created += _franchise_views(con, data_dir)
        created += _airing_view(con, data_dir, has_registry)
        created += _anilist_status_view(con, data_dir, has_registry)
    finally:
        con.close()
    return created


def _franchise_views(con: duckdb.DuckDBPyConnection, data_dir: Path) -> list[str]:
    """Related titles and franchises, where they have been built. See
    ingestion/mal/fetch_relations.py and processing/franchise.py.

    `anime_relation` is each title's current list of related titles: its most
    recent fetch, the edges only. `franchise_member` is the built table as is.
    """
    created = []
    relations = data_dir / "processed" / "mal_relations"
    if list(relations.glob("*/*.parquet")):
        con.execute(
            "CREATE OR REPLACE VIEW anime_relation AS "
            "SELECT * EXCLUDE (_latest) FROM ("
            "  SELECT *, MAX(fetched_on) OVER (PARTITION BY mal_id) AS _latest"
            f"  FROM read_parquet('{relations}/*/*.parquet', union_by_name=true)"
            ") WHERE fetched_on = _latest AND related_mal_id IS NOT NULL"
        )
        created.append("anime_relation")
    else:
        logger.warning("No related titles fetched yet (%s), skipping anime_relation", relations)

    members = data_dir / "processed" / "franchise" / "members.parquet"
    if members.exists():
        con.execute(f"CREATE OR REPLACE VIEW franchise_member AS SELECT * FROM read_parquet('{members}')")
        created.append("franchise_member")
    else:
        logger.warning("No franchises built yet (%s), skipping franchise_member", members)
    return created


def _newest_placed(
    con: duckdb.DuckDBPyConnection, view: str, directory: Path, has_registry: bool
) -> list[str]:
    """A view over the newest of a directory's dated files, each row placed on
    the title it belongs to: by AniList id, then MAL id.

    The newest file is chosen when the view is READ, not when it is made: the
    glob is evaluated per query. These are fetched daily and the views are made
    weekly, and neither has to wait for the other - a new day's file is served
    the moment it lands, with nothing opening the warehouse to write.

    AniList id first, then MAL id: 13 of the 102 catalogue titles airing in the
    week first measured were missing from AniList's season listing, so only
    the MAL id placed them. A row neither places has a null wb_id and is still
    served - One Piece is on the schedule whether or not the catalogue holds it.
    """
    if not list(directory.glob("*.parquet")):
        logger.warning("Nothing fetched yet for %s (%s), skipping it", view, directory)
        return []

    files = f"read_parquet('{directory}/*.parquet', union_by_name=true)"
    latest = f"SELECT * FROM {files} WHERE fetched_on = (SELECT MAX(fetched_on) FROM {files})"
    if has_registry:
        sql = (
            f"SELECT l.*, COALESCE(a.wb_id, m.wb_id) AS wb_id FROM ({latest}) l "
            "LEFT JOIN anime_identity a ON a.source_key = 'anilist:' || CAST(l.anilist_id AS VARCHAR) "
            "LEFT JOIN anime_identity m ON m.source_key = 'mal:' || CAST(l.mal_id AS VARCHAR)"
        )
    else:
        sql = f"SELECT *, CAST(NULL AS VARCHAR) AS wb_id FROM ({latest})"
    con.execute(f"CREATE OR REPLACE VIEW {view} AS {sql}")
    return [view]


def _airing_view(con: duckdb.DuckDBPyConnection, data_dir: Path, has_registry: bool) -> list[str]:
    """AniList's airing schedule. See ingestion/anilist/fetch_airing.py."""
    return _newest_placed(con, "anime_airing", data_dir / "processed" / "anilist_airing", has_registry)


def _anilist_status_view(con: duckdb.DuckDBPyConnection, data_dir: Path, has_registry: bool) -> list[str]:
    """AniList's own status for the titles the catalogue calls airing. See
    ingestion/anilist/fetch_status.py."""
    return _newest_placed(
        con, "anime_anilist_status", data_dir / "processed" / "anilist_status", has_registry
    )


def _identity_views(con: duckdb.DuckDBPyConnection, data_dir: Path) -> bool:
    """Expose the identity registry, if one exists yet. See processing/identity.py.

    `anime_identity` maps every source key ever seen to the title it belongs to;
    `anime_alias` maps retired identities to the one that absorbed them. The
    registry keeps both flattened - every key points at a live identity and every
    alias at its final target - so each resolves in a single join.
    """
    registry = data_dir / "identity" / "registry.parquet"
    if not registry.exists():
        logger.warning("No identity registry at %s yet - titles keyed by source row", registry)
        return False

    path = str(registry)
    con.execute(
        "CREATE OR REPLACE VIEW anime_identity AS "
        f"SELECT key AS source_key, wb_id FROM read_parquet('{path}') WHERE kind = 'key'"
    )
    con.execute(
        "CREATE OR REPLACE VIEW anime_alias AS "
        f"SELECT key AS alias, wb_id FROM read_parquet('{path}') WHERE kind = 'alias'"
    )
    return True


def _latest_view_sql(con: duckdb.DuckDBPyConnection, has_registry: bool) -> str:
    """The newest row per TITLE, where title means its stable identity.

    anime_media keeps one row per title per run, which is right for history, but
    everything that renders the catalogue wants one row per title. It used to
    partition by (source, source_id). That is the address that moves: when the
    merge picks a different winner between two runs - a new pass, a source coming
    back online and outranking another - the same title arrives under two keys
    and survives twice, a duplicate made by nothing but a change of winner.

    Partitioning by identity closes that. It has to cope with every row the lake
    already holds, most of which predate identities entirely, so each row's
    identity is resolved in order of authority:

      1. the registry's current answer for the row's own source key, which is
         authoritative and already follows merges;
      2. the identity stamped on the row, run through the aliases, for a row
         whose key the registry no longer lists under that identity;
      3. the stamped identity as written;
      4. the source key itself, for a row nothing knows about - which is exactly
         the old behaviour, so a lake with no registry yet is unaffected.

    Casts are explicit because DuckDB types a column that is NULL in every row of
    a file as INTEGER, and 1.1.3 (the version CI pins) refuses to COALESCE it with
    VARCHAR; that has turned a sort into a 500 in this project once already.
    """
    columns = {row[0] for row in con.execute("DESCRIBE anime_media").fetchall()}
    stamped = "wb_id" in columns
    own_key = "CAST(m.source AS VARCHAR) || ':' || CAST(m.source_id AS VARCHAR)"

    candidates, joins = [], []
    if has_registry:
        candidates.append("CAST(k.wb_id AS VARCHAR)")
        joins.append(f"LEFT JOIN anime_identity k ON k.source_key = {own_key}")
    if stamped:
        if has_registry:
            candidates.append("CAST(al.wb_id AS VARCHAR)")
            joins.append("LEFT JOIN anime_alias al ON al.alias = CAST(m.wb_id AS VARCHAR)")
        candidates.append("CAST(m.wb_id AS VARCHAR)")

    if not candidates:
        # No identities anywhere yet: exactly the old view.
        return (
            "CREATE OR REPLACE VIEW anime_media_latest AS "
            "SELECT * EXCLUDE (_rn) FROM ("
            "  SELECT *, ROW_NUMBER() OVER ("
            "    PARTITION BY source, source_id ORDER BY run_date DESC"
            "  ) AS _rn FROM anime_media"
            ") WHERE _rn = 1"
        )

    base = "m.* EXCLUDE (wb_id)" if stamped else "m.*"
    resolved = (
        f"SELECT {base}, COALESCE({', '.join(candidates)}) AS wb_id "
        f"FROM anime_media m {' '.join(joins)}"
    )
    return (
        "CREATE OR REPLACE VIEW anime_media_latest AS "
        "SELECT * EXCLUDE (_rn) FROM ("
        "  SELECT *, ROW_NUMBER() OVER ("
        "    PARTITION BY COALESCE(wb_id, CAST(source AS VARCHAR) || ':' || CAST(source_id AS VARCHAR))"
        "    ORDER BY run_date DESC"
        f"  ) AS _rn FROM ({resolved})"
        ") WHERE _rn = 1"
    )


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()

    db_path = args.db_path or args.data_dir / "warehouse.duckdb"
    views = refresh_catalog(args.data_dir, db_path)
    print(f"Refreshed {len(views)} view(s) at {db_path}: {views}")
