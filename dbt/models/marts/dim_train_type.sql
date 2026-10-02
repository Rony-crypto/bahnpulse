{{ config(materialized='table') }}

SELECT
    train_type AS train_type_key,
    train_type AS raw_type,
    train_group,
    train_group IN ('ICE', 'IC/EC') AS is_long_distance
FROM {{ ref('train_type_map') }}
UNION ALL
SELECT '(blank/unknown)', '(blank/unknown)', 'Other', false
UNION ALL
SELECT '(unmapped)', '(unmapped)', 'Other', false