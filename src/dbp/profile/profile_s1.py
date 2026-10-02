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
TRAIN_TYPE_MAP = (
    Path(__file__).resolve().parents[3] / "dbt" / "seeds" / "train_type_map.csv"
)
STATION_STATE_MAP = (
    Path(__file__).resolve().parents[3] / "data" / "raw" / "s3" / "station_state_map.csv"
)


def md_table(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    rel = con.sql(sql)
    cols = rel.columns
    rows = rel.fetchall()
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def build_report(files_glob: str, station_state_file: Path | None = None) -> str:
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
            "## Train type groups",
            "",
            md_table(
                con,
                f"""
            SELECT coalesce(m.train_group, 'Other') AS train_group,
                   count(*) AS rows,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
            FROM s1
            LEFT JOIN read_csv_auto('{TRAIN_TYPE_MAP}') m
              ON nullif(trim(s1.train_type), '') = m.train_type
            GROUP BY 1 ORDER BY rows DESC""",
            ),
        ]
        out += [
            "",
            "## Train type codes",
            "",
            md_table(
                con,
                f"""
            SELECT coalesce(nullif(trim(s1.train_type), ''), '(blank)') AS train_type,
                   coalesce(m.train_group, 'Other') AS train_group,
                   count(*) AS rows
            FROM s1
            LEFT JOIN read_csv_auto('{TRAIN_TYPE_MAP}') m
              ON nullif(trim(s1.train_type), '') = m.train_type
            GROUP BY 1, 2 ORDER BY rows DESC LIMIT 40""",
            ),
        ]
        out += [
            "",
            (
                "Bus rows are excluded from rail punctuality. "
                "Blank train types should be flagged as junk;"
            ),
            "unmapped nonblank codes currently fall back to Other.",
        ]

    if has("station_name", "train_type", "line_number"):
        state_file = station_state_file or STATION_STATE_MAP
        out += ["", "## Hamburg S-Bahn lines", ""]
        if state_file.exists():
            out += [
                md_table(
                    con,
                    f"""
                SELECT line_number, count(*) AS stops,
                       count(DISTINCT CASE
                           WHEN length(CAST(s1.eva AS VARCHAR)) = 8
                                AND starts_with(CAST(s1.eva AS VARCHAR), '08')
                           THEN substring(CAST(s1.eva AS VARCHAR), 2)
                           ELSE CAST(s1.eva AS VARCHAR)
                       END) AS stations
                FROM s1
                JOIN read_csv_auto('{state_file}') states
                   ON CASE
                        WHEN length(CAST(s1.eva AS VARCHAR)) = 8
                            AND starts_with(CAST(s1.eva AS VARCHAR), '08')
                        THEN substring(CAST(s1.eva AS VARCHAR), 2)
                        ELSE CAST(s1.eva AS VARCHAR)
                     END = CAST(states.eva AS VARCHAR)
                WHERE states.federal_state = 'Hamburg'
                  AND s1.train_type = 'S'
                  AND s1.line_number <> 'S0'
                GROUP BY 1 ORDER BY stops DESC""",
                ),
                "",
                "S0 is excluded as an anomalous 10-stop line.",
            ]
        else:
            out += [
                "State-based counts are pending `data/raw/s3/station_state_map.csv` "
                "(columns: eva, federal_state) from DB StaDa station data."
            ]

    null_exprs = ", ".join(
        f'round(100.0 * count(*) FILTER (WHERE "{c}" IS NULL) / count(*), 2) AS "{c}"'
        for c in cols
        if c != "_file"
    )
    out += ["", "## Null rate per column (%)", "", md_table(con, f"SELECT {null_exprs} FROM s1")]

    if has("arrival_planned_time", "arrival_change_time"):
        out += [
            "",
            "## Change times without planned times",
            "",
            md_table(
                con,
                """
            SELECT count(*) FILTER (
                       WHERE arrival_change_time IS NOT NULL AND arrival_planned_time IS NULL
                   ) AS arrival_change_without_plan,
                   count(*) FILTER (
                       WHERE departure_change_time IS NOT NULL AND departure_planned_time IS NULL
                   ) AS departure_change_without_plan
            FROM s1""",
            ),
        ]

    if has(
        "id",
        "train_line_ride_id",
        "train_line_station_num",
        "arrival_planned_time",
        "departure_planned_time",
    ):
        out += [
            "",
            "## Duplicate candidate keys",
            "",
            md_table(
                con,
                """
            SELECT 'id' AS candidate_key,
                   count(*) - count(DISTINCT id) AS duplicate_rows
            FROM s1
            UNION ALL
            SELECT 'train_line_ride_id + train_line_station_num',
                   count(*) - count(DISTINCT (train_line_ride_id, train_line_station_num))
                 FROM s1
                 UNION ALL
                 SELECT 'ride + stop + planned time',
                     count(*) - count(DISTINCT (
                      train_line_ride_id,
                      train_line_station_num,
                      coalesce(arrival_planned_time, departure_planned_time)
                     ))
            FROM s1""",
            ),
        ]

    if has("train_number", "delay_in_min", "train_type"):
        out += [
            "",
            "## Junk and rail-exclusion rows",
            "",
            md_table(
                con,
                """
            SELECT count(*) FILTER (WHERE nullif(trim(train_type), '') IS NULL) AS blank_train_type,
                   count(*) FILTER (
                       WHERE nullif(trim(train_number), '') IS NULL
                   ) AS blank_train_number,
                   count(*) FILTER (WHERE delay_in_min IS NULL) AS missing_delay,
                   count(*) FILTER (WHERE train_type = 'Bus') AS bus_rows
            FROM s1""",
            ),
        ]

    if has("delay_in_min", "arrival_change_time", "departure_change_time") and has(
        "arrival_planned_time", "departure_planned_time"
    ):
        out += [
            "",
            "## Hourly delay and change-time coverage",
            "",
            "Hours are not considered gaps merely because they lack planned stops. Coverage below",
            "half the month's median is flagged for investigation;",
            "an empty table means none were flagged.",
            "",
            md_table(
                con,
                """
            WITH row_hours AS (
                SELECT date_trunc('hour', CAST(coalesce(
                           arrival_planned_time, departure_planned_time
                       ) AS TIMESTAMP)) AS h,
                       count(*) AS rows,
                       count(*) FILTER (WHERE delay_in_min IS NOT NULL) AS delay_rows,
                       count(*) FILTER (WHERE arrival_change_time IS NOT NULL
                                           OR departure_change_time IS NOT NULL) AS change_rows
                FROM s1
                WHERE coalesce(arrival_planned_time, departure_planned_time) IS NOT NULL
                  AND train_type <> 'Bus'
                  AND nullif(trim(train_type), '') IS NOT NULL
                GROUP BY 1
            ),
            bounds AS (
                SELECT min(h) AS first_hour, max(h) AS last_hour FROM row_hours
            ),
            expected_hours AS (
                SELECT unnest(generate_series(
                    first_hour, last_hour, INTERVAL 1 HOUR
                )) AS h
                FROM bounds
            ),
            hourly AS (
                SELECT expected_hours.h,
                       coalesce(row_hours.rows, 0) AS rows,
                       coalesce(row_hours.delay_rows, 0) AS delay_rows,
                       coalesce(row_hours.change_rows, 0) AS change_rows,
                       row_hours.delay_rows::DOUBLE / nullif(row_hours.rows, 0) AS delay_share,
                       row_hours.change_rows::DOUBLE / nullif(row_hours.rows, 0) AS change_share
                FROM expected_hours
                LEFT JOIN row_hours USING (h)
            ),
            scored AS (
                SELECT *,
                    median(delay_share) OVER (
                        PARTITION BY strftime(h, '%Y-%m')
                    ) AS month_delay_median,
                    median(change_share) OVER (
                        PARTITION BY strftime(h, '%Y-%m')
                    ) AS month_change_median
                FROM hourly
            )
            SELECT strftime(h, '%Y-%m-%d %H:00') AS hour, rows,
                   round(100 * delay_share, 1) AS delay_pct,
                   round(100 * change_share, 1) AS change_time_pct,
                   rows = 0 OR delay_share < month_delay_median * 0.5
                       OR change_share < month_change_median * 0.5 AS low_coverage
            FROM scored
            WHERE rows = 0 OR delay_share < month_delay_median * 0.5
                       OR change_share < month_change_median * 0.5
            ORDER BY h""",
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
