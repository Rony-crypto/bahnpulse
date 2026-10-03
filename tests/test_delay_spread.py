from datetime import datetime, timedelta

import duckdb
import pandas as pd

from dbp.transform.delay_spread import (
    ALONG_ROUTE_SQL,
    DELAY_SOURCES_SQL,
    STATION_GAIN_SQL,
    build_by_month,
)


def stop(ride, num, station, arrive, depart, arrival_delay, departure_delay, **flags):
    """One stop event; times are minutes after 2026-05-04 08:00, None = no arrival/departure."""
    start = datetime(2026, 5, 4, 8)
    at = lambda minutes: start + timedelta(minutes=minutes) if minutes is not None else None  # noqa: E731
    return {
        "stop_event_id": f"{ride}-{num}-{arrive}-{depart}",
        "station_key": station,
        "train_group": flags.get("group", "ICE"),
        "service_month": datetime(2026, 5, 1).date(),
        "service_time": at(depart if depart is not None else arrive),
        "train_line_ride_id": ride,
        "train_line_station_num": num,
        "arrival_planned_time": at(arrive),
        "departure_planned_time": at(depart),
        "arrival_delay_min": arrival_delay,
        "departure_delay_min": departure_delay,
        "arrival_is_canceled": flags.get("arrival_cancelled", False),
        "departure_is_canceled": flags.get("departure_cancelled", False),
        "is_junk": False,
        "is_rail_service": True,
    }


def run(rows, sql, with_stations=False):
    con = duckdb.connect()
    con.register("events_frame", pd.DataFrame(rows))
    con.sql("CREATE TABLE events AS SELECT * FROM events_frame")
    con.sql(
        "CREATE TABLE stations AS SELECT * FROM (VALUES ('A', 'Station A', 'Hamburg'), "
        "('B', 'Station B', 'Hamburg'), ('C', 'Station C', 'Bremen'), "
        "('D', 'Station D', 'Bremen')) AS t(station_key, station_name, federal_state)"
    )
    stations = con.table("stations") if with_stations else None
    return build_by_month(con, con.table("events"), sql, "test", stations=stations)


# A -> B -> C -> D: leaves A 2 min late, loses 5 min running to B, stands 3 min too long at B,
# recovers 4 min running to C, then runs on time to D (final 6 min late).
TRIP = [
    stop("r1", 1, "A", None, 0, None, 2),
    stop("r1", 2, "B", 30, 32, 7, 10),
    stop("r1", 3, "C", 60, 62, 6, 6),
    stop("r1", 4, "D", 90, None, 6, None),
]


def test_lateness_splits_exactly_into_origin_running_and_stations():
    sources = run(TRIP, DELAY_SOURCES_SQL).iloc[0]

    assert sources["trip_count"] == 1 and sources["ends_late"]
    assert sources["origin_late_min"] == 2
    assert sources["running_added_min"] == 5
    assert sources["running_recovered_min"] == -4
    assert sources["dwell_added_min"] == 3
    assert sources["final_late_min"] == 6
    parts = sources[
        ["origin_late_min", "running_added_min", "running_recovered_min",
         "dwell_added_min", "dwell_recovered_min"]
    ].sum()
    assert parts == sources["final_late_min"]


def test_same_ride_on_two_days_is_two_trips():
    next_day = [
        {**row, **{
            key: row[key] + timedelta(days=1)
            for key in ("service_time", "arrival_planned_time", "departure_planned_time")
            if row[key] is not None
        }}
        for row in TRIP
    ]

    sources = run(TRIP + next_day, DELAY_SOURCES_SQL)

    assert sources["trip_count"].sum() == 2


def test_early_arrival_is_not_counted_as_delay_gained_at_the_station():
    early = [
        stop("r2", 1, "A", None, 0, None, 0),
        stop("r2", 2, "B", 30, 32, -3, 0),
        stop("r2", 3, "C", 60, None, 0, None),
    ]

    sources = run(early, DELAY_SOURCES_SQL).iloc[0]

    assert sources["dwell_added_min"] == 0 and not sources["ends_late"]


def test_missing_stop_breaks_the_running_gain_and_the_trip_is_not_complete():
    gap = [TRIP[0], TRIP[1], TRIP[3]]  # stop 3 (C) missing from the data

    gains = run(gap, STATION_GAIN_SQL, with_stations=True).set_index("station_name")
    sources = run(gap, DELAY_SOURCES_SQL)

    # D's running gain would span two stretches, and D (last stop) has no dwell, so nothing
    # is measured there.
    assert "Station D" not in gains.index
    assert gains.loc["Station B", "running_added_min"] == 5
    assert sources.empty


def test_delay_start_is_where_the_train_first_crosses_six_minutes():
    gains = run(TRIP, STATION_GAIN_SQL, with_stations=True).set_index("station_name")

    # Leaves A 2 late, reaches B 7 late: B is where the delay started. Nothing can be gained
    # at the first station, so A has no row.
    assert gains["delay_start_count"].to_dict() == {
        "Station B": 1, "Station C": 0, "Station D": 0
    }


def test_route_position_runs_from_first_to_last_station():
    five_stops = [
        stop("r3", n, "A", None if n == 1 else 30 * n, None if n == 5 else 30 * n + 2,
             None if n == 1 else n, None if n == 5 else n)
        for n in range(1, 6)
    ]

    route = run(five_stops, ALONG_ROUTE_SQL).sort_values("route_pct")

    # Quarter points round half up to the nearest 10%.
    assert route["route_pct"].tolist() == [0, 30, 50, 80, 100]
    assert route["stop_count"].sum() == 5


def test_trip_cut_off_before_its_last_station_is_not_complete():
    # The data ends at C, but C still has a departure: the train runs on beyond the data.
    cut = [TRIP[0], TRIP[1], stop("r1", 3, "C", 60, 62, 6, 9)]

    assert run(cut, DELAY_SOURCES_SQL).empty

