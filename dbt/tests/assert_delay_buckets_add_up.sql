-- Fails if the delay buckets do not account for every arrival.
SELECT federal_state, service_month, train_group
FROM {{ ref('agg_state_month_type') }}
WHERE on_time_arrival_count + delay_6_15_count + delay_16_30_count + delay_31_60_count
      + delay_over_60_count <> arrival_count
