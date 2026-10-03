# dbt project

DuckDB-backed dbt project implementing the first S1 history slice from the TRD. Run from the
repository root after downloading S1 and StaDa data:

```bash
uv run dbt build --project-dir dbt --profiles-dir dbt
uv run python -m dbp.publish.export_marts
uv run streamlit run src/dbp/bahnpulse_app.py
```

The default DuckDB database is `data/bahnpulse.duckdb`; override it with
`BAHNPULSE_DUCKDB_PATH`. S1 Parquet and the generated StaDa lookup paths can also be overridden
with dbt vars in `dbt_project.yml`.

Layers: `staging` (views) -> `intermediate` (classification) -> `marts` (facts, dimensions,
aggregates).

## S1 modeling contract

- Seed `seeds/train_type_map.csv` to map raw train/operator codes to ICE, IC/EC, RE, RB, S, Bus, or Other. Keep the raw code alongside the group so mappings remain auditable.
- Exclude Bus from rail punctuality. Flag/drop rows where `train_type` is blank; in the profiled files these align exactly with missing `train_number` and `delay_in_min`.
- Use `id` as the stop-row identity. `train_line_ride_id + train_line_station_num` repeats across service dates; adding planned time still has collisions and is not a replacement for `id`.
- Build station state by normalizing S1's eight-character EVA (leading `0`) and joining to DB StaDa data. Six historical S1 EVAs absent from current StaDa use explicit, auditable overrides. Hamburg S-Bahn analysis filters `federalState = Hamburg` and excludes line S0; station-name prefixes are not a valid state filter.
- Treat endpoint nulls in planned arrival/departure as expected. Track change-time-without-planned-time rows separately.
- Detect collection gaps from hourly delay/change-time fill rates, not missing planned-stop hours. The profiler currently flags hours below half the monthly median coverage for investigation.
- `agg_hamburg_weekly` supports historical line, station, and train-type comparisons with weekday peak (06-09, 16-19) versus off-peak buckets; line rows exclude S0.
