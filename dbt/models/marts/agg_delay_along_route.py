"""How lateness builds up along the route (0% = first station, 100% = last), per month and
train type. Logic: dbp.transform.delay_spread."""

from dbp.transform.delay_spread import ALONG_ROUTE_SQL, build_by_month


def model(dbt, session):
    dbt.config(materialized="table")
    # One at a time after the other delay-spread models, to keep memory low.
    dbt.ref("agg_station_delay_gain")
    return build_by_month(
        session, dbt.ref("fct_stop_event"), ALONG_ROUTE_SQL, "along_route"
    )
