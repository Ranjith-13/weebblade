from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ai.digest.collect import collect_stats
from processing.duckdb_catalog import refresh_catalog


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_collect_stats_reads_from_consolidated_view(tmp_path):
    data_dir = tmp_path / "data"
    _write_parquet(
        data_dir / "processed" / "anime_media_consolidated" / "2026-SUMMER" / "2026-09-07" / "part-0.parquet",
        [
            {
                "source": "kitsu",
                "source_id": "1",
                "title_english": "Demon Slayer",
                "title_romaji": None,
                "score_100": 84.0,
                "genres": ["Action", "Fantasy"],
                "format": "TV",
                "season": "SUMMER",
                "season_year": 2026,
                "run_date": "2026-09-07",
            },
            {
                "source": "kitsu",
                "source_id": "2",
                "title_english": "Frieren",
                "title_romaji": None,
                "score_100": 90.0,
                "genres": ["Fantasy", "Drama"],
                "format": "TV",
                "season": "SUMMER",
                "season_year": 2026,
                "run_date": "2026-09-07",
            },
        ],
    )

    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(data_dir, db_path)

    stats = collect_stats(db_path)

    assert stats["top_rated"][0]["title_english"] == "Frieren"
    assert {row["genre"] for row in stats["genre_counts"]} == {"Action", "Fantasy", "Drama"}
    assert stats["format_counts"] == [{"format": "TV", "title_count": 2}]
    assert stats["season_summary"][0]["title_count"] == 2
