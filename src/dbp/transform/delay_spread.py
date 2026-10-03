"""Where delays start and how they build up: trips rebuilt from stop events, month by month.

Used by the dbt Python models agg_delay_sources, agg_station_delay_gain and
agg_delay_along_route. Rebuilding trips needs window functions over every stop; over the whole
history at once (160M+ rows) DuckDB spilled 40 GB to disk, so each month is processed and
aggregated on its own (about 15M rows, a few seconds). A trip running over midnight at the end
of a month is split in two, which affects a negligible share of trips.

The source has no trip id: train_line_ride_id repeats on every day a train runs. A trip is one
ride id's stops in time order until the stop number restarts or the plan jumps by more than 6
hours. Lateness is delay floored at 0, so an early arrival followed by an on-time departure is
not counted as delay gained at the station. For every complete trip:

    final lateness = lateness at the first station
                     + lateness added and recovered while running between stations
                     + lateness added and recovered while standing at stations
"""

from __future__ import annotations

import pandas as pd

# One row per stop of one month, in trip order, with running and dwell gains.
TRIP_STOP_SQL = """
WITH stops AS (
    SELECT
        stop_event_id,
        station_key,
        train_group,
        service_month,
        train_line_ride_id AS ride_id,
        train_line_station_num AS stop_num,
        arrival_planned_time,
        departure_planned_time,
        arrival_delay_min,
        departure_delay_min,
        coalesce(arrival_is_canceled, false) AS arrival_cancelled,
        coalesce(departure_is_canceled, false) AS departure_cancelled,
        coalesce(departure_planned_time, arrival_planned_time) AS planned_time
    FROM {events}
    WHERE service_time >= TIMESTAMP '{month}'
      AND service_time < TIMESTAMP '{month}' + INTERVAL 1 MONTH
      AND NOT is_junk
      AND is_rail_service
      AND train_group <> 'Other'
      AND train_line_ride_id IS NOT NULL
      AND train_line_station_num IS NOT NULL
      AND coalesce(departure_planned_time, arrival_planned_time) IS NOT NULL
),
trip_breaks AS (
    SELECT
        *,
        CASE
            WHEN stop_num <= lag(stop_num) OVER ride_order
              OR planned_time - lag(planned_time) OVER ride_order > INTERVAL 6 HOUR
                THEN 1
            ELSE 0
        END AS starts_new_trip
    FROM stops
    -- stop_event_id breaks ties between duplicate records (same ride, stop and time), so
    -- every run orders them the same way and gives identical results.
    WINDOW ride_order AS (PARTITION BY ride_id ORDER BY planned_time, stop_num, stop_event_id)
),
trips AS (
    SELECT
        *,
        sum(starts_new_trip) OVER (
            PARTITION BY ride_id ORDER BY planned_time, stop_num, stop_event_id
            ROWS UNBOUNDED PRECEDING
        ) AS trip_seq
    FROM trip_breaks
),
lateness AS (
    SELECT
        *,
        CASE
            WHEN arrival_planned_time IS NOT NULL AND NOT arrival_cancelled
                THEN greatest(arrival_delay_min, 0)
        END AS arrival_late_min,
        CASE
            WHEN departure_planned_time IS NOT NULL AND NOT departure_cancelled
                THEN greatest(departure_delay_min, 0)
        END AS departure_late_min
    FROM trips
),
with_previous AS (
    SELECT
        *,
        lag(stop_num) OVER trip_order AS prev_stop_num,
        lag(departure_late_min) OVER trip_order AS prev_late_min,
        min(stop_num) OVER whole_trip AS first_stop_num,
        max(stop_num) OVER whole_trip AS last_stop_num,
        count(*) OVER whole_trip AS trip_stop_count,
        -- The data can start or end mid-route (a train from or to abroad, or stops the source
        -- missed): only a trip that starts with no planned arrival and ends with no planned
        -- departure runs from its true first to its true last station.
        first_value(arrival_planned_time IS NULL) OVER whole_trip_ordered AS starts_at_origin,
        last_value(departure_planned_time IS NULL) OVER whole_trip_ordered AS ends_at_terminus,
        -- Every planned arrival and departure ran and has a delay, so the trip's lateness
        -- splits exactly into origin + running + dwell.
        bool_and(
            (arrival_planned_time IS NULL OR arrival_late_min IS NOT NULL)
            AND (departure_planned_time IS NULL OR departure_late_min IS NOT NULL)
        ) OVER whole_trip AS fully_observed
    FROM lateness
    WINDOW
        trip_order AS (PARTITION BY ride_id, trip_seq ORDER BY stop_num, stop_event_id),
        whole_trip AS (PARTITION BY ride_id, trip_seq),
        whole_trip_ordered AS (
            PARTITION BY ride_id, trip_seq ORDER BY stop_num, stop_event_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        )
)
SELECT
    station_key,
    train_group,
    service_month,
    ride_id,
    trip_seq,
    stop_num,
    first_stop_num,
    last_stop_num,
    arrival_late_min,
    departure_late_min,
    -- Only between consecutive stops, so a stop missing from the data never hides a gain.
    CASE WHEN prev_stop_num = stop_num - 1 THEN prev_late_min END AS prev_departure_late_min,
    CASE WHEN prev_stop_num = stop_num - 1 THEN arrival_late_min - prev_late_min END
        AS running_gain_min,
    departure_late_min - arrival_late_min AS dwell_gain_min,
    first_stop_num = 1
        AND last_stop_num - first_stop_num + 1 = trip_stop_count
        AND trip_stop_count >= 3
        AND starts_at_origin
        AND ends_at_terminus
        AND fully_observed AS is_complete_trip,
    CASE
        WHEN last_stop_num > first_stop_num
            THEN CAST(10 * round(10.0 * (stop_num - first_stop_num)
                / (last_stop_num - first_stop_num)) AS INTEGER)
    END AS route_pct
FROM with_previous
"""

