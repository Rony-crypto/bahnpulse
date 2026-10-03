"""Loading the published marts and the summaries the dashboard pages are built from."""

from __future__ import annotations

import json
import math

import duckdb
import pandas as pd
import streamlit as st

from dbp.config import DATA, ROOT

PUBLISHED = DATA / "published"
MART_DIR = PUBLISHED / "marts"
STATE_GEOJSON = ROOT / "config" / "germany_states.geojson"
MART_FILES = {
    "state": MART_DIR / "agg_state_month_type.parquet",
    "station": MART_DIR / "agg_station_month_type.parquet",
    "hamburg": MART_DIR / "agg_hamburg_weekly.parquet",
    "hourly": MART_DIR / "agg_state_hour_weekday.parquet",
    "coverage": MART_DIR / "agg_month_coverage.parquet",
    "delay_sources": MART_DIR / "agg_delay_sources.parquet",
    "station_gain": MART_DIR / "agg_station_delay_gain.parquet",
    "along_route": MART_DIR / "agg_delay_along_route.parquet",
}
# Date column each mart's "YYYY-MM" filter label is built from.
LABEL_COLUMNS = {
    "state": "service_month",
    "station": "service_month",
    "hourly": "service_month",
    "hamburg": "service_week",
    "delay_sources": "service_month",
    "station_gain": "service_month",
    "along_route": "service_month",
}
GROUP_ORDER = ["ICE", "IC/EC", "RE", "RB", "S", "Other"]
MIN_STATION_ARRIVALS = 100
# A month gets a data-gap warning from this many low-data hours (about one day missing).
GAP_HOURS_WARN = 24


def mart_signature() -> tuple[tuple[str, int], ...]:
    """File modification times, so a fresh export invalidates the cached marts."""
    return tuple(
        (name, path.stat().st_mtime_ns if path.is_file() else 0)
        for name, path in MART_FILES.items()
    )


