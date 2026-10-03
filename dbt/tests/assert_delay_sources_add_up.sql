-- Fails if origin + running + dwell lateness does not add up to the final lateness: the split
-- in agg_delay_sources must account for every minute.
SELECT service_month, train_group, ends_late
FROM {{ ref('agg_delay_sources') }}
WHERE abs(
    origin_late_min + running_added_min + running_recovered_min
    + dwell_added_min + dwell_recovered_min - final_late_min
) > 0.5
