{{ config(materialized='view') }}

-- Train group per stop. The raw train_type is often an operator code (HLB, VIA, vlx), and one
-- operator runs both RE and RB lines, so a group per code misclassified about a third of
-- regional stops (and filed trilex express RE1/RE2 under IC/EC). The line name says which
-- service a train is (RE1, RB26, S3): when it carries one, it decides the group; otherwise the
-- code mapping does (ICE, IC, EC and trains without a line name). Rail replacement buses keep
-- their Bus group even when they carry the replaced line's name.
WITH classified AS (
    SELECT
        s1.*,
        coalesce(type_map.train_group, 'Other') AS code_train_group,
        type_map.train_type IS NOT NULL AS is_mapped_type,
        nullif(regexp_extract(s1.line_number, '^(RE|RB|S)[0-9]', 1), '') AS line_train_group
    FROM {{ ref('stg_s1') }} AS s1
    LEFT JOIN {{ ref('train_type_map') }} AS type_map
        ON s1.train_type = type_map.train_type
),
grouped AS (
    SELECT
        *,
        CASE
            WHEN code_train_group IN ('IC/EC', 'RE', 'RB', 'S') AND line_train_group IS NOT NULL
                THEN line_train_group
            ELSE code_train_group
        END AS train_group
    FROM classified
)
SELECT
    -- From mid-December 2025 the source writes S-Bahn lines as "S1" instead of "1"; some RE/RB
    -- lines also appear as bare numbers ("7" for RE7). Add the prefix so each line has one name.
    * EXCLUDE (line_train_group) REPLACE (
        CASE
            WHEN train_group IN ('S', 'RE', 'RB') AND regexp_full_match(line_number, '[0-9]+')
                THEN train_group || line_number
            ELSE line_number
        END AS line_number
    ),
    line_train_group IS NOT NULL AND code_train_group IN ('IC/EC', 'RE', 'RB', 'S')
        AS is_grouped_by_line,
    train_type IS NULL OR train_number IS NULL OR delay_in_min IS NULL AS is_junk,
    train_group <> 'Bus' AS is_rail_service
FROM grouped
