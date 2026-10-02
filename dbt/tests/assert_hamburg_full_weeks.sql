-- Fails if a Hamburg week starts before or ends after the event window.
WITH event_window AS (
    SELECT
        min(service_month) AS first_day,
        CAST(max(service_month) + INTERVAL 1 MONTH - INTERVAL 1 DAY AS DATE) AS last_day
    FROM {{ ref('fct_stop_event') }}
)
SELECT DISTINCT weekly.service_week
FROM {{ ref('agg_hamburg_weekly') }} AS weekly
CROSS JOIN event_window
WHERE weekly.service_week < event_window.first_day
   OR weekly.service_week + 6 > event_window.last_day
