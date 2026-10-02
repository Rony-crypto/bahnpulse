{{ config(materialized='table') }}

SELECT
    hour_key,
    hour_key BETWEEN 6 AND 8 OR hour_key BETWEEN 16 AND 18 AS peak_flag
FROM (SELECT unnest(generate_series(0, 23))::INTEGER AS hour_key)