# dbt project

DuckDB-backed dbt project: raw stop history (source `s1`) and station data (source `s3`) →
staging → intermediate → star schema and dashboard marts. Run from the repository root after
downloading S1 and StaDa data:

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

Every model and column is described in `models/schema.yml`; browse them with the lineage graph:

```bash
uv run dbt docs generate --project-dir dbt --profiles-dir dbt
uv run dbt docs serve --project-dir dbt --profiles-dir dbt
```

## S1 modeling contract

- A stop's train group comes from its line name (RE1, RB26, S3) when it has one; otherwise the seed `seeds/train_type_map.csv` maps the raw train/operator code to ICE, IC/EC, RE, RB, S, Bus, or Other. The raw code is kept alongside the group so mappings stay auditable, and `assert_train_type_map_matches_lines` flags codes whose trains contradict their mapping.
- Exclude Bus from rail punctuality. Flag/drop rows where `train_type` is blank; in the profiled files these align exactly with missing `train_number` and `delay_in_min`.
- Use `id` as the stop-row identity. `train_line_ride_id + train_line_station_num` repeats across service dates; adding planned time still has collisions and is not a replacement for `id`.
- Build station state by normalizing S1's eight-character EVA (leading `0`) and joining to DB StaDa data. Six historical S1 EVAs absent from current StaDa use explicit, auditable overrides. Hamburg S-Bahn analysis filters `federalState = Hamburg` and excludes line S0; station-name prefixes are not a valid state filter.
- Treat endpoint nulls in planned arrival/departure as expected. Track change-time-without-planned-time rows separately.
- Collection gaps: `agg_month_coverage` flags hours with under half the usual stop volume for that weekday and hour (24+ such hours mark a month as incomplete); `agg_hourly_coverage` keeps the delay and change-time fill rates per hour.
- `agg_hamburg_weekly` supports historical line, station, and train-type comparisons with weekday peak (06-09, 16-19) versus off-peak buckets; line rows exclude S0.
