import duckdb

from dbp.profile.profile_s1 import build_report


def test_profile_report_on_small_fixture(tmp_path):
    path = tmp_path / "data-2026-08.parquet"
    states_path = tmp_path / "station_state_map.csv"
    states_path.write_text("eva,federal_state\n8000001,Hamburg\n8000002,Berlin\n")
    con = duckdb.connect()
    con.sql(f"""
        COPY (
            SELECT * FROM (VALUES
                ('Hbf', '08000001', '1', 'S', 'S1',
                 TIMESTAMP '2026-08-01 08:00:00', NULL, NULL, NULL,
                 2, 'id-1', 'ride-1', 1),
                ('Hbf', '8000001', '1', 'S', 'S1',
                 TIMESTAMP '2026-08-01 08:00:00', NULL, NULL, NULL,
                 2, 'id-2', 'ride-1', 1),
                ('Berlin Hbf', '8000002', '100', 'ICE', NULL,
                 NULL, NULL, TIMESTAMP '2026-08-01 10:00:00', NULL,
                 7, 'id-3', 'ride-2', 1),
                ('Altona', '8000001', '2', 'S', 'S0',
                 NULL, TIMESTAMP '2026-08-01 09:02:00', TIMESTAMP '2026-08-01 09:00:00', NULL,
                 NULL, 'id-4', 'ride-3', 1)
        ) t(station_name, eva, train_number, train_type, line_number,
            arrival_planned_time, arrival_change_time, departure_planned_time,
            departure_change_time, delay_in_min, id, train_line_ride_id,
            train_line_station_num)
        ) TO '{path}' (FORMAT parquet)
    """)
    report = build_report(str(tmp_path / "data-*.parquet"), states_path)
    assert "## Train type groups" in report
    assert "| S1 | 2 | 1 |" in report
    assert "| id | 0 |" in report
    assert "| train_line_ride_id + train_line_station_num | 1 |" in report
    assert "## Hourly delay and change-time coverage" in report
