"""Hamburg page: weekly comparison of train types, stations and lines."""

from __future__ import annotations

import math

import pandas as pd
import plotly.express as px
import streamlit as st

from dbp.dashboard.charts import cancel_bars_html
from dbp.dashboard.data import (
    GROUP_ORDER,
    MIN_STATION_ARRIVALS,
    summarize_cancellations,
    summarize_weekly,
)
from dbp.dashboard.theme import group_colors, hover_label, palette

# Line families on the Hamburg "Lines" view: line-name pattern per family.
LINE_FAMILIES = {"S-Bahn": r"S\d+", "RE": r"RE\d+", "RB": r"RB\d+"}
# The cancellation ranking lists at most this many items (stations run to dozens).
MAX_CANCEL_ROWS = 10
# A week needs this many planned arrivals before it can be named the worst week.
MIN_WEEK_ARRIVALS = 20


def cancellation_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Cancelled share per item, most cancelled first, with its worst week for the tooltip."""
    table = summarize_cancellations(frame, "item_key")
    table = table.loc[table["planned"] >= MIN_STATION_ARRIVALS]
    weekly = frame.groupby(["item_key", "service_week"], as_index=False)[
        ["arrival_count", "cancelled_arrival_count"]
    ].sum()
    weekly["planned"] = weekly["arrival_count"] + weekly["cancelled_arrival_count"]
    weekly = weekly.loc[weekly["planned"] >= MIN_WEEK_ARRIVALS]
    weekly["pct"] = 100 * weekly["cancelled_arrival_count"] / weekly["planned"]
    worst = weekly.loc[weekly.groupby("item_key")["pct"].idxmax()].set_index("item_key")
    table["worst"] = [
        f"week of {pd.Timestamp(worst.loc[item, 'service_week']):%-d %b %Y} "
        f"({worst.loc[item, 'pct']:.0f}%)"
        if item in worst.index and worst.loc[item, "pct"] > 0
        else ""
        for item in table["item_key"]
    ]
    return table.rename(columns={"item_key": "item"}).reset_index(drop=True)


def line_table(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per line: on-time share, delay and volume over the period, plus weekly trend."""
    weekly = summarize_weekly(frame).sort_values("service_week")
    trends = weekly.groupby("item_key")["punctuality_pct"].apply(
        lambda values: [round(float(value), 1) for value in values.dropna()]
    )
    totals = frame.groupby("item_key")[
        ["arrival_count", "on_time_arrival_count", "delay_count", "delay_total_min"]
    ].sum()
    totals = totals.loc[totals["arrival_count"] > 0]
    table = pd.DataFrame(
        {
            "line": totals.index,
            "punctuality_pct": 100 * totals["on_time_arrival_count"] / totals["arrival_count"],
            "avg_delay": totals["delay_total_min"] / totals["delay_count"].replace(0, math.nan),
            "arrivals": totals["arrival_count"].astype("int64"),
            "trend": [trends.get(line, []) for line in totals.index],
        }
    )
    return table.sort_values("punctuality_pct", ascending=False).reset_index(drop=True)


