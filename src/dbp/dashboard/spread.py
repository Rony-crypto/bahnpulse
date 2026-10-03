"""Germany page: where delays start and how they build up along the route."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dbp.dashboard.charts import along_route_chart, delay_sources_html
from dbp.dashboard.data import (
    MIN_STATION_ARRIVALS,
    delay_sources,
    lateness_along_route,
    station_delay_gain,
    top_share,
)

# The "top 5% add X%" figure is shown only with this many stations (2+ in the top 5%).
MIN_STATIONS_FOR_SHARE = 40


def render_delay_spread(
    spread: dict[str, pd.DataFrame],
    month_range: tuple[str, str],
    selected_groups: list[str],
    area: str | None,
) -> None:
    in_months = lambda frame: frame.loc[  # noqa: E731
        frame["service_month_label"].between(*month_range)
    ]
    sources = delay_sources(in_months(spread["delay_sources"]))
    route = lateness_along_route(in_months(spread["along_route"]))

    # Trips cross state borders, so the build-up is shown for all of Germany.
    with st.container(border=True, key="card_buildup"):
        st.subheader("How delays build up · Germany")
        if sources.empty:
            st.info("No complete trips in this month range.")
        else:
            by_group = sources.set_index("train_group")
            notes = []
            if "ICE" in by_group.index:
                notes.append(
                    f"ICE trips that end late pick up {by_group.loc['ICE', 'running_pct']:.0f}% "
                    "of their delay between stations"
                )
            if "S" in by_group.index:
                notes.append(
                    f"S-Bahn trips {by_group.loc['S', 'dwell_pct']:.0f}% while standing at "
                    "stations"
                )
            st.caption(
                "Where the delay of trips ending 6+ min late comes from · "
                + ", ".join(notes)
                + " · all main train types, whatever the filter"
            )
            sources_column, route_column = st.columns([1, 1.1])
            with sources_column:
                st.iframe(delay_sources_html(sources), height=50 * len(sources) + 60)
            with route_column:
                st.plotly_chart(
                    along_route_chart(route), width="stretch", config={"displayModeBar": False}
                )
                st.caption("Trains start mostly on time; delay builds up stop by stop")

    scope = area or "Germany"
    with st.container(border=True, key="card_delay_added"):
        st.subheader(f"Where delays are added · {scope}")
        gains = in_months(spread["station_gain"])
        gains = gains.loc[gains["train_group"].isin(selected_groups)]
        if area:
            gains = gains.loc[gains["federal_state"] == area]
        stations = station_delay_gain(gains)
        # Stations with a handful of trains swing widely, so they are not ranked.
        stations = stations.loc[stations["measured_stop_count"] >= MIN_STATION_ARRIVALS]
        if stations.empty:
            st.info("Not enough trains to rank stations for this selection.")
            return
        concentration = (
            f" · the top 5% add {top_share(stations['added_min'], 0.05):.0f}% of all delay "
            "minutes"
            if len(stations) >= MIN_STATIONS_FOR_SHARE
            else ""
        )
        st.caption(
            f"{', '.join(selected_groups)} · {len(stations):,} stations{concentration} · "
            "most added first"
        )
        st.dataframe(
            stations,
            hide_index=True,
            width="stretch",
            height=min(420, 35 * (len(stations) + 1) + 3),
            column_order=[
                "station_name",
                *([] if area else ["federal_state"]),
                "added_hours",
                "added_per_train",
                "on_the_way_pct",
                "delay_start_count",
            ],
            column_config={
                "station_name": st.column_config.TextColumn("Station"),
                "federal_state": st.column_config.TextColumn("State"),
                "added_hours": st.column_config.NumberColumn(
                    "Delay added", format="%,.0f h", help="All delay minutes added, in hours."
                ),
                "added_per_train": st.column_config.NumberColumn(
                    "Per train", format="%.2f min", help="Delay added per train stopping here."
                ),
                "on_the_way_pct": st.column_config.ProgressColumn(
                    "Added on the way in",
                    format="%.0f%%",
                    min_value=0,
                    max_value=100,
                    color="red",
                    help="Share added between the previous station and this one; the rest is "
                    "added while the train stands here.",
                ),
                "delay_start_count": st.column_config.NumberColumn(
                    "Delay starts",
                    format="%,d",
                    help="Trains that first became 6+ minutes late here.",
                ),
            },
        )
