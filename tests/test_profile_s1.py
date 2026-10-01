import duckdb

from dbp.profile.profile_s1 import build_report


def test_profile_report_on_small_fixture(tmp_path):
    path = tmp_path / "data-2026-08.parquet"
    con = duckdb.connect()
    con.sql(f"""
        COPY (
            SELECT * FROM (VALUES
                ('Hamburg Hbf', '8000001', 'S1', 'S', 'S1',
                 TIMESTAMP '2026-08-01 08:00:00', NULL, 2),
                ('Hamburg Hbf', '8000001', 'S1', 'S', 'S1',
                 TIMESTAMP '2026-08-01 08:00:00', NULL, 2),
                ('Berlin Hbf', '8000002', '100', 'ICE', NULL,
                 NULL, TIMESTAMP '2026-08-01 10:00:00', 7)
            ) t(station_name, eva, train_number, train_type, line_number,
                arrival_planned_time, departure_planned_time, delay_in_min)
        ) TO '{path}' (FORMAT parquet)
    """)
    report = build_report(str(tmp_path / "data-*.parquet"))
    assert "## Train types" in report
    assert "| S1 | 2 | 1 |" in report  # Hamburg S-Bahn line S1: 2 stops at 1 station
    assert "| 3 | 2 | 1 |" in report  # 3 rows, 2 distinct keys, 1 duplicate
    assert "| 2026-08 | 1 |" in report  # 09:00 has no planned stop