# Per month, train type and whether the trip ended 6+ minutes late: lateness by source.
DELAY_SOURCES_SQL = """
WITH trips AS (
    SELECT
        any_value(train_group) AS train_group,
        min(service_month) AS service_month,
        max(departure_late_min) FILTER (WHERE stop_num = first_stop_num) AS origin_late_min,
        sum(greatest(running_gain_min, 0)) AS running_added_min,
        sum(least(running_gain_min, 0)) AS running_recovered_min,
        sum(greatest(dwell_gain_min, 0)) AS dwell_added_min,
        sum(least(dwell_gain_min, 0)) AS dwell_recovered_min,
        max(arrival_late_min) FILTER (WHERE stop_num = last_stop_num) AS final_late_min
    FROM {trip_stops}
    WHERE is_complete_trip
    GROUP BY ride_id, trip_seq
)
SELECT
    service_month,
    train_group,
    final_late_min >= 6 AS ends_late,
    count(*) AS trip_count,
    sum(origin_late_min) AS origin_late_min,
    sum(running_added_min) AS running_added_min,
    sum(running_recovered_min) AS running_recovered_min,
    sum(dwell_added_min) AS dwell_added_min,
    sum(dwell_recovered_min) AS dwell_recovered_min,
    sum(final_late_min) AS final_late_min
FROM trips
WHERE final_late_min IS NOT NULL
GROUP BY 1, 2, 3
"""

# Per station (by name, so separate S-Bahn platforms count as one), month and train type:
# lateness added on the way in (running, credited to the station reached) and while standing
# there (dwell). A "delay start" is where a train first crosses 6 minutes late.
STATION_GAIN_SQL = """
SELECT
    station.station_name,
    station.federal_state,
    stop.service_month,
    stop.train_group,
    count(*) FILTER (
        WHERE stop.running_gain_min IS NOT NULL OR stop.dwell_gain_min IS NOT NULL
    ) AS measured_stop_count,
    coalesce(sum(greatest(stop.running_gain_min, 0)), 0) AS running_added_min,
    coalesce(sum(least(stop.running_gain_min, 0)), 0) AS running_recovered_min,
    coalesce(sum(greatest(stop.dwell_gain_min, 0)), 0) AS dwell_added_min,
    coalesce(sum(least(stop.dwell_gain_min, 0)), 0) AS dwell_recovered_min,
    count(*) FILTER (
        WHERE (stop.prev_departure_late_min < 6 AND stop.arrival_late_min >= 6)
           OR (stop.arrival_late_min < 6 AND stop.departure_late_min >= 6)
    ) AS delay_start_count
FROM {trip_stops} AS stop
JOIN {stations} AS station USING (station_key)
GROUP BY 1, 2, 3, 4
HAVING measured_stop_count > 0
"""

# Lateness by position on the route (complete trips with 5+ stops, steps of 10%).
ALONG_ROUTE_SQL = """
SELECT
    service_month,
    train_group,
    route_pct,
    count(*) AS stop_count,
    sum(coalesce(arrival_late_min, departure_late_min)) AS late_min,
    count(*) FILTER (WHERE coalesce(arrival_late_min, departure_late_min) >= 6)
        AS late_stop_count
FROM {trip_stops}
WHERE is_complete_trip
  AND last_stop_num - first_stop_num >= 4
GROUP BY 1, 2, 3
"""


def build_by_month(
    session, events, aggregate_sql: str, name: str, stations=None
) -> pd.DataFrame:
    """Rebuild trips for one month at a time and stack the monthly aggregates.

    `events` (and `stations`) are DuckDB relations; `name` keeps the temporary objects of
    models running side by side apart.
    """
    # Plain SQL views on the relations' queries: views made with relation.create_view() let
    # no filter through, so every month re-read the whole history (minutes instead of seconds).
    session.sql(f"CREATE OR REPLACE TEMP VIEW {name}_events AS {events.sql_query()}")
    if stations is not None:
        session.sql(f"CREATE OR REPLACE TEMP VIEW {name}_stations AS {stations.sql_query()}")
    months = [
        row[0]
        for row in session.sql(
            f"SELECT DISTINCT service_month FROM {name}_events "
            "WHERE service_month IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
    frames = []
    for month in months:
        session.sql(
            f"CREATE OR REPLACE TEMP TABLE {name}_trip_stops AS "
            + TRIP_STOP_SQL.format(events=f"{name}_events", month=month)
        )
        frames.append(
            session.sql(
                aggregate_sql.format(
                    trip_stops=f"{name}_trip_stops", stations=f"{name}_stations"
                )
            ).df()
        )
    session.sql(f"DROP TABLE IF EXISTS {name}_trip_stops")
    session.sql(f"DROP VIEW IF EXISTS {name}_events")
    session.sql(f"DROP VIEW IF EXISTS {name}_stations")
    return pd.concat(frames, ignore_index=True)
