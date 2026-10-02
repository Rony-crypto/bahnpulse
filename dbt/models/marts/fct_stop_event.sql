-- A view, not a table: a full copy of every stop event would double disk use (7 GB+) and
-- overflow the GitHub runner in the monthly job. Marts read the Parquet files through it.
{{ config(materialized='view') }}

-- Each monthly file carries a few stops just outside its month. Inside the range they
-- fill the neighbouring month; at the edges they would form near-empty months, so keep
-- only events inside the months covered by source files.
WITH source_window AS (
    SELECT min(source_month) AS first_month, max(source_month) AS last_month
    FROM {{ ref('int_s1_classified') }}
)

SELECT
    s1.stop_record_id AS stop_event_id,
    s1.eva AS station_key,
    -- Types missing from the seed (new operators, typos like "." or "RE 4") get one key, so a
    -- new month never breaks the dimension; the raw value stays in raw_train_type.
    CASE
        WHEN s1.train_type IS NULL THEN '(blank/unknown)'
        WHEN NOT s1.is_mapped_type THEN '(unmapped)'
        ELSE s1.train_type
    END AS train_type_key,
    s1.train_type AS raw_train_type,
    s1.train_group,
    concat_ws('|', s1.train_group, coalesce(s1.line_number, '(unknown)')) AS line_key,
    s1.train_number,
    s1.line_number,
    s1.train_line_ride_id,
    s1.train_line_station_num,
    s1.service_time,
    CAST(date_trunc('month', s1.service_time) AS DATE) AS service_month,
    CAST(s1.service_time AS DATE) AS date_key,
    CAST(extract(hour FROM s1.service_time) AS INTEGER) AS hour_key,
    s1.arrival_planned_time,
    s1.arrival_change_time,
    s1.departure_planned_time,
    s1.departure_change_time,
    s1.delay_in_min,
    s1.arrival_is_canceled,
    s1.departure_is_canceled,
    s1.arrival_is_canceled OR s1.departure_is_canceled AS is_cancelled,
    s1.is_replacement_train,
    s1.is_junk,
    s1.is_rail_service
FROM {{ ref('int_s1_classified') }} AS s1
CROSS JOIN source_window
WHERE s1.service_time IS NULL
   OR CAST(date_trunc('month', s1.service_time) AS DATE)
      BETWEEN source_window.first_month AND source_window.last_month