def render_hamburg(hamburg_frame: pd.DataFrame, month_range: tuple[str, str]) -> None:
    first_month, last_month = month_range
    st.header("Hamburg")
    st.caption("Weekly comparison")
    with st.container(border=True, key="card_hamburg"):
        mode_label = st.segmented_control(
            "Compare",
            ["Train types", "Stations", "Lines"],
            default="Train types",
        ) or "Train types"
        mode_to_kind = {"Lines": "line", "Stations": "station", "Train types": "train_type"}
        item_kind = mode_to_kind[mode_label]
        hamburg = hamburg_frame.loc[
            hamburg_frame["item_kind"] == item_kind
        ].copy()
        hamburg = hamburg.loc[hamburg["service_month_label"].between(first_month, last_month)]
        if item_kind == "station":
            groups = [group for group in GROUP_ORDER if group in hamburg["train_group"].unique()]
            selected_groups = st.multiselect(
                "Train type", groups, default=groups, key="hamburg_train_types"
            )
            hamburg = hamburg.loc[hamburg["train_group"].isin(selected_groups)]
        family = "S-Bahn"
        selected_hub = None
        if item_kind == "line":
            family = st.segmented_control(
                "Lines to compare",
                list(LINE_FAMILIES),
                default="S-Bahn",
                key="hamburg_line_family",
            ) or "S-Bahn"
            hamburg = hamburg.loc[hamburg["item_key"].str.fullmatch(LINE_FAMILIES[family])]
            # Drop stray "lines" with a handful of records (e.g. RB5 with 2 stops).
            line_arrivals = hamburg.groupby("item_key")["arrival_count"].sum()
            hamburg = hamburg.loc[
                hamburg["item_key"].isin(
                    line_arrivals[line_arrivals >= MIN_STATION_ARRIVALS].index
                )
            ]
        if item_kind == "train_type":
            # Only stations served by more than one train type have something to compare.
            types_per_station = hamburg.groupby("station_name")["item_key"].nunique()
            stations = sorted(types_per_station[types_per_station > 1].index.tolist())
            if stations:
                selected_hub = st.selectbox(
                    "Station",
                    stations,
                    index=stations.index("Hamburg Hbf") if "Hamburg Hbf" in stations else 0,
                    key="hamburg_station",
                    help="Stations served by more than one train type.",
                )
                hamburg = hamburg.loc[hamburg["station_name"] == selected_hub]

        slots = ["All day", "Weekday peak", "Off-peak"]
        selected_slot = st.segmented_control("Time slot", slots, default="All day") or "All day"
        if selected_slot != "All day":
            hamburg = hamburg.loc[hamburg["time_slot"] == selected_slot]
        item_options = (
            hamburg.groupby("item_key")["stop_count"].sum().sort_values(ascending=False).index.tolist()
        )
        if item_kind == "train_type":
            item_options = [group for group in GROUP_ORDER if group in item_options]
        item_label = {"line": "Lines", "station": "Stations", "train_type": "Train types"}[
            item_kind
        ]
        if item_kind == "line" and item_options:
            st.markdown(f"**All {family} lines** · best on-time share first")
            table = line_table(hamburg)
            st.dataframe(
                table,
                hide_index=True,
                width="stretch",
                height=35 * (len(table) + 1) + 3,
                column_config={
                    "line": st.column_config.TextColumn("Line", width="small"),
                    "punctuality_pct": st.column_config.ProgressColumn(
                        "On time", format="%.1f%%", min_value=0, max_value=100, color="red"
                    ),
                    "avg_delay": st.column_config.NumberColumn("Avg delay", format="%.1f min"),
                    "arrivals": st.column_config.NumberColumn("Arrivals", format="%,d"),
                    "trend": st.column_config.LineChartColumn(
                        "On time, week by week", y_min=0, y_max=100, color="red"
                    ),
                },
            )
        selected_items = st.multiselect(
            item_label if item_kind != "line" else f"{family} lines to plot week by week",
            item_options,
            default=item_options[:5] if item_kind in ("train_type", "line") else item_options[:3],
            max_selections=5,
        )
        comparison = hamburg.loc[hamburg["item_key"].isin(selected_items)]
        if comparison.empty:
            st.info("No historical records match these filters.")
        else:
            weekly = summarize_weekly(comparison)
            chart_columns = st.columns(2)
            # Same color per item in both charts: train types keep their Germany-page colors,
            # other items follow the selection order.
            colors = palette()
            item_colors = (
                group_colors()
                if item_kind == "train_type"
                else dict(zip(selected_items, colors["categorical"], strict=False))
            )
            for column, metric, label, hover_value in (
                (chart_columns[0], "punctuality_pct", "On-time arrivals (%)", "On time: %{y:.1f}%"),
                (
                    chart_columns[1],
                    "avg_arrival_delay_min",
                    "Average arrival delay (min)",
                    "Avg delay: %{y:.1f} min",
                ),
            ):
                chart = px.line(
                    weekly,
                    x="service_week",
                    y=metric,
                    color="item_key",
                    markers=True,
                    category_orders={"item_key": selected_items},
                    color_discrete_map=item_colors,
                )
                chart.update_traces(
                    line_width=2,
                    marker_size=8,
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>Week of %{x|%d %b %Y}<br>"
                        + hover_value
                        + "<extra></extra>"
                    ),
                )
                chart.update_layout(
                    height=340,
                    margin={"l": 6, "r": 6, "t": 18, "b": 4},
                    xaxis_title=None,
                    yaxis_title=label,
                    legend_title=None,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    hoverlabel=hover_label(),
                )
                chart.update_yaxes(gridcolor=colors["line"])
                chart.update_xaxes(showgrid=False)
                column.plotly_chart(
                    chart, width="stretch", config={"displayModeBar": False}
                )

    context = {
        "train_type": f"Train types at {selected_hub}" if selected_hub else "Train types",
        "station": "Stations",
        "line": f"{family} lines",
    }[item_kind]
    with st.container(border=True, key="card_hamburg_cancelled"):
        st.subheader(f"Cancelled arrivals · {context}")
        # As on the Germany page, the mixed "Other" group stays out of the ranking.
        table = cancellation_table(hamburg.loc[hamburg["train_group"] != "Other"])
        if table.empty:
            st.info("Not enough arrivals to compare cancellations for these filters.")
        else:
            shown = table.head(MAX_CANCEL_ROWS)
            st.caption(
                "Share of planned arrivals cancelled · most cancelled first"
                + ("" if selected_slot == "All day" else f" · {selected_slot.lower()}")
                + (
                    f" · top {len(shown)} of {len(table)}"
                    if len(table) > len(shown)
                    else ""
                )
            )
            st.iframe(cancel_bars_html(shown, "Worst week"), height=40 * len(shown) + 34)
