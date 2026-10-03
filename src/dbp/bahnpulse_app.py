"""BahnPulse historical dashboard.

Launch with `uv run streamlit run src/dbp/bahnpulse_app.py` after exporting dbt marts.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from dbp.dashboard.data import data_gaps, load_marts, load_states, mart_signature
from dbp.dashboard.germany import render_germany
from dbp.dashboard.hamburg import render_hamburg
from dbp.dashboard.theme import (
    PLOTLY_HOVER_FOLLOW_JS,
    THEME_SYNC_JS,
    app_css,
    hero_banner_html,
)

GITHUB_URL = "https://github.com/Rony-crypto/bahnpulse"


# The month range survives page switches the same way as the Germany filters (see
# dbp.dashboard.germany.copy_state).
def store_month_range() -> None:
    first, last = st.session_state["w_month_from"], st.session_state["w_month_to"]
    if first > last:
        # Swap a reversed pick so both dropdowns show the corrected order.
        first, last = last, first
        st.session_state["w_month_from"], st.session_state["w_month_to"] = first, last
    st.session_state["month_range"] = (first, last)


def render_dashboard(view: str) -> None:
    # Repeated per page: the layout set in main() does not carry into st.navigation pages.
    st.set_page_config(layout="wide")
    st.markdown(app_css(), unsafe_allow_html=True)
    st.html(PLOTLY_HOVER_FOLLOW_JS, unsafe_allow_javascript=True)
    st.html(THEME_SYNC_JS, unsafe_allow_javascript=True)
    st.button("Sync theme", key="bp_theme_sync")
    # Filled once the month range is known, but drawn at the very top of the page.
    banner = st.container()

    try:
        marts = load_marts(mart_signature())
        states = load_states()
    except (FileNotFoundError, json.JSONDecodeError) as error:
        st.error("Published history marts are not available yet.")
        st.code(
            "uv run dbt build --project-dir dbt --profiles-dir dbt\n"
            "uv run python -m dbp.publish.export_marts",
            language="bash",
        )
        st.caption(str(error))
        return

    state_frame = marts["state"]
    available_months = sorted(state_frame["service_month_label"].dropna().unique().tolist())
    if not available_months:
        st.warning("No monthly history is available in the published marts.")
        return

    with st.sidebar:
        st.header("History")
        page_filters = st.container()
        month_names = {month: pd.Period(month).strftime("%b %Y") for month in available_months}
        stored_from, stored_to = st.session_state.get(
            "month_range", (available_months[0], available_months[-1])
        )
        st.session_state["w_month_from"] = (
            stored_from if stored_from in available_months else available_months[0]
        )
        st.session_state["w_month_to"] = (
            stored_to if stored_to in available_months else available_months[-1]
        )
        from_column, to_column = st.columns(2)
        from_column.selectbox(
            "From",
            available_months,
            format_func=lambda month: month_names[month],
            key="w_month_from",
            on_change=store_month_range,
        )
        to_column.selectbox(
            "To",
            available_months,
            format_func=lambda month: month_names[month],
            key="w_month_to",
            on_change=store_month_range,
        )
        month_range = (st.session_state["w_month_from"], st.session_state["w_month_to"])
        st.session_state["month_range"] = month_range

    gaps = data_gaps(marts["coverage"], month_range)
    with banner:
        st.html(hero_banner_html(month_range))

    if view == "Germany":
        render_germany(
            state_frame, marts["station"], marts["hourly"], states, month_range, page_filters, gaps
        )
    else:
        render_hamburg(marts["hamburg"], month_range)

    render_footer()


def render_footer() -> None:
    # One quiet line: the CC BY 4.0 data needs its attribution. Run status and data-gap
    # notes live in docs/report_notes.md.
    st.markdown(
        '<div class="bp-footer">Data: Deutsche Bahn &amp; piebro (CC BY 4.0) · '
        "Boundaries: Natural Earth · "
        f'<a href="{GITHUB_URL}" target="_blank">GitHub</a></div>',
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="BahnPulse | DB punctuality", layout="wide")
    pages = [
        st.Page(
            "pages/germany.py",
            title="Germany",
            url_path="germany",
            default=True,
        ),
        st.Page(
            "pages/hamburg.py",
            title="Hamburg",
            url_path="hamburg",
        ),
    ]
    st.navigation(pages, position="sidebar").run()


if __name__ == "__main__":
    main()
