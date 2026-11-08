# Definitions

Every measure, filter and term used in BahnPulse, as the code computes it. Where a definition
lives in code, the file is named so it can be checked.

All rates are computed from summed counts (sum first, then divide), never by averaging
percentages, so a busy station or state weighs more than a quiet one.

## Data basics

| Term | Definition |
| --- | --- |
| **Stop event** | One train at one station on one day: one row of the source data (S1). It has a planned and actual arrival and/or departure time. |
| **Planned stop** | Every stop event in the timetable, whether it ran or was cancelled. |
| **Service time** | The planned arrival time, or the planned departure time at a train's first station. Months, weeks, days and hours are all assigned by this time. |
| **Month** | Calendar month of the service time. A trip running past midnight at the end of a month is split between the two months. |
| **Federal state** | The state of the station, from DB's station data (S3, StaDa). |
| **Excluded records** | Rows without a train type, train number or delay value (`is_junk`), and rail replacement buses (`Bus`). Both are left out of every figure. |

Source: `dbt/models/staging/stg_s1.sql`, `dbt/models/intermediate/int_s1_classified.sql`,
`dbt/models/marts/fct_stop_event.sql`.

## Train types

| Group | Meaning |
| --- | --- |
| **ICE** | InterCity Express (long-distance high-speed). |
| **IC/EC** | InterCity and EuroCity (other long-distance trains). |
| **RE** | Regional Express. |
| **RB** | Regional train (Regionalbahn). |
| **S** | S-Bahn (suburban rail). |
| **Other** | Special trains and services that fit no group. Shown in some views, left out of comparisons where it would distort the scale. |
| **Long-distance** | ICE + IC/EC. |
| **Regional** | RE + RB. |

A train's group comes from its **line name** when it has one (RE1, RB26, S3), otherwise from
its train type code (ICE, IC, EC). Operator codes alone are not used, because one operator
often runs both RE and RB lines. Source: `int_s1_classified.sql`, seed `train_type_map`.

## Punctuality

| Measure | Definition |
| --- | --- |
| **Arrival delay** | Actual arrival time minus planned arrival time, in whole minutes. Negative = early. Derived from the timestamps, because the source's own delay field is the departure delay at every stop but the last. |
| **Arrival (that ran)** | A planned arrival that was not cancelled and has a known delay. The base for all punctuality measures. |
| **On time** | An arrival less than 6 minutes late (0:00 to 5:59), DB's own definition. Early arrivals count as on time. |
| **On-time arrivals (%)** | On-time arrivals ÷ arrivals that ran × 100. |
| **Average arrival delay (min)** | Mean arrival delay of arrivals that ran, with early arrivals counted as 0 minutes late. So it is the average *lateness*, not reduced by early trains. |
| **Delay bands** | Arrivals that ran, split by lateness: on time (under 6 min), 6–15, 16–30, 31–60 and over 60 minutes late. The bands add up to all arrivals that ran. |

Source: `dbt/models/marts/agg_state_month_type.sql` (same definitions in the station, hour
and Hamburg marts).

## Cancellations

| Measure | Definition |
| --- | --- |
| **Cancelled arrival** | A planned arrival marked as cancelled. |
| **Cancelled arrivals (%)** | Cancelled arrivals ÷ (arrivals that ran + cancelled arrivals) × 100, so the base is all planned arrivals. |

Counting on arrivals counts each lost train once, at the station it no longer reached.
Counting "arrival or departure cancelled" would count a cut-short trip twice.

## Where delays start (trip-level measures)

The source has no trip id, so trips are rebuilt (`src/dbp/transform/delay_spread.py`).

