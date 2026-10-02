{{ config(materialized='table') }}

WITH bounds AS (
    SELECT min(date_key) AS first_day, max(date_key) AS last_day
    FROM {{ ref('fct_stop_event') }}
    WHERE date_key IS NOT NULL
),
calendar AS (
    SELECT unnest(generate_series(first_day, last_day, INTERVAL 1 DAY)) AS calendar_day
    FROM bounds
)
SELECT
    CAST(calendar_day AS DATE) AS date_key,
    extract(year FROM calendar_day)::INTEGER AS year,
    extract(month FROM calendar_day)::INTEGER AS month,
    strftime(calendar_day, '%A') AS weekday_name,
    strftime(calendar_day, '%w') IN ('0', '6') AS is_weekend
FROM calendar