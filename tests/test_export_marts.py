import json

import duckdb

from dbp.publish.export_marts import MART_NAMES, dbt_run_summary, export_marts


def test_export_marts_writes_only_aggregate_parquet(tmp_path):
    database = tmp_path / "test.duckdb"
    con = duckdb.connect(str(database))
    con.sql("CREATE SCHEMA marts")
    con.sql("CREATE TABLE marts.agg_state_month_type AS SELECT DATE '2026-01-01' AS service_month")
    con.sql("CREATE TABLE marts.agg_station_month_type AS SELECT 'Hamburg Hbf' AS station_name")
    con.sql("""
        CREATE TABLE marts.agg_hamburg_weekly AS
        SELECT 'line' AS item_kind, 'S1' AS item_key
    """)
    con.sql("""
        CREATE TABLE marts.agg_state_hour_weekday AS
        SELECT 'Hamburg' AS federal_state, 1 AS iso_weekday, 8 AS service_hour
    """)
    con.sql("CREATE TABLE marts.agg_month_coverage AS SELECT DATE '2026-01-01' AS service_month")
    for name in ("agg_delay_sources", "agg_station_delay_gain", "agg_delay_along_route"):
        con.sql(f"CREATE TABLE marts.{name} AS SELECT DATE '2026-01-01' AS service_month")
    con.close()

    published = tmp_path / "published"
    s1_directory = tmp_path / "raw_s1"
    s1_directory.mkdir()
    (s1_directory / "data-2026-01.parquet").touch()
    (s1_directory / "data-2026-02.parquet").touch()
    status = export_marts(database, published, s1_directory, tmp_path / "no_run_results.json")

    assert set(status["row_counts"]) == set(MART_NAMES)
    assert status["event_month_start"] == "2026-01-01"
    assert status["event_month_end"] == "2026-01-01"
    assert status["source_month_start"] == "2026-01"
    assert status["source_month_end"] == "2026-02"
    for name in MART_NAMES:
        assert (published / "marts" / f"{name}.parquet").exists()
    saved_status = json.loads((published / "run_status.json").read_text(encoding="utf-8"))
    assert saved_status["row_counts"] == status["row_counts"]

def test_dbt_run_summary_counts_tests_and_models(tmp_path):
    run_results = tmp_path / "run_results.json"
    run_results.write_text(json.dumps({
        "metadata": {"generated_at": "2026-10-02T00:00:50Z"},
        "results": [
            {"unique_id": "model.bahnpulse.fct_stop_event", "status": "success"},
            {"unique_id": "test.bahnpulse.unique_x", "status": "pass"},
            {"unique_id": "test.bahnpulse.not_null_y", "status": "pass"},
            {"unique_id": "test.bahnpulse.assert_z", "status": "fail"},
        ],
    }))

    summary = dbt_run_summary(run_results)

    assert summary == {
        "run_at": "2026-10-02T00:00:50Z",
        "tests_passed": 2,
        "tests_failed": 1,
        "tests_warned": 0,
        "models_built": 1,
    }
    assert dbt_run_summary(tmp_path / "missing.json") is None
