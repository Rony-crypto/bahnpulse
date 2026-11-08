# What the numbers mean

Plain-language explanations of every measure in BahnPulse. The exact calculations are in the
code; the file behind each section is named at its end.

All percentages are worked out from totals (add up all trains first, then divide), so a busy
station counts more than a quiet one.

## The basics

- **Stop:** one train at one station on one day. The data has one record per stop.
- **Planned stop:** a stop in the timetable, whether the train came or not.
- **Month / hour:** when the train was *scheduled* to be there, not when it actually came.
- **Federal state:** the state the station is in.
- **Left out:** records with missing information (no train type, number or delay) and rail
  replacement buses. They are not in any figure.

*Code: `dbt/models/staging/stg_s1.sql`, `dbt/models/marts/fct_stop_event.sql`*

## Train types

- **ICE:** DB's high-speed long-distance trains.
- **IC/EC:** the other long-distance trains (InterCity, EuroCity).
- **RE:** Regional Express, faster regional trains with fewer stops.
- **RB:** Regionalbahn, regional trains that stop everywhere.
- **S:** S-Bahn, suburban trains in and around cities.
- **Other:** special trains that fit none of the groups.
- **Long-distance:** ICE + IC/EC. **Regional:** RE + RB.

A train's type comes from its line name (RE1, RB26, S3) when it has one, because one operator
often runs both RE and RB lines under the same code.

*Code: `dbt/models/intermediate/int_s1_classified.sql`*

## Punctuality

- **Arrival delay:** how many minutes after its scheduled time a train arrives. An early train
  counts as 0 minutes late.
- **On time:** a train that arrives less than 6 minutes late. This is DB's own definition, so a
  train 5 minutes late is still "on time".
- **On-time arrivals (%):** out of all trains that arrived, the share that were on time.
- **Average arrival delay:** how late a train is when it arrives, all its lateness so far,
  averaged over all arrivals.
- **Delay bands:** arrivals grouped by how late they were: on time, 6–15, 16–30, 31–60 and over
  60 minutes late.

> Example: three trains arrive 0, 4 and 11 minutes late. Two of three are on time (67%); the
> average arrival delay is (0 + 4 + 11) ÷ 3 = 5 minutes.

*Code: `dbt/models/marts/agg_state_month_type.sql`*

## Cancellations

- **Cancelled arrival:** a train that was scheduled to arrive at a station but did not.
- **Cancelled arrivals (%):** out of all scheduled arrivals, the share that were cancelled.

Each lost train is counted once, at the station it no longer reached.

## Where delays start

These measures follow each train along its whole route.

- **Trip:** one train's journey from its first station to its last on one day.
- **Complete trip:** a trip the data covers from its very first to its very last station, with
  no stop missing. Only complete trips are used below, so nothing is guessed.
- **Ends late:** a trip that reached its last station 6 or more minutes late.
- **Delay at the first station:** how late the train already was when it set off.
- **Delay added between stations (running):** extra lateness picked up while travelling from one
  station to the next.
- **Delay added at stations (dwell):** extra lateness picked up while standing at a platform,
  for example during boarding or while waiting for a free track.
- **Recovered:** lateness the train wins back, usually through spare time built into the
  timetable.
- **Delay split:** a late train's final lateness broken down into where it came from: delay at
  the first station + delay added between stations + delay added at stations, minus what it
  won back. The parts always add up to the final lateness.
- **Delay added per stop:** how much extra lateness a train picks up at each stop: on the way in
  from the previous station, plus while standing at this one. Unlike average arrival delay, it
  leaves out lateness the train brought from elsewhere, so it shows where delay is created.
- **Delay start:** the station where a train first becomes 6 or more minutes late.
- **Route position:** how far along its journey a train is: 0% at the first station, 100% at
  the last.
- **Top 5% of stations:** the 5% of stations that add the most delay. Their share of all delay
  shows how much a few busy hubs matter.

> Example: a train leaves the previous station 4 minutes late and arrives in Hamburg 5 minutes
> late. It stands a minute too long and leaves 6 minutes late. For **average arrival delay** it
> counts as 5 minutes. For **delay added per stop** at Hamburg it counts as 2 minutes: 1 on the
> way in, plus 1 standing.

*Code: `src/dbp/transform/delay_spread.py`*

## Time views

- **Hour:** the scheduled hour of the stop (0–23).
- **Weekday:** Monday to Sunday.
- **Week (Hamburg page):** Monday to Sunday; only full weeks are shown.
- **Weekday peak (Hamburg page):** Monday to Friday, 6–9 am and 4–7 pm, when commuters travel.
- **Off-peak (Hamburg page):** all other times, including weekends.

## Data quality

- **Low-data hour:** an hour where the source collected less than half the usual number of
  trains, a sign it missed data rather than trains not running.
- **Incomplete month:** a month with about a day or more of low-data hours. The dashboard marks
  these months (Nov 2025 and Jul 2026 so far).

*Code: `dbt/models/marts/agg_month_coverage.sql`*

## Dashboard rules

- **Station rankings:** only stations with at least 100 trains in the chosen period, so a tiny
  station cannot top a list by chance.
- **vs Germany:** how the chosen state compares with all of Germany for the same train types
  and months.

## Ask AI chat

- **How it answers:** the AI writes a database query, the database works out the numbers, and
  the AI puts the result into words. The AI never calculates numbers itself.
- **Declined:** the AI says the data cannot answer the question (causes, weather, prices, the
  future, other countries).
- **No train type or month in the question:** the answer covers all months and all train types
  except replacement buses and "Other".
- **Correct (evaluation):** the AI's answer matches a hand-written reference answer.
- **Hold-out questions:** test questions written after the AI's instructions were finished and
  never used to improve them, so their score is the fair one.

*Code: `src/dbp/ask/`; results: `docs/ask_eval.md`*
