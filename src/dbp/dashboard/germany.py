"""Germany page: KPIs, state map and ranking, delay breakdown, heatmap, trend, stations."""

from __future__ import annotations

from functools import partial

import pandas as pd
import streamlit as st

from dbp.dashboard.charts import (
    MIN_HEATMAP_ARRIVALS,
    cancel_bars_html,
    delay_bars_html,
    delay_breakdown,
    delay_donut_html,
    hour_weekday_heatmap,
    monthly_trend,
    state_map,
)
from dbp.dashboard.data import (
    GROUP_ORDER,
    MIN_STATION_ARRIVALS,
    headline_kpis,
    monthly_kpis,
    summarize_cancellations,
    summarize_states,
    summarize_stations,
)
from dbp.dashboard.theme import palette

ALL_GERMANY = "All Germany"


# Streamlit drops widget state when switching pages, so each filter keeps its value in a
# plain session-state entry, copied in by the widget's on_change callback and written back
# into the widget before it is drawn on every run.
def copy_state(source: str, target: str) -> None:
    st.session_state[target] = st.session_state[source]


def set_area(area: str) -> None:
    st.session_state["area"] = area


def select_ranked_state(key: str) -> None:
    """Switch the page to the state clicked in the ranking table."""
    rows = st.session_state[key].selection.rows
    order = st.session_state.get("ranking_order", [])
    if rows and rows[0] < len(order):
        st.session_state["area"] = order[rows[0]]


def train_type_cancellations(frame: pd.DataFrame) -> pd.DataFrame:
    """Cancelled share per train type, most cancelled first, with its worst month."""
    table = summarize_cancellations(frame, "train_group")
    monthly = summarize_cancellations(
        frame.assign(key=frame["train_group"] + "|" + frame["service_month_label"]), "key"
    )
    monthly[["train_group", "month"]] = monthly["key"].str.split("|", expand=True)
    worst = monthly.drop_duplicates("train_group").set_index("train_group")
    table["worst"] = [
        f"{pd.Period(worst.loc[group, 'month']).strftime('%b %Y')} "
        f"({worst.loc[group, 'cancelled_pct']:.1f}%)"
        if group in worst.index
        else ""
        for group in table["train_group"]
    ]
    return table.rename(columns={"train_group": "item"})


