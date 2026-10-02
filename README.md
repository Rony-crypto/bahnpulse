# BahnPulse: Deutsche Bahn punctuality platform

Germany-wide Deutsche Bahn punctuality: monthly history for all stations, a 15-minute collector
for ~35 hubs, a tested dbt model, a public Streamlit app with a state map and a Hamburg deep dive,
and an AI layer that answers questions in English or German with validated SQL.

> Current slice: tested historical marts and a local Streamlit dashboard. See the roadmap below
> for collector and AI milestones.

## Questions this project answers

1. How punctual is each federal state, station and train type (ICE, IC/EC, RE, RB, S-Bahn)?
2. Where do delays start and how do they spread?
3. How likely is a given connection at a major hub to fail?

## Architecture (planned)

```
S1 history (monthly) ──────┐
S3 station data ───────────┼─> raw storage ─> dbt: staging -> merge -> star schema + tests
S2 hub collector (15 min) ─┘                       │
S4 state shapes (dbt seed) ────────────────────────┤
                                                   ▼
                    public marts ─┬─> Streamlit app (map, Hamburg, live hubs, ask the data)
                                  └─> Power BI (history)
```

## Quick start

```bash
git clone https://github.com/<your-user>/bahnpulse.git
cd bahnpulse
uv sync
cp .env.example .env   # add your DB API Marketplace keys
uv run python -m dbp.ingest.download_s1 --start 2025-11 --end latest
uv run python -m dbp.ingest.download_s3
uv run python -m dbp.profile.profile_s1
uv run dbt build --project-dir dbt --profiles-dir dbt
uv run python -m dbp.publish.export_marts
uv run streamlit run src/dbp/app.py
```

Other week-1 scripts:

| Command | What it does |
| --- | --- |
| `uv run python -m dbp.ingest.stada_probe "Hamburg Hbf"` | Checks which station fields StaDa returns (federal state, coordinates) |
| `uv run python -m dbp.ingest.download_s3` | Downloads StaDa station data and builds the EVA-to-state lookup |
| `uv run python -m dbp.ingest.find_eva --write` | Looks up EVA numbers for the hubs in `config/hubs.yml` |
| `uv run dbt build --project-dir dbt --profiles-dir dbt` | Builds and tests local DuckDB models and aggregate marts |
| `uv run python -m dbp.publish.export_marts` | Exports aggregate Parquet marts and freshness metadata |
| `uv run streamlit run src/dbp/app.py` | Launches the historical dashboard at `http://localhost:8501` |
| `uv run pytest` | Runs the unit tests |

## Roadmap

| Week | Dates (2026) | Milestone |
| --- | --- | --- |
| 1 | 5–11 Oct | Data foundation: download, profiling, station → state mapping |
| 2 | 12–18 Oct | Tested dbt model; collector starts |
| 3 | 19–25 Oct | Public Streamlit app v1 |
| 4 | 26 Oct – 1 Nov | AI v1: ask the data + evaluation |
| 5 | 2–8 Nov | Near-real-time hub layer |
| 6 | 9–15 Nov | AI summary, polish, v1.0 |

## Data coverage and known gaps

History covers Nov 2025 to the latest month published by the source (currently Sep 2026); the
`monthly_history` workflow checks daily and adds each new month automatically. Two months are
incomplete, found by the dbt mart `agg_month_coverage` (hours with under half the usual stop volume
for that weekday and hour):

- **Nov 2025:** 1–2 Nov cover only the ~100 largest stations; all stations from 2 Nov onwards.
- **Jul 2026:** overnight hours (00:00–05:00) on 7 nights (4, 7–9, 21–23 Jul) were not collected by the
  source, about 3% of the month's stops. Monthly figures barely change, but the dashboard marks
  both months as "partial data".


- Historical stop data: [piebro/deutsche-bahn-data](https://huggingface.co/datasets/piebro/deutsche-bahn-data),
  CC BY 4.0, based on Deutsche Bahn Timetables API data.
- Live data and station data: [DB API Marketplace](https://developers.deutschebahn.com/db-api-marketplace)
  (Timetables, StaDa), CC BY 4.0, Deutsche Bahn AG.
- State boundaries: Natural Earth admin-1, public domain; Germany-only extract in
  `config/germany_states.geojson`. Source: [Natural Earth](https://www.naturalearthdata.com/).
- No personal data is collected or stored.

Related public work this project builds on or differs from: Bahnvorhersage, db-punctuality by
Surebuckle71, nrw-connection-risk. This project adds S-Bahn and regional coverage, a batch +
near-real-time merge, state-level comparison by train type, tests/CI and an evaluated AI layer.

## Licence

Code: MIT. Data: see credits above.
