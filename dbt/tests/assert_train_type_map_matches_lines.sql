-- Warns when the train_type_map seed files a code under a group that its trains' line names
-- mostly contradict, as TLX (trilex express, lines RE1/RE2) once sat under IC/EC. Stops with a
-- line name are grouped by it anyway (int_s1_classified); this keeps the fallback for stops
-- without one honest, and flags new operators classified by guesswork.
{{ config(severity='warn') }}

WITH labelled AS (
    SELECT
        train_type,
        code_train_group,
        regexp_extract(line_number, '^(RE|RB|S)[0-9]', 1) AS line_group
    FROM {{ ref('int_s1_classified') }}
    WHERE NOT is_junk
      AND code_train_group IN ('IC/EC', 'RE', 'RB', 'S')
      AND regexp_matches(line_number, '^(RE|RB|S)[0-9]')
)
SELECT
    train_type,
    code_train_group,
    mode(line_group) AS usual_line_group,
    count(*) AS labelled_stops,
    round(avg((line_group <> code_train_group)::INTEGER), 3) AS share_disagreeing
FROM labelled
GROUP BY 1, 2
HAVING count(*) >= 1000 AND avg((line_group <> code_train_group)::INTEGER) >= 0.9
