{{ config(materialized='table') }}

-- train_group here is the code's fallback group from the seed. A stop's own group can differ:
-- when the train carries a line name (RE1, RB26, S3), that decides (see int_s1_classified).
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