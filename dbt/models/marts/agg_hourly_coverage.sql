{{ config(materialized='table') }}

SELECT
    date_trunc('hour', service_time) AS service_hour,
    train_group,
    count(*) AS planned_stop_count,
    count(*) FILTER (WHERE delay_in_min IS NOT NULL) AS delay_count,
    count(*) FILTER (
        WHERE arrival_change_time IS NOT NULL OR departure_change_time IS NOT NULL
    ) AS change_time_count,
    round(100.0 * delay_count / nullif(planned_stop_count, 0), 2) AS delay_coverage_pct,
    round(100.0 * change_time_count / nullif(planned_stop_count, 0), 2) AS change_time_coverage_pct
FROM {{ ref('fct_stop_event') }}
WHERE NOT is_junk
  AND is_rail_service
  AND service_time IS NOT NULL
GROUP BY 1, 2