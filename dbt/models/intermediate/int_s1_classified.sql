{{ config(materialized='view') }}

SELECT
    -- From mid-December 2025 the source writes S-Bahn lines as "S1" instead of "1"; some RE/RB
    -- lines also appear as bare numbers ("7" for RE7). Add the prefix so each line has one name.
    s1.* REPLACE (
        CASE
            WHEN type_map.train_group IN ('S', 'RE', 'RB')
                 AND regexp_full_match(s1.line_number, '[0-9]+')
                THEN type_map.train_group || s1.line_number
            ELSE s1.line_number
        END AS line_number
    ),
    coalesce(type_map.train_group, 'Other') AS train_group,
    type_map.train_type IS NOT NULL AS is_mapped_type,
    s1.train_type IS NULL OR s1.train_number IS NULL OR s1.delay_in_min IS NULL AS is_junk,
    coalesce(type_map.train_group, 'Other') <> 'Bus' AS is_rail_service
FROM {{ ref('stg_s1') }} AS s1
LEFT JOIN {{ ref('train_type_map') }} AS type_map
    ON s1.train_type = type_map.train_type