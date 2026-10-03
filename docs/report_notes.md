# Report notes

Method, findings and limitations behind the dashboard, for the report. Figures cover
Nov 2025 – Sep 2026 unless stated otherwise.

## The story in one minute

Punctuality numbers say *how* late German trains are; they do not say *where the delay comes
from*, which is what you need to know to fix it. I rebuilt every train journey from 160
million stop records and split each late train's delay into three parts: delay it already had
at its first station, delay added while running between stations, and delay added while
standing at stations. Three findings stand out, and each held in all 11 months:

1. **Delay builds up along the route.** Most trains start on time (82% of ICE leave their
   first station on time), but fewer than half of ICE (45%) reach their last station on
   time.
2. **Long-distance and local trains lose time in different places.** ICE and IC/EC trains
   pick up about 60% of their delay *between* stations (the line itself: capacity, speed
   restrictions, conflicts); S-Bahn trains pick up half of theirs while *standing* at
   stations (boarding, dwell times, waiting for a free path).
3. **A few hubs matter most.** The 5% of stations that add the most delay handle 27% of train
   stops but add 35% of all delay minutes, led by Frankfurt, Hamburg, Köln, Hannover,
   Stuttgart and Duisburg.

So the problem is not that trains leave late; it is how much delay the network adds once
they are running, concentrated at a small number of nodes.

## Where delays start and how they spread

### Question

Where in a journey does lateness arise (at the first station, between stations or at
stations), how does it develop along the route, and which stations add the most?

### Method

1. **Rebuild trips.** The source has no trip id: `train_line_ride_id` repeats on every day a
   train runs. A trip is one ride id's stops in time order until the stop number restarts or
   the timetable jumps by more than 6 hours.
2. **Measure lateness, not delay.** Lateness is delay floored at 0, so an early arrival
   followed by an on-time departure is not counted as delay gained at the station.
3. **Split each stop's change.** For stop *k*: *running gain* = arrival lateness at *k* minus
   departure lateness at *k − 1* (only between consecutive stops), and *dwell gain* =
   departure lateness at *k* minus arrival lateness at *k*. Positive values add delay;
   negative values are recovered by timetable buffers.
4. **Complete trips only for the split.** A trip counts when it runs from its true first
   station (no planned arrival) to its true last station (no planned departure), with no
   missing stop, no cancellation and every delay recorded: 9.1 million trips in total.
5. **Exact accounting.** For every complete trip, final lateness = lateness at the first
   station + running added + running recovered + dwell added + dwell recovered. A dbt test
   (`assert_delay_sources_add_up`) checks this every build.

### Checks that shaped the method

- **Trip reconstruction:** in May 2026, 1.29 million trips; 93.5% have no missing stop and
  none has a duplicate stop number.
- **Trains that run on beyond the data:** some trips end in the data at a stop that still has
  a departure (the train continues abroad or to stops the source missed). They first broke
  the identity test for about 3% of complete trips; requiring a true first and last station
  fixed it (0 of 826,835 May trips off by even a minute).
- **Processing month by month:** rebuilding trips over the whole history at once spilled
  40 GB to disk. Each month is now rebuilt and aggregated on its own (about 5 seconds).
  Trips running over midnight at a month end are split, a negligible share.
- **Memory:** on a 16 GB laptop DuckDB's default (80% of RAM) pushed the machine into swap
  and one month took 305 seconds instead of 5. The dbt profile caps DuckDB at 4 GB
  (10 GB on the GitHub runner).
- **Unit tests** (`tests/test_delay_spread.py`) cover the split, two days of the same ride,
  early arrivals, missing stops, trips cut off before their last station and route position.

### Findings

**Where the delay of late trips comes from** (trips ending 6+ minutes late, share of delay
minutes added):

| Train type | Trips ending late | At the first station | Between stations | At stations |
| --- | --- | --- | --- | --- |
| ICE | 54% | 14% | 60% | 25% |
| IC/EC | 48% | 17% | 61% | 22% |
| RE | 26% | 25% | 39% | 37% |
| RB | 16% | 25% | 31% | 44% |
| S-Bahn | 14% | 19% | 31% | 50% |

Month to month the ICE share between stations stays between 57% and 65%, and the S-Bahn share
at stations between 47% and 55%.

**Recovery:** timetable buffers win back about 30% of the delay added (43% for the S-Bahn),
but not enough to cancel it out.

**Along the route** (share of trains 6+ minutes late):

| Train type | First station | Halfway | Near the end (90%) | Last station |
| --- | --- | --- | --- | --- |
| ICE | 18% | 46% | 57% | 55% |
| IC/EC | 13% | 40% | 52% | 50% |
| RE | 11% | 22% | 28% | 28% |
| S-Bahn | 5% | 11% | 14% | 14% |

