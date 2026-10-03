"""Where the lateness of trips comes from (first station, running, standing), per month and
train type. assert_delay_sources_add_up checks that the parts add up to the final lateness.
Logic: dbp.transform.delay_spread."""

from dbp.transform.delay_spread import DELAY_SOURCES_SQL, build_by_month


def model(dbt, session):
    dbt.config(materialized="table")
    return build_by_month(
        session, dbt.ref("fct_stop_event"), DELAY_SOURCES_SQL, "delay_sources"
    )