def render_germany(
    state_frame: pd.DataFrame,
    station_frame: pd.DataFrame,
    hourly_frame: pd.DataFrame,
    states: dict,
    month_range: tuple[str, str],
    page_filters,
    gaps: dict[str, int],
) -> None:
    groups = [group for group in GROUP_ORDER if group in state_frame["train_group"].unique()]
    state_names = sorted(state_frame["federal_state"].dropna().unique().tolist())
    areas = [ALL_GERMANY, *state_names]
    st.session_state["w_train_groups"] = [
        group
        for group in st.session_state.get("train_groups", ["RE"] if "RE" in groups else groups[:1])
        if group in groups
    ]
    with page_filters:
        selected_groups = st.multiselect(
            "Train type",
            groups,
            key="w_train_groups",
            on_change=copy_state,
            args=("w_train_groups", "train_groups"),
        )

    first_month, last_month = month_range
    selected_states = state_frame.loc[
        state_frame["train_group"].isin(selected_groups)
        & state_frame["service_month_label"].between(first_month, last_month)
    ]
    selected_stations = station_frame.loc[
        station_frame["train_group"].isin(selected_groups)
        & station_frame["service_month_label"].between(first_month, last_month)
    ]
    state_summary = summarize_states(selected_states)
    ranked_states = state_summary.dropna(subset=["punctuality_pct"]).sort_values(
        "punctuality_pct"
    )
    worst_state = ranked_states["federal_state"].iloc[0] if not ranked_states.empty else None

    chosen_area = st.session_state.get("area")
    st.session_state["w_area"] = chosen_area if chosen_area in areas else ALL_GERMANY
    with page_filters:
        area = st.selectbox(
            "State",
            areas,
            key="w_area",
            on_change=copy_state,
            args=("w_area", "area"),
            help="Headline numbers, trend and stations follow this choice. "
            "You can also click a state in the ranking.",
        )
    is_state = area != ALL_GERMANY

    st.header(area if is_state else "Germany")
    if selected_states.empty:
        st.warning("No data for the selected train type and month range.")
        return
    month_label = lambda month: pd.Period(month).strftime("%b %Y")  # noqa: E731
    st.caption(
        f"{', '.join(selected_groups)} · {month_label(first_month)} – {month_label(last_month)}"
        + (
            f" · lowest on-time share of all {len(ranked_states)} states"
            if area == worst_state
            else ""
        )
    )

    germany = headline_kpis(state_summary)
    shown = (
        headline_kpis(state_summary.loc[state_summary["federal_state"] == area])
        if is_state
        else germany
    )

    area_states = (
        selected_states.loc[selected_states["federal_state"] == area]
        if is_state
        else selected_states
    )
    by_month = monthly_kpis(area_states)
    sparkline = (lambda key: by_month[key].round(2).tolist()) if len(by_month) > 1 else (
        lambda key: None
    )

    metric_columns = st.columns(4)
    for column, label, key, unit, diff_unit, higher_is_better, icon in (
        (metric_columns[0], "On-time arrivals", "punctuality", "%", " pts", True,
         ":material/schedule:"),
        (metric_columns[1], "Average arrival delay", "delay", " min", " min", False,
         ":material/timer:"),
        (metric_columns[2], "Cancelled arrivals", "cancelled", "%", " pts", False,
         ":material/cancel:"),
    ):
        value = shown[key]
        delta = None
        if is_state and not pd.isna(value):
            # Plain ASCII sign: Streamlit reads it to choose the arrow and color.
            delta = f"{value - germany[key]:+.1f}{diff_unit}"
        column.metric(
            label,
            "–" if pd.isna(value) else f"{value:.1f}{unit}",
            delta,
            delta_color="normal" if higher_is_better else "inverse",
            delta_description="vs Germany" if delta else None,
            icon=icon,
            chart_data=sparkline(key),
            chart_type="area",
            help="Small chart: month by month for this selection.",
        )
    stops_share = 100 * shown["stops"] / germany["stops"] if germany["stops"] else 0
    metric_columns[3].metric(
        "Planned stops",
        f"{shown['stops']:,}",
        f"{stops_share:.1f}% of Germany" if is_state else None,
        delta_color="off",
        delta_arrow="off",
        icon=":material/train:",
        chart_data=sparkline("stops"),
        chart_type="bar",
    )

    map_column, ranking_column = st.columns([0.85, 1.15])
    with map_column, st.container(border=True, key="card_map"):
        st.subheader("Punctuality by federal state")
        st.caption(
            f"{', '.join(selected_groups)} · share of arrivals under 6 minutes late · "
            "darker red = fewer trains on time"
        )
        st.plotly_chart(
            state_map(states, state_summary, area if is_state else None),
            width="stretch",
            config={"displayModeBar": False},
        )

    with ranking_column, st.container(border=True, key="card_ranking"):
        st.subheader("State ranking")
        if worst_state:
            worst = headline_kpis(state_summary.loc[state_summary["federal_state"] == worst_state])
            with st.container(border=True, key="callout_lowest"):
                text_column, button_column = st.columns([3, 1], vertical_alignment="center")
                text_column.markdown(
                    f"**Lowest:** {worst_state} · {worst['punctuality']:.1f}% on time "
                    f"({worst['punctuality'] - germany['punctuality']:+.1f} pts vs Germany)"
                )
                if area == worst_state:
                    button_column.button(
                        "All Germany", on_click=set_area, args=(ALL_GERMANY,), width="stretch"
                    )
                else:
                    button_column.button(
                        "View →", on_click=set_area, args=(worst_state,), width="stretch"
                    )
        ranking = (
            state_summary.dropna(subset=["punctuality_pct"])
            .sort_values("punctuality_pct", ascending=False)
            .reset_index(drop=True)
        )
        ranking.insert(0, "rank", range(1, len(ranking) + 1))
        st.session_state["ranking_order"] = ranking["federal_state"].tolist()
        ranking = ranking[
            [
                "rank",
                "federal_state",
                "punctuality_pct",
                "avg_arrival_delay_min",
                "cancellation_pct",
            ]
        ].rename(
            columns={
                "rank": "#",
                "federal_state": "State",
                "punctuality_pct": "On time",
                "avg_arrival_delay_min": "Avg delay",
                "cancellation_pct": "Cancelled",
            }
        )
        highlight = palette()["highlight"]
        styled = ranking.style.format(
            {
                "On time": "{:.1f}%",
                "Avg delay": "{:.1f} min",
                "Cancelled": "{:.1f}%",
            }
        ).apply(
            lambda row: [
                f"background-color: {highlight}; font-weight: 700"
                if row["State"] == area
                else ""
            ]
            * len(row),
            axis=1,
        )
        st.caption("Best on-time share first · click a row to view that state")
        # Keyed on the shown state so the click selection clears once the page switches;
        # the shown state stays highlighted instead.
        ranking_key = f"w_ranking_{area}"
        st.dataframe(
            styled,
            hide_index=True,
            width="stretch",
            height=35 * (len(ranking) + 1) + 3,
            key=ranking_key,
            on_select=partial(select_ranked_state, ranking_key),
            selection_mode="single-row",
            column_config={
                "#": st.column_config.NumberColumn(width=32),
                "State": st.column_config.TextColumn(width="medium"),
            },
        )

    in_area = (lambda frame: frame.loc[frame["federal_state"] == area]) if is_state else (
        lambda frame: frame
    )
    scope = area if is_state else "Germany"

    with st.container(border=True, key="card_delays"):
        st.subheader(f"How late are arrivals? · {scope}")
        st.caption("Share of planned arrivals, cancellations included")
        donut_column, bars_column = st.columns([1, 1.6])
        with donut_column:
            # Iframes keep the SVG (st.html strips it) and the cursor-following tooltips.
            st.iframe(delay_donut_html(delay_breakdown(in_area(selected_states))), height=430)
        with bars_column:
            period_states = state_frame.loc[
                state_frame["service_month_label"].between(first_month, last_month)
            ]
            st.iframe(
                delay_bars_html(delay_breakdown(in_area(period_states), by="train_group")),
                height=365,
            )
            st.caption("All train types side by side, whatever the train type filter")

    with st.container(border=True, key="card_cancelled"):
        st.subheader(f"Cancellations by train type · {scope}")
        st.caption(
            "Share of planned arrivals cancelled · every main train type, whatever the filter"
        )
        # "Other" (specials, replacement services) runs far above the rest and would squash
        # the scale, so it is left out here.
        rail_states = period_states.loc[period_states["train_group"] != "Other"]
        cancelled = train_type_cancellations(in_area(rail_states))
        if is_state:
            national = summarize_cancellations(rail_states, "train_group")
            cancelled["ref_pct"] = cancelled["item"].map(
                national.set_index("train_group")["cancelled_pct"]
            )
        st.iframe(
            cancel_bars_html(
                cancelled, "Worst month", "Germany" if is_state else None, scope
            ),
            height=40 * len(cancelled) + (64 if is_state else 34),
        )

    with st.container(border=True, key="card_heatmap"):
        st.subheader(f"When are trains late? · {scope}")
        selected_hours = in_area(
            hourly_frame.loc[
                hourly_frame["train_group"].isin(selected_groups)
                & hourly_frame["service_month_label"].between(first_month, last_month)
            ]
        )
        heatmap, best, worst_slot = hour_weekday_heatmap(selected_hours)
        if heatmap is None:
            st.info("Not enough arrivals to show a pattern for this selection.")
        else:
            st.caption(
                f"On-time share by planned arrival hour · darker red = fewer trains on time · "
                f"blank = fewer than {MIN_HEATMAP_ARRIVALS} arrivals · "
                f"worst: {worst_slot} · best: {best}"
            )
            st.plotly_chart(heatmap, width="stretch", config={"displayModeBar": False})

    with st.container(border=True, key="card_trend"):
        st.subheader(f"Monthly trend · {area}" if is_state else "Monthly trend")
        st.caption(
            "On-time share by month"
            + (" · shaded band = range across all states" if len(selected_groups) == 1 else "")
            + (" · dotted = Germany" if is_state else "")
            + " · bars = average arrival delay"
        )
        st.plotly_chart(
            monthly_trend(selected_states, area if is_state else None, gaps),
            width="stretch",
            config={"displayModeBar": False},
        )

    with st.container(border=True, key="card_stations"):
        st.subheader(f"Stations · {area}" if is_state else "Stations · Germany")
        area_stations = (
            selected_stations.loc[selected_stations["federal_state"] == area]
            if is_state
            else selected_stations
        )
        # Stations with a handful of arrivals (often diversions) swing to 0% or 100% on one
        # train, so they are left out of the ranking.
        all_stations = summarize_stations(area_stations)
        station_detail = all_stations.loc[all_stations["arrival_count"] >= MIN_STATION_ARRIVALS]
        st.caption(
            f"{len(station_detail):,} stations · worst on-time share first · "
            f"stations with fewer than {MIN_STATION_ARRIVALS} arrivals are not listed"
        )
        st.dataframe(
            station_detail,
            hide_index=True,
            width="stretch",
            height=420,
            column_order=[
                "station_name",
                *([] if is_state else ["federal_state"]),
                "punctuality_pct",
                "cancellation_pct",
                "planned_stop_count",
                "arrival_count",
            ],
            column_config={
                "station_name": st.column_config.TextColumn("Station"),
                "federal_state": st.column_config.TextColumn("State"),
                "punctuality_pct": st.column_config.ProgressColumn(
                    "On time", format="%.1f%%", min_value=0, max_value=100, color="red"
                ),
                "cancellation_pct": st.column_config.NumberColumn("Cancelled", format="%.1f%%"),
                "planned_stop_count": st.column_config.NumberColumn("Stops", format="%,d"),
                "arrival_count": st.column_config.NumberColumn("Arrivals", format="%,d"),
            },
        )
