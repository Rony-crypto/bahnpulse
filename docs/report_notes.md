# Report notes

Notes that used to sit on the dashboard as captions and footer text. They belong in the
report's method and limitations sections rather than on the live page.

## Definitions

- **On time** means an arrival less than 6 minutes late (DB definition).
- **Headline on-time share** leaves cancelled arrivals out, as DB does. The delay breakdown
  (donut and bars) counts cancelled arrivals in its base, so its "on time" share is a little
  lower than the headline figure.
- **Average arrival delay** is weighted by arrival volume across states, months and train types.
- **Cancelled arrivals** are planned arrivals that were cancelled, as a share of all planned
  arrivals (cancelled plus those that ran). This is the same base as the on-time share, so
  on time, late and cancelled add up to 100%. Germany and Hamburg use the same definition.
  The section below explains why arrivals are counted rather than stops.
- The cancellation charts leave out the mixed "Other" group (specials and replacement
  services). Its rate is far higher than the main train types and would squash the scale.
- In the Hamburg cancellation ranking, items with fewer than 100 planned arrivals are left
  out, and a week needs at least 20 planned arrivals before it can be named the worst week.

## Why cancellations are counted on arrivals

A train usually arrives at a station and then departs again. The data flags each half
separately, so a stop can be cancelled in two ways:

- **Fully cancelled:** both the arrival and the departure are cancelled. The train does not
  call at the station at all.
- **Partially cancelled:** only one half is cancelled. A train that ends its trip early here
  has its departure cancelled. A train that starts here instead of further back has its
  arrival cancelled.

Every piece of a trip (say Hamburg → Kiel) has two ends: a departure and an arrival. Three
ways to count were compared:

| Method | Problem |
| --- | --- |
| Stop cancelled if arrival **or** departure cancelled | Counts one lost piece twice: at Hamburg (departure) and at Kiel (arrival). It also counts Hamburg when a train ends there early, although passengers still arrived. Too high. |
| Only **fully** cancelled stops | Misses a train that starts at Hamburg instead of Hannover: Hamburg's departure runs, so the stop is not counted, yet passengers from Hannover never arrived. Too low. |
| **Cancelled arrivals** (used) | Each lost piece has exactly one arrival, so it is counted once, at the station that lost the train. |

The simple rule behind the dashboard: at every station, ask "did the train arrive as
planned?" The choice changes rates by only 0.2 to 1.1 points and leaves the order of train
types almost unchanged, but it gives the most accurate picture. For Hamburg ICE the old "arrival
or departure" method gave 8.0%; counting arrivals gives 7.4%.

## Hamburg ICE cancellations

Hamburg's ICE cancellation rate (7.4%) is above Germany's (6.0%). The breakdown shows why:

- **One bad month:** January 2026 reached 17.0%. Every other month was between 3.2% and
  10.0%. Without January, Hamburg is at 6.2%, almost the national rate. The data does not
  say what caused the spike, so check January 2026 reports before naming a cause.
- **Similar to other hubs:** Berlin and Nordrhein-Westfalen are both at 6.7%, so Hamburg is
  only slightly higher than other large ICE hubs. Hessen (5.9%) and Bayern (4.8%) are lower.
- **By station:** Hamburg-Altona 10.8%, Dammtor 8.4%, Hbf 7.7%, Harburg 5.2%. Altona is the
  end of many ICE routes, so trains that turn back early at Hbf show up as cancelled
  arrivals there.

## Comparing states

States are compared within the same train type. A state with many S-Bahn trains is not
comparable with one served mostly by long-distance trains, so mixing train types in the
filter weakens the state comparison.

In the monthly trend, the shaded band is the range between the lowest and highest state for
that month. States with fewer than 500 arrivals in a month are left out of the band, because
small counts swing widely.

## Known data gaps

Found with the `agg_month_coverage` mart. A month is flagged when it has 24 or more low-data
hours (about one day missing).

- **Nov 2025:** 1–2 Nov only covers the largest stations.
- **Jul 2026:** overnight data is missing on 7 nights, about 3% of the month's stops.

A dip in these months should not be read as a real change in punctuality. In the dashboard,
the trend tooltip marks them as incomplete months.

## Pipeline

- History runs through the latest monthly S1 release. Each run's time and dbt test count are
  recorded in `data/published/run_status.json`.
- All marts are built and tested with dbt before they are exported (see `dbt/models/schema.yml`
  and `dbt/tests/`).

## Sources and licences

- Train data: Deutsche Bahn and piebro, CC BY 4.0
- State boundaries: Natural Earth, public domain
