{{ config(materialized='table') }}

SELECT
    event.station_key,
    station.station_name,
    station.federal_state,
    event.service_month,
    event.train_group,
    count(*) AS planned_stop_count,
    count(*) FILTER (WHERE event.is_cancelled) AS cancelled_stop_count,
    count(*) FILTER (
        WHERE event.arrival_planned_time IS NOT NULL
          AND NOT event.arrival_is_canceled
          AND event.delay_in_min IS NOT NULL
    ) AS arrival_count,
    count(*) FILTER (
        WHERE event.arrival_planned_time IS NOT NULL
          AND NOT event.arrival_is_canceled
          AND event.delay_in_min < 6
    ) AS on_time_arrival_count,
    count(*) FILTER (
        WHERE event.arrival_planned_time IS NOT NULL
          AND event.arrival_is_canceled
    ) AS cancelled_arrival_count,
    round(
        100.0 * on_time_arrival_count / nullif(arrival_count, 0),
        2
    ) AS punctuality_pct,
    round(avg(event.delay_in_min) FILTER (
        WHERE event.arrival_planned_time IS NOT NULL
          AND NOT event.arrival_is_canceled
    ), 2) AS avg_arrival_delay_min,
    -- Cancelled share of planned arrivals (cancelled + ran), the same base as the on-time
    -- share. Counting arrivals counts each lost train once, at the station that lost it.
    round(
        100.0 * cancelled_arrival_count / nullif(arrival_count + cancelled_arrival_count, 0), 2
    ) AS cancellation_pct
FROM {{ ref('fct_stop_event') }} AS event
JOIN {{ ref('dim_station') }} AS station USING (station_key)
WHERE NOT event.is_junk
  AND event.is_rail_service
  AND event.service_month IS NOT NULL
GROUP BY 1, 2, 3, 4, 5