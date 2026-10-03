"""BahnPulse historical dashboard.

Launch with `uv run streamlit run src/dbp/app.py` after exporting dbt marts.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from dbp.dashboard.data import (
    data_gaps,
    format_months,
    load_marts,
    load_run_status,
    load_states,
    mart_signature,
)
from dbp.dashboard.germany import render_germany
from dbp.dashboard.hamburg import render_hamburg
from dbp.dashboard.theme import (
    PLOTLY_HOVER_FOLLOW_JS,
    THEME_SYNC_JS,
    app_css,
    hero_banner_html,
)

GITHUB_URL = "https://github.com/Rony-crypto/bahnpulse"
# Known gaps per month (TRD section 3; found with agg_month_coverage), shown in the footer.
COVERAGE_NOTES = {
    "2025-11": "1–2 Nov 2025 (largest stations only)",
    "2026-07": "7 nights in Jul 2026 (overnight data missing, ~3% of the month's stops)",
}


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

    state_frame = marts["state"].copy()
    state_frame["service_month_label"] = format_months(state_frame, "service_month")
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
        station_frame = marts["station"].copy()
        station_frame["service_month_label"] = format_months(station_frame, "service_month")
        hourly_frame = marts["hourly"].copy()
        hourly_frame["service_month_label"] = format_months(hourly_frame, "service_month")
        render_germany(
            state_frame, station_frame, hourly_frame, states, month_range, page_filters, gaps
        )
    else:
        hamburg_frame = marts["hamburg"].copy()
        hamburg_frame["service_month_label"] = format_months(hamburg_frame, "service_week")
        render_hamburg(hamburg_frame, month_range)

    render_footer(month_range[1], gaps)


def render_footer(last_month: str, gaps: dict[str, int]) -> None:
    status = load_run_status()
    history_end = pd.Period(status.get("source_month_end", last_month)).strftime("%b %Y")
    dbt_run = status.get("dbt") or {}
    run_at = dbt_run.get("run_at") or status.get("built_at")
    run_text = (
        "Last pipeline run "
        + pd.Timestamp(run_at).tz_convert("Europe/Berlin").strftime("%-d %b %Y, %H:%M %Z")
        if run_at
        else "Last pipeline run not recorded"
    )
    if dbt_run:
        run_text += f" ({dbt_run['tests_passed']} data tests passed)"
    st.divider()
    st.caption(
        f"History through {history_end} · {run_text} · "
        "Data: Deutsche Bahn and piebro, CC BY 4.0 · State boundaries: Natural Earth, public domain"
        f" · [Source code on GitHub]({GITHUB_URL})"
    )
    if gaps:
        notes = [
            COVERAGE_NOTES.get(month)
            or f"{pd.Period(month).strftime('%b %Y')} ({hours} hours with partial data)"
            for month, hours in gaps.items()
        ]
        st.caption("Known data gaps: " + " · ".join(notes))


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
