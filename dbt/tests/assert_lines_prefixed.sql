-- Fails if S-Bahn, RE or RB lines appear as bare numbers ("1", "7") next to "S1" / "RE7".
SELECT train_group, line_number, count(*) AS stops
FROM {{ ref('fct_stop_event') }}
WHERE train_group IN ('S', 'RE', 'RB')
  AND regexp_full_match(line_number, '[0-9]+')
GROUP BY 1, 2
