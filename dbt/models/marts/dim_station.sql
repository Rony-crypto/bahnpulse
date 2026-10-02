{{ config(materialized='table') }}

SELECT
    eva AS station_key,
    station_name,
    federal_state,
    try_cast(longitude AS DOUBLE) AS longitude,
    try_cast(latitude AS DOUBLE) AS latitude,
    try_cast(category AS INTEGER) AS category,
    mapping_source
FROM read_csv('{{ var("station_state_map") }}', all_varchar=true)