# Report notes

Notes that used to sit on the dashboard as captions and footer text. They belong in the
report's method and limitations sections rather than on the live page.

## Definitions

- **On time** means an arrival less than 6 minutes late (DB definition).
- **Headline on-time share** leaves cancelled arrivals out, as DB does. The delay breakdown
  (donut and bars) counts cancelled arrivals in its base, so its "on time" share is a little
  lower than the headline figure.
- **Average arrival delay** is weighted by arrival volume across states, months and train types.
- **Cancelled stops** are planned stops where the arrival or the departure was cancelled,
  as a share of all planned stops. Germany and Hamburg use the same definition.
- The cancellation charts leave out the mixed "Other" group (specials and replacement
  services). Its rate is far higher, for example 28% in Hamburg and 78% at Hamburg Hbf, and
  would squash the scale for the main train types.
- In the Hamburg cancellation ranking, items with fewer than 100 stops are left out, and a
  week needs at least 20 stops before it can be named the worst week.

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
