from __future__ import annotations

import logging
import os
from pathlib import Path

from .collect import collect_stats
from .prompt import build_prompt

logger = logging.getLogger(__name__)


def generate_digest(
    db_path: Path, out_dir: Path, run_date: str, dry_run: bool = False
) -> Path | None:
    """Collect stats from the warehouse, build a prompt, and get an LLM digest.

    Never hard-fails on a missing API key or empty data - both are expected states
    early in the project's life (before GROQ_API_KEY is configured, or before any
    source has landed data yet), so this writes a placeholder explaining why instead
    of crashing the task.
    """
    stats = collect_stats(db_path)
    if not stats["top_rated"]:
        logger.warning("No data available yet in the warehouse - skipping digest generation")
        return None

    prompt = build_prompt(stats)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_date}.md"

    if dry_run or not os.environ.get("GROQ_API_KEY"):
        reason = "dry run requested" if dry_run else "GROQ_API_KEY not set"
        text = (
            f"[Digest not generated: {reason}]\n\n"
            f"--- Prompt that would have been sent to the LLM ---\n\n{prompt}"
        )
    else:
        from .client import GroqClient

        text = GroqClient().complete(prompt)

    out_path.write_text(text, encoding="utf-8")
    logger.info("Wrote digest to %s", out_path)
    return out_path


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("run_date", help="e.g. 2026-09-07")
    parser.add_argument("--db-path", type=Path, default=Path("data/warehouse.duckdb"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/digests"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = generate_digest(args.db_path, args.out_dir, args.run_date, dry_run=args.dry_run)
    print(f"Wrote: {result}" if result else "Nothing to generate (no data yet)")
