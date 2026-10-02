-- Warns when a train type missing from the train_type_map seed becomes common: likely a new
-- operator that should be classified. Rare junk values (".", "RE 4") stay below the threshold.
{{ config(severity='warn') }}

SELECT raw_train_type, count(*) AS stops
FROM {{ ref('fct_stop_event') }}
WHERE train_type_key = '(unmapped)'
GROUP BY 1
HAVING count(*) > 1000
