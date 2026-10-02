{{ config(materialized='table') }}

-- Data completeness per month. The source misses whole fetch hours now and then (and only
-- covers all stations from 2 Nov 2025); such hours still have a few stops, so a gap shows up
-- as an hour with under half the usual volume for that weekday and hour of the month.
WITH hourly AS (
    SELECT date_trunc('hour', service_time) AS service_hour, count(*) AS stop_count
    FROM {{ ref('fct_stop_event') }}
    WHERE service_time IS NOT NULL
      AND NOT is_junk
      AND is_rail_service
    GROUP BY 1
),
typical AS (
    SELECT
        service_hour,
        stop_count,
        median(stop_count) OVER (
            PARTITION BY date_trunc('month', service_hour), isodow(service_hour),
                hour(service_hour)
        ) AS typical_count
    FROM hourly
)
SELECT
    CAST(date_trunc('month', service_hour) AS DATE) AS service_month,
    count(*) AS hour_count,
    count(*) FILTER (WHERE stop_count < 0.5 * typical_count) AS low_data_hours,
    round(100.0 * sum(least(stop_count, typical_count)) / sum(typical_count), 1)
        AS volume_completeness_pct
FROM typical
GROUP BY 1