| Term | Definition |
| --- | --- |
| **Trip** | The stops of one ride id in time order, until the stop number restarts or the plan jumps by more than 6 hours (the same ride id repeats every day a train runs). |
| **Lateness** | Delay floored at 0: an early arrival counts as 0 minutes late. |
| **Complete trip** | A trip seen from its true first station to its true last station: starts at stop 1, has no missing stop, has at least 3 stops, only its first stop lacks a planned arrival and only its last stop lacks a planned departure, and every planned arrival and departure ran with a known delay. Only complete trips are used for the delay split. |
| **Ends late** | A complete trip that reached its last station 6 or more minutes late. |
| **Origin lateness** | How late the trip left its first station. |
| **Running gain** | Lateness on arrival at a stop minus lateness on departure from the previous stop: delay gained (or won back) between stations. Only counted between consecutive stops. |
| **Dwell gain** | Lateness on departure minus lateness on arrival at the same stop: delay gained (or won back) while standing at a station. |
| **Added / recovered** | Positive gains are "added", negative gains are "recovered" (timetable buffers winning time back). |
| **Delay split** | For every complete trip: final lateness = origin lateness + running added + running recovered + dwell added + dwell recovered. A dbt test checks this adds up for every month and train type. |
| **Share of delay from a source** | For trips that end late: origin, running added or dwell added minutes ÷ (origin + running added + dwell added) minutes. Recovered minutes are left out of the base. |
| **Delay added per stop** | (Running added + dwell added) minutes ÷ measured stops, for the stations in the selected area. The lateness a train picks up per stop there. Unlike average arrival delay it leaves out lateness brought in from elsewhere, so it shows where delay is created. Recovered minutes are not subtracted. |
| **Measured stop** | A stop where a running or dwell gain could be measured. |
| **Delay start** | A stop where a train first becomes 6+ minutes late: it was under 6 minutes late on leaving the previous stop and 6+ late on arrival, or under 6 on arrival and 6+ on departure. |
| **Route position** | How far along its route a stop is: 0% = first station, 100% = last station, in steps of 10%. Used only for complete trips with 5 or more stops. |
| **Top 5% of stations** | Stations ranked by delay minutes added; the top 5% by count. Their share of all stops and of all delay added shows how concentrated delay is. |

Source: `src/dbp/transform/delay_spread.py`, marts `agg_delay_sources`,
`agg_station_delay_gain`, `agg_delay_along_route`, test `assert_delay_sources_add_up`.

## Time views

| Term | Definition |
| --- | --- |
| **Hour** | Hour (0–23) of the service time. |
| **Weekday** | ISO weekday of the service time, 1 = Monday to 7 = Sunday. |
| **Week (Hamburg)** | Monday-to-Sunday week. Only complete weeks inside the data are shown. |
| **Weekday peak (Hamburg)** | Monday to Friday, 06:00–08:59 and 16:00–18:59 (service time). |
| **Off-peak (Hamburg)** | Every other hour, including all weekend hours. |

## Data quality

| Term | Definition |
| --- | --- |
| **Low-data hour** | An hour with under half the usual number of stops, compared with the median for the same weekday and hour in that month. Marks hours the source failed to collect. |
| **Incomplete month** | A month with 24 or more low-data hours (about a day missing). Flagged on the dashboard; Nov 2025 and Jul 2026 so far. |
| **Volume completeness (%)** | Stops collected ÷ stops expected from the typical hourly volume, per month. |

Source: `dbt/models/marts/agg_month_coverage.sql`.

## Dashboard rules

| Rule | Definition |
| --- | --- |
| **Station rankings** | Only stations with at least 100 arrivals (or 100 measured stops) in the selected period, so a station with a handful of trains cannot top a list by chance. |
| **"vs Germany"** | The selected state's value minus the value for all of Germany, with the same train types and months. |

## Ask AI chat

| Term | Definition |
| --- | --- |
| **Answer** | The model writes one SQL query; the database computes every number; the model then words a short answer from the result rows only. |
| **Unspecified question** | A question naming no month or train type covers all months and all train types except Bus and Other. |
| **Declined** | The model says the data cannot answer (causes, weather, prices, the future, other countries). |
| **Correct (evaluation)** | The model's result matches a hand-written reference query within its rounding (0.1 for one decimal), or names the same station, state, month or hour. |
| **Tuning set** | Test questions used while writing the prompt. |
| **Hold-out set** | Test questions written afterwards and never used to change the prompt; their score is the fair one. |

Source: `src/dbp/ask/`, results in `docs/ask_eval.md`.
