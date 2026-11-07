"""Read-only DuckDB sandbox over the published marts for "Ask the data".

Generated SQL runs here, never on the dbt database: an in-memory DuckDB holding six clean views
(counts only, no precomputed percentages, so ratios are always summed correctly), with file
and network access switched off and the configuration locked, so a query cannot read files,
attach databases or change settings. Only a single SELECT on the known views is accepted.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from dbp.config import DATA

MART_DIR = DATA / "published" / "marts"
MAX_ROWS = 200
TIMEOUT_SECONDS = 10
# A month with this many low-data hours counts as incomplete (as GAP_HOURS_WARN on the dashboard).
GAP_HOURS = 24

# View name -> SQL over the mart's Parquet file ({path}). Columns are renamed to plain words.
VIEWS = {
    "state_month": """
        SELECT federal_state, CAST(service_month AS DATE) AS month, train_group,
            planned_stop_count AS planned_stops, arrival_count AS arrivals,
            on_time_arrival_count AS on_time_arrivals,
            cancelled_arrival_count AS cancelled_arrivals,
            avg_arrival_delay_min * arrival_count AS late_minutes,
            delay_6_15_count AS late_6_15, delay_16_30_count AS late_16_30,
            delay_31_60_count AS late_31_60, delay_over_60_count AS late_over_60
        FROM read_parquet('{path}/agg_state_month_type.parquet')""",
    "station_month": """
        SELECT station_name, federal_state, CAST(service_month AS DATE) AS month, train_group,
            planned_stop_count AS planned_stops, arrival_count AS arrivals,
            on_time_arrival_count AS on_time_arrivals,
            cancelled_arrival_count AS cancelled_arrivals,
            avg_arrival_delay_min * arrival_count AS late_minutes
        FROM read_parquet('{path}/agg_station_month_type.parquet')""",
    "state_hour": """
        SELECT federal_state, CAST(service_month AS DATE) AS month, train_group,
            iso_weekday AS weekday, service_hour AS hour, arrival_count AS arrivals,
            on_time_arrival_count AS on_time_arrivals
        FROM read_parquet('{path}/agg_state_hour_weekday.parquet')""",
    "delay_sources": """
        SELECT CAST(service_month AS DATE) AS month, train_group, ends_late, trip_count AS trips,
            origin_late_min, running_added_min, running_recovered_min, dwell_added_min,
            dwell_recovered_min, final_late_min
        FROM read_parquet('{path}/agg_delay_sources.parquet')""",
    "station_delay_gain": """
        SELECT station_name, federal_state, CAST(service_month AS DATE) AS month, train_group,
            measured_stop_count AS measured_stops, running_added_min, running_recovered_min,
            dwell_added_min, dwell_recovered_min, delay_start_count AS delay_starts
        FROM read_parquet('{path}/agg_station_delay_gain.parquet')""",
    "delay_along_route": """
        SELECT CAST(service_month AS DATE) AS month, train_group, route_pct,
            stop_count AS stops, late_min, late_stop_count AS late_stops
        FROM read_parquet('{path}/agg_delay_along_route.parquet')""",
}


@dataclass(frozen=True)
class Period:
    first: date
    last: date
    incomplete: tuple[date, ...]  # months with many hours missing


def data_period(con: duckdb.DuckDBPyConnection) -> Period:
    """Months the sandbox covers, so prompts and captions follow the published data."""
    cursor = con.cursor()
    try:
        first, last = cursor.sql("SELECT min(month), max(month) FROM state_month").fetchone()
        rows = cursor.execute(
            "SELECT month FROM month_coverage WHERE low_data_hours >= ? "
            "AND month BETWEEN ? AND ? ORDER BY month",
            [GAP_HOURS, first, last],
        ).fetchall()
    finally:
        cursor.close()
    return Period(first, last, tuple(row[0] for row in rows))


class UnsafeQuery(ValueError):
    """The SQL is not a single read-only SELECT on the known views."""


@dataclass
class QueryResult:
    frame: pd.DataFrame
    truncated: bool


def open_sandbox(mart_dir: Path = MART_DIR) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with the views loaded, then file access off and settings locked."""
    con = duckdb.connect()
    for name, sql in VIEWS.items():
        # Materialised as tables: views would need file access at query time.
        con.sql(f"CREATE TABLE {name} AS {sql.format(path=mart_dir.as_posix())}")
    # For data_period only; not in VIEWS, so generated SQL cannot query it.
    con.sql(
        "CREATE TABLE month_coverage AS SELECT CAST(service_month AS DATE) AS month, "
        f"low_data_hours FROM read_parquet('{mart_dir.as_posix()}/agg_month_coverage.parquet')"
    )
    con.sql("SET enable_external_access = false")
    con.sql("SET lock_configuration = true")
    return con


def check_query(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    """Return the SQL if it is one SELECT on known views; raise UnsafeQuery otherwise."""
    statements = con.extract_statements(sql)
    if len(statements) != 1:
        raise UnsafeQuery(f"Expected one statement, got {len(statements)}.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise UnsafeQuery(f"Only SELECT is allowed, not {statements[0].type.name}.")
    # Table functions (read_csv, duckdb_settings(), range(), ...) are not needed to answer
    # questions about the views; refusing them all keeps the surface small. Checked first,
    # on the parse tree only, before anything is resolved.
    tree = con.execute("SELECT json_serialize_sql(?::VARCHAR)", [sql]).fetchone()[0]
    if '"TABLE_FUNCTION"' in tree:
        raise UnsafeQuery("Table functions are not allowed; query the views only.")
    unknown = con.get_table_names(sql) - set(VIEWS)
    if unknown:
        raise UnsafeQuery(f"Unknown tables: {', '.join(sorted(unknown))}.")
    return sql.strip().rstrip(";")


def run_query(con: duckdb.DuckDBPyConnection, sql: str) -> QueryResult:
    """Check and run the SQL with a time limit, keeping at most MAX_ROWS rows."""
    # Own cursor per query: the app shares one sandbox across visitor threads, and a
    # connection is not thread-safe (nor should a timeout interrupt someone else's query).
    cursor = con.cursor()
    try:
        sql = check_query(cursor, sql)
        timer = threading.Timer(TIMEOUT_SECONDS, cursor.interrupt)
        timer.start()
        try:
            frame = cursor.sql(sql).limit(MAX_ROWS + 1).df()
        finally:
            timer.cancel()
    finally:
        cursor.close()
    # Sums of counts come back as floats (457.0); show whole numbers as whole numbers.
    for column in frame.select_dtypes("float").columns:
        values = frame[column].dropna()
        if len(values) and (values == values.round()).all() and values.abs().max() < 2**53:
            frame[column] = frame[column].astype("Int64")
    return QueryResult(frame.head(MAX_ROWS), truncated=len(frame) > MAX_ROWS)