# cache_resource hands every rerun the same frames instead of an unpickled copy, so pages
# must filter them (.loc) and never change them in place.
@st.cache_resource(show_spinner=False, max_entries=1)
def load_marts(signature: tuple[tuple[str, int], ...]) -> dict[str, pd.DataFrame]:
    missing = [path for path in MART_FILES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(str(path) for path in missing))

    connection = duckdb.connect()
    try:
        marts = {
            name: connection.execute(
                "SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchdf()
            for name, path in MART_FILES.items()
        }
    finally:
        connection.close()
    # Month labels are formatted once here, not on every rerun.
    for name, column in LABEL_COLUMNS.items():
        marts[name]["service_month_label"] = format_months(marts[name], column)
    return marts


@st.cache_data(show_spinner=False)
def load_states() -> dict:
    with STATE_GEOJSON.open(encoding="utf-8") as source:
        return json.load(source)


def cancelled_share(cancelled: pd.Series, arrivals: pd.Series) -> pd.Series:
    """Cancelled share of planned arrivals (cancelled + ran). Counting arrivals counts each
    lost train once, at the station it no longer reached (see docs/report_notes.md)."""
    planned = (cancelled + arrivals).replace(0, pd.NA)
    return 100 * cancelled / planned


def format_months(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_datetime(frame[column]).dt.strftime("%Y-%m")


def summarize_states(frame: pd.DataFrame) -> pd.DataFrame:
    summary = frame.groupby("federal_state", as_index=False).agg(
        planned_stop_count=("planned_stop_count", "sum"),
        cancelled_arrival_count=("cancelled_arrival_count", "sum"),
        arrival_count=("arrival_count", "sum"),
        on_time_arrival_count=("on_time_arrival_count", "sum"),
    )
    delay_totals = frame.assign(
        delay_total=frame["avg_arrival_delay_min"] * frame["arrival_count"]
    ).groupby("federal_state")["delay_total"].sum()
    summary["punctuality_pct"] = (
        100 * summary["on_time_arrival_count"] / summary["arrival_count"].replace(0, pd.NA)
    )
    summary["cancellation_pct"] = cancelled_share(
        summary["cancelled_arrival_count"], summary["arrival_count"]
    )
    summary["avg_arrival_delay_min"] = (
        summary["federal_state"].map(delay_totals)
        / summary["arrival_count"].replace(0, pd.NA)
    )
    return summary


def summarize_stations(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-station totals for the drill-down, worst on-time share first."""
    stations = frame.groupby(["station_name", "federal_state"], as_index=False).agg(
        planned_stop_count=("planned_stop_count", "sum"),
        arrival_count=("arrival_count", "sum"),
        on_time_arrival_count=("on_time_arrival_count", "sum"),
        cancelled_arrival_count=("cancelled_arrival_count", "sum"),
    )
    stations["punctuality_pct"] = (
        100 * stations["on_time_arrival_count"] / stations["arrival_count"].replace(0, pd.NA)
    )
    stations["cancellation_pct"] = cancelled_share(
        stations["cancelled_arrival_count"], stations["arrival_count"]
    )
    return stations.sort_values("punctuality_pct", na_position="last").reset_index(drop=True)


def headline_kpis(summary: pd.DataFrame) -> dict[str, float]:
    """Totals-based KPIs for any set of state rows (one state or all of Germany)."""
    arrivals = summary["arrival_count"].sum()
    stops = summary["planned_stop_count"].sum()
    delay_total = (summary["avg_arrival_delay_min"] * summary["arrival_count"]).sum()
    cancelled = summary["cancelled_arrival_count"].sum()
    return {
        "punctuality": (
            100 * summary["on_time_arrival_count"].sum() / arrivals if arrivals else math.nan
        ),
        "delay": delay_total / arrivals if arrivals else math.nan,
        "cancelled": (
            100 * cancelled / (cancelled + arrivals) if cancelled + arrivals else math.nan
        ),
        "stops": int(stops),
    }


def monthly_kpis(frame: pd.DataFrame) -> pd.DataFrame:
    """Headline KPIs per month, oldest first, for the KPI sparklines."""
    return pd.DataFrame(
        [
            {"month": month, **headline_kpis(rows)}
            for month, rows in frame.groupby("service_month_label", sort=True)
        ]
    )


def summarize_months(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Volume-weighted on-time share and average delay per month and the given keys."""
    monthly = (
        frame.assign(delay_total=frame["avg_arrival_delay_min"] * frame["arrival_count"])
        .groupby(["service_month_label", *keys], as_index=False)
        .agg(
            arrival_count=("arrival_count", "sum"),
            on_time_arrival_count=("on_time_arrival_count", "sum"),
            delay_total=("delay_total", "sum"),
        )
    )
    arrivals = monthly["arrival_count"].where(monthly["arrival_count"] > 0)
    monthly["punctuality_pct"] = 100 * monthly["on_time_arrival_count"] / arrivals
    monthly["avg_arrival_delay_min"] = monthly["delay_total"] / arrivals
    return monthly


def summarize_cancellations(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    """Cancelled share of planned arrivals per `key`, most cancelled first."""
    totals = frame.groupby(key, as_index=False).agg(
        cancelled=("cancelled_arrival_count", "sum"), ran=("arrival_count", "sum")
    )
    totals["planned"] = totals["cancelled"] + totals["ran"]
    totals = totals.loc[totals["planned"] > 0].drop(columns="ran")
    totals["cancelled_pct"] = 100 * totals["cancelled"] / totals["planned"]
    return totals.sort_values("cancelled_pct", ascending=False).reset_index(drop=True)


def summarize_weekly(frame: pd.DataFrame) -> pd.DataFrame:
    weekly = frame.groupby(["item_key", "service_week"], as_index=False).agg(
        stop_count=("stop_count", "sum"),
        arrival_count=("arrival_count", "sum"),
        on_time_arrival_count=("on_time_arrival_count", "sum"),
        delay_count=("delay_count", "sum"),
        delay_total_min=("delay_total_min", "sum"),
    )
    weekly["punctuality_pct"] = (
        100 * weekly["on_time_arrival_count"] / weekly["arrival_count"].replace(0, pd.NA)
    )
    weekly["avg_arrival_delay_min"] = (
        weekly["delay_total_min"] / weekly["delay_count"].replace(0, pd.NA)
    )
    return weekly


def data_gaps(coverage: pd.DataFrame, month_range: tuple[str, str]) -> dict[str, int]:
    """Months in the selected range with many low-data hours: {"2026-07": 55, ...}."""
    labels = pd.to_datetime(coverage["service_month"]).dt.strftime("%Y-%m")
    in_range = labels.between(*month_range) & (coverage["low_data_hours"] >= GAP_HOURS_WARN)
    return dict(zip(labels[in_range], coverage.loc[in_range, "low_data_hours"], strict=True))



def delay_sources(frame: pd.DataFrame) -> pd.DataFrame:
    """Per train type: where the lateness of trips that ended 6+ minutes late came from.

    Shares are of the delay minutes added (lateness at the first station + added while running
    + added at stations); minutes later recovered by timetable buffers are left out.
    """
    late = frame.loc[frame["ends_late"]].groupby("train_group")[
        ["trip_count", "origin_late_min", "running_added_min", "dwell_added_min", "final_late_min"]
    ].sum()
    all_trips = frame.groupby("train_group")["trip_count"].sum()
    added = late[["origin_late_min", "running_added_min", "dwell_added_min"]].sum(axis=1)
    table = pd.DataFrame(
        {
            "origin_pct": 100 * late["origin_late_min"] / added,
            "running_pct": 100 * late["running_added_min"] / added,
            "dwell_pct": 100 * late["dwell_added_min"] / added,
            "late_trip_pct": 100 * late["trip_count"] / all_trips.reindex(late.index),
            "avg_final_late_min": late["final_late_min"] / late["trip_count"],
            "late_trips": late["trip_count"].astype("int64"),
        }
    )
    order = [group for group in GROUP_ORDER if group in table.index]
    return table.reindex(order).rename_axis("train_group").reset_index()


def lateness_along_route(frame: pd.DataFrame) -> pd.DataFrame:
    """Share of stops 6+ minutes late and average lateness by position on the route."""
    route = frame.groupby(["train_group", "route_pct"], as_index=False)[
        ["stop_count", "late_min", "late_stop_count"]
    ].sum()
    route["late_pct"] = 100 * route["late_stop_count"] / route["stop_count"]
    route["avg_late_min"] = route["late_min"] / route["stop_count"]
    return route.sort_values(["train_group", "route_pct"]).reset_index(drop=True)


def station_delay_gain(frame: pd.DataFrame) -> pd.DataFrame:
    """Per station: delay minutes added on the way in and while standing, most added first."""
    stations = frame.groupby(["station_name", "federal_state"], as_index=False)[
        ["measured_stop_count", "running_added_min", "dwell_added_min", "delay_start_count"]
    ].sum()
    stations["added_min"] = stations["running_added_min"] + stations["dwell_added_min"]
    stations = stations.loc[stations["added_min"] > 0]
    stations["added_per_train"] = stations["added_min"] / stations["measured_stop_count"]
    stations["on_the_way_pct"] = 100 * stations["running_added_min"] / stations["added_min"]
    stations["added_hours"] = stations["added_min"] / 60
    return stations.sort_values("added_min", ascending=False).reset_index(drop=True)


def top_share(values: pd.Series, top_fraction: float) -> float:
    """Share of the total held by the largest `top_fraction` of values (e.g. top 5%)."""
    ordered = values.sort_values(ascending=False)
    count = max(1, round(len(ordered) * top_fraction))
    return 100 * ordered.head(count).sum() / ordered.sum() if ordered.sum() else math.nan
