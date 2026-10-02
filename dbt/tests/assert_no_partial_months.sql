-- Fails on near-empty months, e.g. an edge month built only from stray rows of a
-- neighbouring source file.
WITH monthly AS (
    SELECT service_month, sum(planned_stop_count) AS stops
    FROM {{ ref('agg_state_month_type') }}
    GROUP BY 1
)
SELECT service_month, stops
FROM monthly
WHERE stops < 0.5 * (SELECT median(stops) FROM monthly)
