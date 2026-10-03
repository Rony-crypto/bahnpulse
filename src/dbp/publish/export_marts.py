"""Export small dashboard marts from the local dbt DuckDB database.

Usage:
    uv run python -m dbp.publish.export_marts
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from dbp.config import DATA, RAW_S1, ROOT

DEFAULT_DATABASE = DATA / "bahnpulse.duckdb"
DATABASE = (
    Path(os.environ["BAHNPULSE_DUCKDB_PATH"])
    if os.getenv("BAHNPULSE_DUCKDB_PATH")
    else DEFAULT_DATABASE
)
PUBLISHED = DATA / "published"
DBT_RUN_RESULTS = ROOT / "dbt" / "target" / "run_results.json"
MART_NAMES = (
    "agg_state_month_type",
    "agg_station_month_type",
    "agg_hamburg_weekly",
    "agg_state_hour_weekday",
    "agg_month_coverage",
    "agg_delay_sources",
    "agg_station_delay_gain",
    "agg_delay_along_route",
)


def dbt_run_summary(run_results: Path) -> dict | None:
    """Tests passed/failed and models built in the latest dbt run, for the app footer."""
    if not run_results.exists():
        return None
    results = json.loads(run_results.read_text(encoding="utf-8"))
    tests = [r for r in results["results"] if r["unique_id"].startswith("test.")]
    models = [r for r in results["results"] if not r["unique_id"].startswith("test.")]
    return {
        "run_at": results["metadata"]["generated_at"],
        "tests_passed": sum(r["status"] == "pass" for r in tests),
        "tests_failed": sum(r["status"] in ("fail", "error") for r in tests),
        "tests_warned": sum(r["status"] == "warn" for r in tests),
        "models_built": sum(r["status"] == "success" for r in models),
    }


def export_marts(
    database: Path = DATABASE,
    published: Path = PUBLISHED,
    s1_directory: Path = RAW_S1,
    run_results: Path = DBT_RUN_RESULTS,
) -> dict:
    """Write configured aggregate marts as compressed Parquet and return run metadata."""
    if not database.exists():
        raise FileNotFoundError(f"dbt DuckDB database not found: {database}")

    mart_dir = published / "marts"
    mart_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(database), read_only=True)
    try:
        row_counts = {}
        for name in MART_NAMES:
            relation = con.table(f"marts.{name}")
            relation.write_parquet(str(mart_dir / f"{name}.parquet"), compression="zstd")
            row_counts[name] = relation.count("*").fetchone()[0]
        history = con.sql(
            "SELECT min(service_month), max(service_month) FROM marts.agg_state_month_type"
        ).fetchone()
    finally:
        con.close()

    source_months = sorted(
        path.stem.removeprefix("data-") for path in s1_directory.glob("data-*.parquet")
    )
    status = {
        "built_at": datetime.now(UTC).isoformat(),
        "event_month_start": history[0].isoformat() if history[0] else None,
        "event_month_end": history[1].isoformat() if history[1] else None,
        "source_month_start": source_months[0] if source_months else None,
        "source_month_end": source_months[-1] if source_months else None,
        "row_counts": row_counts,
        "dbt": dbt_run_summary(run_results),
    }
    published.mkdir(parents=True, exist_ok=True)
    (published / "run_status.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    return status


def main() -> None:
    status = export_marts()
    print(
        f"Exported {len(status['row_counts'])} marts; "
        f"source files {status['source_month_start']} to {status['source_month_end']} "
        f"-> {PUBLISHED}"
    )


if __name__ == "__main__":
    main()