The small improvement at the last station is the buffer timetables add before the end of a
line.

**Where delay is added:** 5,377 stations. The top 5% handle 27% of train stops but add 35% of
all delay minutes, so they add more delay per train, not only more trains. Highest totals:
Frankfurt (Main) Hbf, Hamburg Hbf, Köln Hbf, Hannover Hbf, Stuttgart Hbf, Duisburg Hbf.
Per train, Hannover (2.4 min, 76% of it on the way in) and Duisburg (2.1 min) stand out.

### Limits

- **Association, not cause.** The data shows where lateness grows, not why. "At stations"
  includes boarding, but also trains held at a platform waiting for a free path; "between
  stations" includes slow running and signal stops.
- **Credit for running gains goes to the station a train arrives at**, so a slow stretch shows
  up at the next station.
- **Terminal stations show all their added delay "on the way in".** A train ending its trip
  does not depart, so nothing can be added while standing. Hamburg Hbf, where most RE trains
  end, shows 100% on the way in for RE.
- **Complete trips only** for the split (start to end inside Germany, no cancellation).
  Trains to and from abroad are left out of that part, which removes some long-distance
  trips.
- **Not comparable with DB's official figures one to one:** DB publishes punctuality for its
  own operations; this data covers every operator at every station in the source.

## Definitions

- **On time** means an arrival less than 6 minutes late (DB definition). Arrival delay is
  the actual minus the planned arrival time. The source's own `delay_in_min` column is the
  *departure* delay at every stop except the last (it matched departure times on 100% of rows
  and arrival times on only 55%), so it is not used for punctuality. Switching to real arrival
  times raised on-time shares by 0.6 to 2.1 points (ICE 56.1% to 58.1% in May 2026).
- **Headline on-time share** leaves cancelled arrivals out, as DB does. The delay breakdown
  (donut and bars) counts cancelled arrivals in its base, so its "on time" share is a little
  lower than the headline figure.
- **Average arrival delay** counts early arrivals as 0 minutes late (2.7% of arrivals are
  early) and is weighted by arrival volume across states, months and train types.
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

## Hamburg page vs Germany page

The Hamburg page compares train types **at one station** (Hamburg Hbf by default), so that
all types share the same platforms, traffic and disruptions. ICE serves only 4 Hamburg
stations while the S-Bahn serves about 60, so adding up all stations would compare unlike
networks. The Germany page, filtered to Hamburg, adds up every Hamburg station instead,
so its figures differ: IC/EC cancellations are 8.8% for all of Hamburg but 10.3% at Hamburg
Hbf (Dammtor 6.7%, Harburg 6.5%). The Hamburg page also uses full weeks only, which drops
a few days at each end of the period.

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

## Live hub data (deferred)

The project focuses on the monthly history. The near-real-time collector (S2) was tested and
the live layer is left for later. Findings from the first test (6 Hamburg hubs, 16 runs on
Sat 3 Oct 2026, a public holiday, with hourly runs from 13:07 to 17:07):

- **Reliable:** all 330 API calls returned OK, each in about 1 second. An external cron
  (cron-job.org) triggers the GitHub workflow at :07 every hour, because GitHub's own
  schedule skipped most runs.
- **Hourly is enough:** the change feed (`fchg`) keeps trains for hours after they pass (up
  to about 10 hours), and all 307 checked arrivals were in the first snapshot after they
  passed. A 15-minute schedule is not needed to catch every train.
- **Forecasts are too optimistic:** delays read before a train arrives showed 91% on time,
  while the same trains read after arrival showed 74%. A third of delays changed by 3 minutes
  or more. Each delay must be taken from the first snapshot after the train's expected
  arrival time; from then on it is stable (6 of 604 later readings changed).
- **S-Bahn gap:** Hamburg Hbf, Altona and Harburg have separate station codes for their
  S-Bahn platforms (8098549, 8098553, 8098147, found in the history data). The test only
  collected the main-line codes, so S-Bahn trains at these stations were missing. Add them to
  `config/hubs.yml` (after confirming with `find_eva`) before restarting the collector.
- **Scaling:** each hub costs 4 calls per run (1 change feed, 3 hourly plans). Going from 6 to
  about 35 hubs means about 140 calls per run, which may exceed the DB API's per-minute
  limit. Pace the calls or fetch fewer plan hours (each hour is currently fetched 3 times).
- **Not yet representative:** 5 regular hours on a holiday afternoon. A full week covering
  weekday peaks and nights is needed before drawing conclusions about punctuality.

## Sources and licences

- Train data: Deutsche Bahn and piebro, CC BY 4.0
- State boundaries: Natural Earth, public domain
