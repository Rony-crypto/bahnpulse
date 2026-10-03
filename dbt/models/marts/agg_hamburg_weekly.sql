{{ config(materialized='table') }}

-- Weeks start on Monday, so the first and last week of the history are usually cut short
-- (e.g. a week holding only 31 Aug). Keep only weeks fully inside the event window.
WITH event_window AS (
    SELECT
        min(service_month) AS first_day,
        CAST(max(service_month) + INTERVAL 1 MONTH - INTERVAL 1 DAY AS DATE) AS last_day
    FROM {{ ref('fct_stop_event') }}
),
hamburg_events AS (
    SELECT
        event.*,
        station.station_name,
        CAST(date_trunc('week', event.service_time) AS DATE) AS service_week,
        CASE
            WHEN strftime(event.service_time, '%w') NOT IN ('0', '6')
                 AND (
                     extract(hour FROM event.service_time) BETWEEN 6 AND 8
                     OR extract(hour FROM event.service_time) BETWEEN 16 AND 18
                 )
                THEN 'Weekday peak'
            ELSE 'Off-peak'
        END AS time_slot
    FROM {{ ref('fct_stop_event') }} AS event
    JOIN {{ ref('dim_station') }} AS station USING (station_key)
    CROSS JOIN event_window
    WHERE station.federal_state = 'Hamburg'
      AND CAST(date_trunc('week', event.service_time) AS DATE) >= event_window.first_day
      AND CAST(date_trunc('week', event.service_time) AS DATE) + 6 <= event_window.last_day
      AND NOT event.is_junk
      AND event.is_rail_service
      AND event.service_time IS NOT NULL
),
items AS (
    SELECT
        'line' AS item_kind,
        line_number AS item_key,
        CAST(NULL AS VARCHAR) AS station_key,
        CAST(NULL AS VARCHAR) AS station_name,
        service_week,
        time_slot,
        train_group,
        arrival_planned_time,
        arrival_is_canceled,
        is_cancelled,
        delay_in_min
    FROM hamburg_events
    WHERE line_number IS NOT NULL
      AND (
          (train_group = 'S' AND line_number <> 'S0')
          -- RE and RB lines by their line name; the train type does not always match it
          -- (e.g. RE5 runs as RB, RB41 as RE).
          OR regexp_full_match(line_number, 'R[EB][0-9]+')
      )
    UNION ALL
    SELECT
        'station', station_name, station_key, station_name,
        service_week, time_slot, train_group, arrival_planned_time, arrival_is_canceled,
        is_cancelled, delay_in_min
    FROM hamburg_events
    UNION ALL
    SELECT
        'train_type', train_group, station_key, station_name,
        service_week, time_slot, train_group, arrival_planned_time, arrival_is_canceled,
        is_cancelled, delay_in_min
    FROM hamburg_events
)
SELECT
    item_kind,
    item_key,
    station_key,
    station_name,
    service_week,
    time_slot,
    train_group,
    count(*) AS stop_count,
    -- Same definition as agg_state_month_type: arrival or departure cancelled.
    count(*) FILTER (WHERE is_cancelled) AS cancelled_stop_count,
    count(*) FILTER (
        WHERE arrival_planned_time IS NOT NULL
          AND NOT arrival_is_canceled
          AND delay_in_min IS NOT NULL
    ) AS arrival_count,
    count(*) FILTER (
        WHERE arrival_planned_time IS NOT NULL
          AND NOT arrival_is_canceled
          AND delay_in_min < 6
    ) AS on_time_arrival_count,
    count(*) FILTER (
        WHERE arrival_planned_time IS NOT NULL
          AND NOT arrival_is_canceled
          AND delay_in_min IS NOT NULL
    ) AS delay_count,
    sum(delay_in_min) FILTER (
        WHERE arrival_planned_time IS NOT NULL
          AND NOT arrival_is_canceled
          AND delay_in_min IS NOT NULL
    ) AS delay_total_min,
    round(100.0 * on_time_arrival_count / nullif(arrival_count, 0), 2) AS punctuality_pct,
    round(delay_total_min / nullif(delay_count, 0), 2) AS avg_arrival_delay_min
FROM items
GROUP BY 1, 2, 3, 4, 5, 6, 7