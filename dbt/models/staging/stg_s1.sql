{{ config(materialized='view') }}

SELECT
    CAST(id AS VARCHAR) AS stop_record_id,
    CAST(eva AS VARCHAR) AS source_eva,
    CASE
        WHEN length(CAST(eva AS VARCHAR)) = 8 AND starts_with(CAST(eva AS VARCHAR), '08')
            THEN substring(CAST(eva AS VARCHAR), 2)
        ELSE CAST(eva AS VARCHAR)
    END AS eva,
    station_name,
    nullif(trim(CAST(train_number AS VARCHAR)), '') AS train_number,
    nullif(trim(CAST(train_type AS VARCHAR)), '') AS train_type,
    nullif(trim(CAST(line_number AS VARCHAR)), '') AS line_number,
    CAST(delay_in_min AS INTEGER) AS delay_in_min,
    CAST(arrival_planned_time AS TIMESTAMP) AS arrival_planned_time,
    CAST(arrival_change_time AS TIMESTAMP) AS arrival_change_time,
    CAST(departure_planned_time AS TIMESTAMP) AS departure_planned_time,
    CAST(departure_change_time AS TIMESTAMP) AS departure_change_time,
    coalesce(arrival_is_canceled, false) AS arrival_is_canceled,
    coalesce(departure_is_canceled, false) AS departure_is_canceled,
    CAST(is_replacement_train AS BOOLEAN) AS is_replacement_train,
    CAST(train_line_ride_id AS VARCHAR) AS train_line_ride_id,
    CAST(train_line_station_num AS INTEGER) AS train_line_station_num,
    coalesce(
        CAST(arrival_planned_time AS TIMESTAMP),
        CAST(departure_planned_time AS TIMESTAMP)
    ) AS service_time,
    CAST(
        regexp_extract(filename, 'data-(\d{4}-\d{2})\.parquet$', 1) || '-01' AS DATE
    ) AS source_month
FROM read_parquet('{{ var("s1_parquet_glob") }}', filename = true)