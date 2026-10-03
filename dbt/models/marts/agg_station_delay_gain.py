"""Lateness added at each station (on the way in and while standing) and where trains first
become late, per month and train type. Logic: dbp.transform.delay_spread."""

from dbp.transform.delay_spread import STATION_GAIN_SQL, build_by_month


def model(dbt, session):
    dbt.config(materialized="table")
    # Built after agg_delay_sources, not beside it: each rebuilds trips month by month, and
    # running them one at a time keeps memory low.
    dbt.ref("agg_delay_sources")
    return build_by_month(
        session,
        dbt.ref("fct_stop_event"),
        STATION_GAIN_SQL,
        "station_gain",
        stations=dbt.ref("dim_station"),
    )
