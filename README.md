# BahnPulse: Deutsche Bahn punctuality platform

Germany-wide Deutsche Bahn punctuality: monthly history for all stations, a 15-minute collector
for ~35 hubs, a tested dbt model, a public Streamlit app with a state map and a Hamburg deep dive,
and an AI layer that answers questions in English or German with validated SQL.

> Status: **week 1 of 6** (data foundation). Built in public; see the roadmap below.

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
uv run python -m dbp.ingest.download_s1 --start 2026-06 --end 2026-08
uv run python -m dbp.profile.profile_s1
```

Other week-1 scripts:

| Command | What it does |
| --- | --- |
| `uv run python -m dbp.ingest.stada_probe "Hamburg Hbf"` | Checks which station fields StaDa returns (federal state, coordinates) |
| `uv run python -m dbp.ingest.find_eva --write` | Looks up EVA numbers for the hubs in `config/hubs.yml` |
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

## Data and credits

- Historical stop data: [piebro/deutsche-bahn-data](https://huggingface.co/datasets/piebro/deutsche-bahn-data),
  CC BY 4.0, based on Deutsche Bahn Timetables API data.
- Live data and station data: [DB API Marketplace](https://developers.deutschebahn.com/db-api-marketplace)
  (Timetables, StaDa), CC BY 4.0, Deutsche Bahn AG.
- No personal data is collected or stored.

Related public work this project builds on or differs from: Bahnvorhersage, db-punctuality by
Surebuckle71, nrw-connection-risk. This project adds S-Bahn and regional coverage, a batch +
near-real-time merge, state-level comparison by train type, tests/CI and an evaluated AI layer.

## Licence

Code: MIT. Data: see credits above.
