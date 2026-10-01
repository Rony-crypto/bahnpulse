"""Week 1 profiling of the downloaded S1 files with DuckDB.

Usage:
    uv run python -m dbp.profile.profile_s1

Writes docs/sources/s1_profile.md: schema, row counts per month, train types, Hamburg S-Bahn
lines, null rates, duplicate candidate keys and hours without data. Use the report to fill in
docs/sources/s1.md and to design the staging model.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from dbp.config import DOCS, RAW_S1

REPORT = DOCS / "sources" / "s1_profile.md"


def md_table(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    rel = con.sql(sql)
    cols = rel.columns
    rows = rel.fetchall()
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def build_report(files_glob: str) -> str:
    con = duckdb.connect()
    con.sql(
        "CREATE VIEW s1 AS SELECT * EXCLUDE (filename), filename AS _file "
        f"FROM read_parquet('{files_glob}', filename=true)"
    )
    cols = [r[0] for r in con.sql("DESCRIBE s1").fetchall()]

    def has(*names: str) -> bool:
        return all(n in cols for n in names)

    out = ["# S1 profile (generated)", "", "## Schema", "", md_table(con, "DESCRIBE s1")]

    out += [
        "",
        "## Rows per file",
        "",
        md_table(
            con,
            """
        SELECT regexp_extract(_file, 'data-(\\d{4}-\\d{2})', 1) AS month, count(*) AS rows
        FROM s1 GROUP BY 1 ORDER BY 1""",
        ),
    ]

    if has("train_type"):
        out += [
            "",
            "## Train types",
            "",
            md_table(
                con,
                """
            SELECT train_type, count(*) AS rows,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
            FROM s1 GROUP BY 1 ORDER BY rows DESC LIMIT 30""",
            ),
        ]

    if has("station_name", "train_type", "line_number"):
        out += [
            "",
            "## Hamburg S-Bahn lines",
            "",
            md_table(
                con,
                """
            SELECT line_number, count(*) AS stops, count(DISTINCT station_name) AS stations
            FROM s1 WHERE station_name LIKE 'Hamburg%' AND train_type = 'S'
            GROUP BY 1 ORDER BY stops DESC""",
            ),
        ]

    null_exprs = ", ".join(
        f'round(100.0 * count(*) FILTER (WHERE "{c}" IS NULL) / count(*), 2) AS "{c}"'
        for c in cols
        if c != "_file"
    )
    out += ["", "## Null rate per column (%)", "", md_table(con, f"SELECT {null_exprs} FROM s1")]

    if has("eva", "train_number", "arrival_planned_time", "departure_planned_time"):
        out += [
            "",
            "## Duplicate candidate key (eva, train_number, planned time)",
            "",
            md_table(
                con,
                """
            SELECT count(*) AS rows,
                   count(DISTINCT (eva, train_number,
                         coalesce(arrival_planned_time, departure_planned_time))) AS distinct_keys,
                   count(*) - count(DISTINCT (eva, train_number,
                         coalesce(arrival_planned_time, departure_planned_time))) AS duplicates
            FROM s1""",
            ),
        ]

    if has("arrival_planned_time", "departure_planned_time"):
        out += [
            "",
            "## Hours without any planned stop (possible collection gaps)",
            "",
            md_table(
                con,
                """
            WITH hours AS (
                SELECT DISTINCT date_trunc(
                    'hour',
                    CAST(coalesce(arrival_planned_time, departure_planned_time) AS TIMESTAMP)
                ) AS h
                FROM s1),
            bounds AS (SELECT min(h) AS lo, max(h) AS hi FROM hours),
            expected AS (
                SELECT unnest(generate_series(lo, hi, INTERVAL 1 HOUR)) AS h FROM bounds)
            SELECT strftime(e.h, '%Y-%m') AS month, count(*) AS missing_hours
            FROM expected e LEFT JOIN hours USING (h)
            WHERE hours.h IS NULL GROUP BY 1 ORDER BY 1""",
            ),
        ]

    missing = [
        n for n in ("train_type", "line_number", "eva", "arrival_planned_time") if n not in cols
    ]
    if missing:
        out += [
            "",
            f"> Note: expected columns not found: {', '.join(missing)}. "
            "Adjust the queries to the real names.",
        ]
    return "\n".join(out) + "\n"


def main() -> None:
    files = sorted(Path(RAW_S1).glob("data-*.parquet"))
    if not files:
        raise SystemExit("No files in data/raw/s1. Run dbp.ingest.download_s1 first.")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(str(RAW_S1 / "data-*.parquet")), encoding="utf-8")
    print(f"Profiled {len(files)} file(s) -> {REPORT}")


if __name__ == "__main__":
    main()
