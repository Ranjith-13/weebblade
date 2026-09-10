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


def test_collect_stats_handles_missing_warehouse_file(tmp_path):
    # Every source failed and consolidate/refresh_catalog never even created the
    # warehouse file - collect_stats should degrade gracefully, not raise.
    stats = collect_stats(tmp_path / "does-not-exist.duckdb")

    assert stats == {
        "current_season": [],
        "top_rated": [],
        "genre_counts": [],
        "format_counts": [],
        "season_summary": [],
    }


def test_collect_stats_handles_missing_view(tmp_path):
    # Warehouse file exists (refresh_catalog ran) but every source failed that run,
    # so anime_media/anime_media_latest were never created.
    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(tmp_path / "data", db_path)

    stats = collect_stats(db_path)

    assert stats["top_rated"] == []


def _season_rows(season, year, titles):
    """titles: (source_id, name, score, format)"""
    return [
        {
            "source": "kitsu",
            "source_id": sid,
            "title_english": name,
            "title_romaji": None,
            "score_100": score,
            "genres": ["Action"],
            "format": fmt,
            "season": season,
            "season_year": year,
            "run_date": "2026-09-10",
        }
        for sid, name, score, fmt in titles
    ]


def _warehouse(tmp_path, rows):
    data_dir = tmp_path / "data"
    _write_parquet(
        data_dir / "processed" / "anime_media_consolidated" / "_catalogue" / "2026-09-10" / "part-0.parquet",
        rows,
    )
    db_path = tmp_path / "warehouse.duckdb"
    refresh_catalog(data_dir, db_path)
    return db_path


def test_the_digest_stats_cover_only_the_newest_season(tmp_path):
    """anime_media_latest spans every season ever ingested - 475 titles across two
    of them live - while the prompt asks for a digest of "this season". Unscoped,
    the model was handed the whole catalogue and told it was one season, so an
    older season's title could be quoted as this season's best."""
    db_path = _warehouse(
        tmp_path,
        _season_rows("SPRING", 2026, [("1", "Spring Best", 99.0, "ONA")])
        + _season_rows("SUMMER", 2026, [("2", "Summer Best", 80.0, "TV")]),
    )

    stats = collect_stats(db_path)

    assert stats["current_season"] == [{"season": "SUMMER", "season_year": 2026}]
    assert [r["title_english"] for r in stats["top_rated"]] == ["Summer Best"]
    assert stats["format_counts"] == [{"format": "TV", "title_count": 1}]


def test_the_newest_season_uses_the_quarterly_order_not_the_alphabet(tmp_path):
    """Sorting season names as text puts WINTER first and FALL last, exactly
    backwards. It happened to give the right answer while Spring and Summer were
    the only seasons on record, and would have broken silently on the first Fall
    or Winter partition."""
    db_path = _warehouse(
        tmp_path,
        _season_rows("WINTER", 2026, [("1", "Winter", 50.0, "TV")])
        + _season_rows("SUMMER", 2026, [("2", "Summer", 60.0, "TV")])
        + _season_rows("FALL", 2026, [("3", "Fall", 70.0, "TV")]),
    )

    stats = collect_stats(db_path)

    assert stats["current_season"] == [{"season": "FALL", "season_year": 2026}]
    assert [r["title_english"] for r in stats["top_rated"]] == ["Fall"]
    assert [(r["season"], r["season_year"]) for r in stats["season_summary"]] == [
        ("FALL", 2026),
        ("SUMMER", 2026),
        ("WINTER", 2026),
    ]


def test_the_season_summary_still_spans_every_season(tmp_path):
    """The one section that is deliberately unscoped: a digest of a season reads
    better when the model can compare it against the ones before it."""
    db_path = _warehouse(
        tmp_path,
        _season_rows("SPRING", 2026, [("1", "A", 99.0, "TV")])
        + _season_rows("SUMMER", 2026, [("2", "B", 80.0, "TV")]),
    )

    summary = collect_stats(db_path)["season_summary"]

    assert [(r["season"], r["season_year"]) for r in summary] == [
        ("SUMMER", 2026),
        ("SPRING", 2026),
    ]


def test_titles_with_no_season_are_left_out_of_the_summary(tmp_path):
    """They would otherwise render as "None None: 1 titles" in the prompt, which
    tells the model nothing and invites it to invent a meaning."""
    rows = _season_rows("SUMMER", 2026, [("1", "Real", 80.0, "TV")])
    orphan = _season_rows("SUMMER", 2026, [("2", "Orphan", 40.0, "TV")])[0]
    orphan["season"] = None
    orphan["season_year"] = None

    summary = collect_stats(_warehouse(tmp_path, rows + [orphan]))["season_summary"]

    assert [(r["season"], r["season_year"]) for r in summary] == [("SUMMER", 2026)]
