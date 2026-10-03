# BahnPulse: where Deutsche Bahn delays come from

How punctual are German trains, and where does their delay actually come from? BahnPulse
turns 160 million stop records (Nov 2025 – Sep 2026, every station, every operator) into a
tested dbt model and a public dashboard that compares federal states, train types and
stations, and traces how delay builds up along each journey.

**Live dashboard:** [bahnpulse.streamlit.app](https://bahnpulse.streamlit.app/?embed=true)

## Key findings

1. **Delay builds up along the route.** 82% of ICE trains leave their first station on time,
   but only 45% reach their last station on time.
2. **Long-distance and local trains lose time in different places.** ICE and IC/EC trains pick
   up about 60% of their delay *between* stations; S-Bahn trains pick up half of theirs while
   *standing* at stations.
3. **A few hubs matter most.** The 5% of stations that add the most delay handle 27% of train
   stops but add 35% of all delay minutes (Frankfurt, Hamburg, Köln, Hannover, Stuttgart,
   Duisburg).

Each finding holds in every one of the 11 months. Method, checks and limits are in
[docs/report_notes.md](docs/report_notes.md).

## Questions the dashboard answers

1. How punctual is each federal state, station and train type (ICE, IC/EC, RE, RB, S-Bahn),
   and how many arrivals are cancelled?
2. Where do delays start and how do they spread along the route?
3. When are trains late (hour × weekday), and how does punctuality change month to month?
4. Hamburg deep dive: train types at one station, stations and lines, week by week.

## How it works

```
S1 stop history (monthly Parquet) ─┐
S3 station data (DB StaDa) ────────┼─> dbt on DuckDB: staging -> star schema -> marts + tests
S4 state shapes (Natural Earth) ───┘                         │
                                                             ▼
                          aggregate Parquet marts (data/published) ─> Streamlit dashboard
```

- **dbt + DuckDB:** staging and classification views, a stop-event fact table with station,
  train type, line, date and hour dimensions, and aggregate marts for the dashboard. The
  "where do delays start" marts are dbt Python models that rebuild trips one month at a time
  (`src/dbp/transform/delay_spread.py`).
- **Tests:** 47 dbt data tests (keys, accepted values, full weeks, delay buckets adding up,
  delay sources adding up to the final delay) and Python unit tests (`uv run pytest`).
- **Automation:** the `monthly_history` GitHub workflow checks daily for a new source month,
  rebuilds, tests and publishes the marts.

### Data decisions worth knowing

- **Punctuality uses real arrival times.** The source's `delay_in_min` is the departure delay
  at every stop except the last, so arrival delay is derived from the timestamps (DB measures
  punctuality on arrivals).
- **Cancellations are counted on planned arrivals,** so each lost train is counted once, at
  the station it no longer reached. Counting "arrival or departure cancelled" counts a
  cut-short trip twice; counting only fully cancelled stops misses trains that start late on
  their route.
- **Trips are rebuilt from stop events,** because the source has no trip id. Only trips from
  their true first to their true last station are used to split delay, and the split is
  checked to account for every minute.

## Quick start

```bash
git clone https://github.com/Rony-crypto/bahnpulse.git
cd bahnpulse
uv sync
cp .env.example .env   # DB API Marketplace keys (for station data)
uv run python -m dbp.ingest.download_s1 --start 2025-11 --end latest
uv run python -m dbp.ingest.download_s3
uv run dbt build --project-dir dbt --profiles-dir dbt
uv run python -m dbp.publish.export_marts
uv run streamlit run src/dbp/bahnpulse_app.py
```

The dbt build caps DuckDB at 4 GB of memory (set `BAHNPULSE_DUCKDB_MEMORY` to change it) and
takes about 4 minutes on a laptop.

| Command | What it does |
| --- | --- |
| `uv run python -m dbp.profile.profile_s1` | Profiles the raw stop data (nulls, keys, quirks) |
| `uv run python -m dbp.ingest.stada_probe "Hamburg Hbf"` | Checks which station fields StaDa returns |
| `uv run python -m dbp.ingest.find_eva --write` | Looks up station numbers for `config/hubs.yml` |
| `uv run pytest` | Runs the unit tests |

## Data coverage and known gaps

History covers Nov 2025 to the latest month the source has published (currently Sep 2026).
Two months are incomplete, found by the dbt mart `agg_month_coverage` (hours with under half
the usual stop volume):

- **Nov 2025:** 1–2 Nov cover only the ~100 largest stations; all stations from 2 Nov.
- **Jul 2026:** overnight hours (00:00–05:00) on 7 nights were not collected, about 3% of the
  month's stops. Monthly figures barely change; the trend tooltip marks both months.

## Roadmap

| Status | Milestone |
| --- | --- |
| Done | Data foundation: download, profiling, station → state mapping |
| Done | Tested dbt model and monthly automation |
| Done | Public dashboard: states, train types, cancellations, Hamburg deep dive |
| Done | Where delays start and how they spread |
| Next | "Ask the data": questions in English or German answered with validated SQL |
| Later | Live hub layer (collector tested; see the report notes for findings) |

## Credits and licences

- Historical stop data: [piebro/deutsche-bahn-data](https://huggingface.co/datasets/piebro/deutsche-bahn-data),
  CC BY 4.0, based on Deutsche Bahn Timetables API data.
- Station data: [DB API Marketplace](https://developers.deutschebahn.com/db-api-marketplace)
  (StaDa, Timetables), CC BY 4.0, Deutsche Bahn AG.
- State boundaries: [Natural Earth](https://www.naturalearthdata.com/) admin-1, public domain;
  Germany-only extract in `config/germany_states.geojson`.
- No personal data is collected or stored.

Code: MIT. Data: see credits above.
