{{ config(materialized='table') }}

-- On-time share by weekday and planned hour, for the "when are trains late?" heatmap.
SELECT
    station.federal_state,
    event.service_month,
    event.train_group,
    CAST(isodow(event.service_time) AS INTEGER) AS iso_weekday,
    event.hour_key AS service_hour,
    count(*) FILTER (
        WHERE event.arrival_planned_time IS NOT NULL
          AND NOT event.arrival_is_canceled
          AND event.arrival_delay_min IS NOT NULL
    ) AS arrival_count,
    count(*) FILTER (
        WHERE event.arrival_planned_time IS NOT NULL
          AND NOT event.arrival_is_canceled
          AND event.arrival_delay_min < 6
    ) AS on_time_arrival_count
FROM {{ ref('fct_stop_event') }} AS event
JOIN {{ ref('dim_station') }} AS station USING (station_key)
WHERE NOT event.is_junk
  AND event.is_rail_service
  AND event.service_month IS NOT NULL
GROUP BY 1, 2, 3, 4, 5
HAVING arrival_count > 0
