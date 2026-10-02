{{ config(materialized='table') }}

SELECT DISTINCT
    concat_ws('|', train_group, coalesce(line_number, '(unknown)')) AS line_key,
    line_number AS line_name,
    train_group AS train_type_key
FROM {{ ref('int_s1_classified') }}