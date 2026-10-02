"""BahnPulse historical dashboard.

Launch with `uv run streamlit run src/dbp/app.py` after exporting dbt marts.
"""

from __future__ import annotations

import base64
import html
import json
import math
from functools import partial
from typing import cast

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

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
}
GROUP_ORDER = ["ICE", "IC/EC", "RE", "RB", "S", "Other"]
MIN_STATION_ARRIVALS = 100
ALL_GERMANY = "All Germany"
GITHUB_URL = "https://github.com/Rony-crypto/bahnpulse"
# A month gets a data-gap warning from this many low-data hours (about one day missing).
GAP_HOURS_WARN = 24
# Known gaps per month (TRD section 3; found with agg_month_coverage), shown in the footer.
COVERAGE_NOTES = {
    "2025-11": "1–2 Nov 2025 (largest stations only)",
    "2026-07": "7 nights in Jul 2026 (overnight data missing, ~3% of the month's stops)",
}
# Line families on the Hamburg "Lines" view: line-name pattern per family.
LINE_FAMILIES = {"S-Bahn": r"S\d+", "RE": r"RE\d+", "RB": r"RB\d+"}
MIN_HEATMAP_ARRIVALS = 50
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Deutsche Bahn brand palette (DB red, cool grays and DB accent colors).
DB_INK = "#282D37"
DB_RED = "#EC0016"
# Colors that follow the viewer's light/dark choice (⋮ menu → Light / Dark / System); keep
# in step with .streamlit/config.toml. Dark mode uses DB's cool slate grays, not near-black.
THEME_COLORS = {
    "light": {
        "ink": DB_INK,
        "muted": "#646973",
        "card": "#FFFFFF",
        "line": "#D7DCE1",
        "highlight": "#FDE3E4",
        "callout": "#FDF2F3",
        "shadow": "rgba(40, 45, 55, 0.08)",
        "categorical": ["#EC0016", "#1455C0", "#309FD1", "#814997", "#408335", "#878C96"],
    },
    "dark": {
        "ink": "#F0F3F5",
        "muted": "#AFB4BB",
        "card": "#2C323D",
        "line": "#434956",
        "highlight": "#5C2A35",
        "callout": "#40303A",
        "shadow": "rgba(20, 22, 28, 0.35)",
        "categorical": ["#FF3B4A", "#73AEF0", "#55B9E6", "#B286C4", "#66A558", "#AFB4BB"],
    },
}
# Delay buckets in one rose-to-wine family: blush (on time), rose, raspberry, crimson and
# wine for longer delays, muted plum for cancelled. Nothing near-black.
# Columns come from agg_state_month_type.
# Deep wine tone the donut slices shade lightly toward at their edges (soft satin sheen).
DONUT_EDGE = "#5A1A33"
DONUT_EDGE_AMOUNT = 0.3
DELAY_BUCKETS = [
    ("on_time_arrival_count", "On time (<6 min)", "#F4B6C2"),
    ("delay_6_15_count", "6–15 min late", "#EC7F98"),
    ("delay_16_30_count", "16–30 min late", "#DB4568"),
    ("delay_31_60_count", "31–60 min late", "#B71D47"),
    ("delay_over_60_count", "Over 60 min late", "#851637"),
    ("cancelled_arrival_count", "Cancelled", "#7A4A68"),
]
# Sequential DB red ramp: darker red means fewer trains on time.
DB_RED_SCALE = ["#5E0008", "#9B000E", "#EC0016", "#F4545E", "#F9A3A8", "#FDE3E4"]


def palette() -> dict:
    """Colors for the theme the viewer is looking at."""
    return THEME_COLORS["dark" if st.context.theme.type == "dark" else "light"]


def hover_label() -> dict[str, str]:
    """One tooltip look for every Plotly chart: card background, light border, ink text."""
    colors = palette()
    return {"bgcolor": colors["card"], "bordercolor": colors["line"], "font_color": colors["ink"]}


def group_colors() -> dict[str, str]:
    return dict(zip(GROUP_ORDER, palette()["categorical"], strict=True))


def mart_signature() -> tuple[tuple[str, int], ...]:
    """File modification times, so a fresh export invalidates the cached marts."""
    return tuple(
        (name, path.stat().st_mtime_ns if path.is_file() else 0)
        for name, path in MART_FILES.items()
    )


@st.cache_data(show_spinner=False, max_entries=1)
def load_marts(signature: tuple[tuple[str, int], ...]) -> dict[str, pd.DataFrame]:
    missing = [path for path in MART_FILES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(str(path) for path in missing))

    connection = duckdb.connect()
    try:
        return {
            name: connection.execute(
                "SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchdf()
            for name, path in MART_FILES.items()
        }
    finally:
        connection.close()


@st.cache_data(show_spinner=False)
def load_states() -> dict:
    with STATE_GEOJSON.open(encoding="utf-8") as source:
        return json.load(source)


def format_months(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_datetime(frame[column]).dt.strftime("%Y-%m")


def summarize_states(frame: pd.DataFrame) -> pd.DataFrame:
    summary = frame.groupby("federal_state", as_index=False).agg(
        planned_stop_count=("planned_stop_count", "sum"),
        cancelled_stop_count=("cancelled_stop_count", "sum"),
        arrival_count=("arrival_count", "sum"),
        on_time_arrival_count=("on_time_arrival_count", "sum"),
    )
    delay_totals = frame.assign(
        delay_total=frame["avg_arrival_delay_min"] * frame["arrival_count"]
    ).groupby("federal_state")["delay_total"].sum()
    summary["punctuality_pct"] = (
        100 * summary["on_time_arrival_count"] / summary["arrival_count"].replace(0, pd.NA)
    )
    summary["cancellation_pct"] = (
        100
        * summary["cancelled_stop_count"]
        / summary["planned_stop_count"].replace(0, pd.NA)
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
        cancelled_stop_count=("cancelled_stop_count", "sum"),
    )
    stations["punctuality_pct"] = (
        100 * stations["on_time_arrival_count"] / stations["arrival_count"].replace(0, pd.NA)
    )
    stations["cancellation_pct"] = (
        100
        * stations["cancelled_stop_count"]
        / stations["planned_stop_count"].replace(0, pd.NA)
    )
    return stations.sort_values("punctuality_pct", na_position="last").reset_index(drop=True)


def headline_kpis(summary: pd.DataFrame) -> dict[str, float]:
    """Totals-based KPIs for any set of state rows (one state or all of Germany)."""
    arrivals = summary["arrival_count"].sum()
    stops = summary["planned_stop_count"].sum()
    delay_total = (summary["avg_arrival_delay_min"] * summary["arrival_count"]).sum()
    return {
        "punctuality": (
            100 * summary["on_time_arrival_count"].sum() / arrivals if arrivals else math.nan
        ),
        "delay": delay_total / arrivals if arrivals else math.nan,
        "cancelled": 100 * summary["cancelled_stop_count"].sum() / stops if stops else math.nan,
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


def summarize_national_months(frame: pd.DataFrame) -> pd.DataFrame:
    monthly = frame.groupby(["service_month_label", "train_group"], as_index=False).agg(
        arrival_count=("arrival_count", "sum"),
        on_time_arrival_count=("on_time_arrival_count", "sum"),
    )
    monthly["punctuality_pct"] = (
        100 * monthly["on_time_arrival_count"] / monthly["arrival_count"].replace(0, pd.NA)
    )
    return monthly


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


def store_month_range() -> None:
    first, last = st.session_state["w_month_from"], st.session_state["w_month_to"]
    if first > last:
        # Swap a reversed pick so both dropdowns show the corrected order.
        first, last = last, first
        st.session_state["w_month_from"], st.session_state["w_month_to"] = first, last
    st.session_state["month_range"] = (first, last)


# BahnPulse's own mark (not the DB logo): a pulse line running along a rail.
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
<rect width="48" height="48" rx="12" fill="#FFFFFF"/>
<path d="M6 26h9l3.5-9 5.5 18 4.5-13 3 4H42" fill="none" stroke="#EC0016" stroke-width="3.6"
 stroke-linecap="round" stroke-linejoin="round"/>
<path d="M8 39h32" stroke="#282D37" stroke-width="2.2" stroke-linecap="round"/>
<path d="M13 36.5v5M20 36.5v5M27 36.5v5M34 36.5v5" stroke="#282D37" stroke-width="1.6"
 stroke-linecap="round"/>
</svg>"""
# Faint pulse line drawn across the banner background.
BANNER_PULSE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 160">
<path d="M0 95h190l22-55 34 110 28-80 18 25h308" fill="none" stroke="#FFFFFF"
 stroke-opacity="0.16" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


def svg_data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def hero_banner_html(month_range: tuple[str, str]) -> str:
    first, last = (pd.Period(month).strftime("%b %Y") for month in month_range)
    chips = [f"{first} – {last}", "16 federal states", "6 train types"]
    chip_html = "".join(f'<span class="bp-chip">{html.escape(chip)}</span>' for chip in chips)
    return f"""
<div class="bp-hero" style="background-image:url('{svg_data_uri(BANNER_PULSE_SVG)}'),
     linear-gradient(115deg, #EC0016 0%, #B3001B 55%, #6E1424 100%);">
  <img class="bp-logo" src="{svg_data_uri(LOGO_SVG)}" alt="BahnPulse logo">
  <div class="bp-hero-text">
    <div class="bp-hero-title">BahnPulse</div>
    <div class="bp-hero-sub">How punctual are Deutsche Bahn trains across Germany?</div>
    <div class="bp-chips">{chip_html}</div>
  </div>
</div>
<style>
.bp-hero {{
  display: flex; align-items: center; gap: 1.25rem; padding: 1.6rem 1.8rem;
  border-radius: 16px; color: #FFFFFF; background-size: 70% auto, cover;
  background-repeat: no-repeat; background-position: right center, center;
  box-shadow: 0 10px 30px rgba(236, 0, 22, 0.18); font-family: "Helvetica Neue",
  Helvetica, Arial, sans-serif; flex-wrap: wrap;
}}
.bp-logo {{ width: 64px; height: 64px; flex: none;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18); border-radius: 16px; }}
.bp-hero-text {{ flex: 1; min-width: 14rem; }}
.bp-hero-title {{ font-size: 2.1rem; font-weight: 800; letter-spacing: -0.02em; line-height: 1.1; }}
.bp-hero-sub {{ font-size: 1rem; opacity: 0.92; margin: 0.25rem 0 0.7rem; }}
.bp-chips {{ display: flex; flex-wrap: wrap; gap: 0.4rem; }}
.bp-chip {{
  font-size: 0.78rem; padding: 0.22rem 0.65rem; border-radius: 999px;
  background: rgba(255, 255, 255, 0.16); border: 1px solid rgba(255, 255, 255, 0.28);
}}
</style>
"""


# Plotly pins a hover label to its data point (a bar end, a cell centre). This moves every
# Plotly hover label to the mouse pointer instead, and keeps it there while Plotly redraws.
PLOTLY_HOVER_FOLLOW_JS = """
<script>
(() => {
  if (window.bpHoverFollow) return;
  window.bpHoverFollow = true;
  const cursor = new WeakMap();
  const watched = new WeakSet();
  const place = (plot) => {
    const at = cursor.get(plot);
    const layer = plot.querySelector(".hoverlayer");
    if (!at || !layer || !layer.ownerSVGElement) return;
    const box = layer.ownerSVGElement.getBoundingClientRect();
    const transform = `translate(${at.x - box.left},${at.y - box.top})`;
    layer.querySelectorAll(":scope > .hovertext").forEach((label) => {
      if (label.getAttribute("transform") !== transform) label.setAttribute("transform", transform);
    });
  };
  document.addEventListener("mousemove", (event) => {
    const plot = event.target.closest && event.target.closest(".js-plotly-plot");
    if (!plot) return;
    cursor.set(plot, { x: event.clientX, y: event.clientY });
    const layer = plot.querySelector(".hoverlayer");
    if (layer && !watched.has(layer)) {
      watched.add(layer);
      new MutationObserver(() => place(plot)).observe(layer, {
        childList: true, subtree: true, attributes: true, attributeFilter: ["transform"],
      });
    }
    place(plot);
  }, true);
})();
</script>
"""


# Streamlit does not rerun the script when the viewer switches light/dark, so the charts
# and cards drawn here would keep the old colors. This compares the page background with
# the mode the script last drew (--bp-mode) and clicks a hidden button to rerun on a change.
THEME_SYNC_JS = """
<script>
(() => {
  if (window.bpThemeSync) return;
  window.bpThemeSync = true;
  let lastClick = 0;
  setInterval(() => {
    const app = document.querySelector(".stApp");
    const button = document.querySelector(".st-key-bp_theme_sync button");
    const drawn = getComputedStyle(document.documentElement).getPropertyValue("--bp-mode").trim();
    if (!app || !button || !drawn) return;
    const [r, g, b] = getComputedStyle(app).backgroundColor.match(/\\d+/g).map(Number);
    const shown = 0.299 * r + 0.587 * g + 0.114 * b < 128 ? "dark" : "light";
    if (shown !== drawn && Date.now() - lastClick > 3000) {
      lastClick = Date.now();
      button.click();
    }
  }, 400);
})();
</script>
"""


def app_css() -> str:
    colors = palette()
    mode = "dark" if colors is THEME_COLORS["dark"] else "light"
    return f"""
<style>
:root {{ --bp-mode: {mode}; }}
.st-key-bp_theme_sync {{ display: none; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stCaptionContainer"] p {{ color: {colors["muted"]}; }}
/* KPI cards */
[data-testid="stMetric"] {{
  background: {colors["card"]}; border-radius: 14px; padding: 14px 16px 10px;
  border-left: 4px solid #EC0016; box-shadow: 0 4px 18px {colors["shadow"]};
}}
[data-testid="stMetric"] [data-testid="stMetricLabel"] p {{
  color: {colors["muted"]}; font-weight: 500;
}}
/* Section cards: keyed containers (st-key-card_*) become cards on the page background */
[class*="st-key-card_"] {{
  background: {colors["card"]}; border: none !important; border-radius: 16px;
  box-shadow: 0 4px 22px {colors["shadow"]}; padding: 1rem 1.1rem;
}}
/* The "Lowest" callout inside the ranking card gets a soft red tint */
[class*="st-key-callout_"] {{
  background: {colors["callout"]}; border: none !important; border-radius: 12px;
  padding: 0.6rem 0.9rem;
}}
/* Section titles with a red accent */
[data-testid="stHeadingWithActionElements"] h3 {{
  border-left: 4px solid #EC0016; padding-left: 0.6rem; font-size: 1.35rem;
}}
</style>
"""


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
        (metric_columns[2], "Cancelled stops", "cancelled", "%", " pts", False,
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
            "Share of arrivals under 6 minutes late · darker red = fewer trains on time · "
            "gray = no data"
        )
        st.caption(
            f"Showing {', '.join(selected_groups)} only: states are compared within the same "
            "train type, because a state with many S-Bahn trains is not comparable with one "
            "served mostly by long-distance trains."
            + (" Mixing train types weakens that comparison." if len(selected_groups) > 1 else "")
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
        st.caption(
            "Share of planned arrivals, cancelled ones included, so “on time” here is a little "
            "lower than the headline figure, which leaves cancellations out (DB definition)."
        )
        donut_column, bars_column = st.columns([1, 1.6])
        with donut_column:
            # Iframes keep the SVG (st.html strips it) and the cursor-following tooltips.
            components.html(delay_donut_html(delay_breakdown(in_area(selected_states))), height=430)
        with bars_column:
            period_states = state_frame.loc[
                state_frame["service_month_label"].between(first_month, last_month)
            ]
            components.html(
                delay_bars_html(delay_breakdown(in_area(period_states), by="train_group")),
                height=365,
            )
            st.caption("All train types side by side, whatever the train type filter")

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


def state_map(states: dict, state_summary: pd.DataFrame, highlight: str | None) -> go.Figure:
    colors = palette()
    map_data = pd.DataFrame(
        {"federal_state": [f["properties"]["name"] for f in states["features"]]}
    ).merge(state_summary, on="federal_state", how="left")
    with_data = map_data.dropna(subset=["punctuality_pct"])
    no_data = map_data.loc[map_data["punctuality_pct"].isna()]
    low = 5 * math.floor(with_data["punctuality_pct"].min() / 5)
    high = 5 * math.ceil(with_data["punctuality_pct"].max() / 5)
    if high <= low:
        high = low + 5
    figure = px.choropleth(
        with_data,
        geojson=states,
        locations="federal_state",
        featureidkey="properties.name",
        color="punctuality_pct",
        color_continuous_scale=DB_RED_SCALE,
        range_color=(low, high),
        custom_data=["avg_arrival_delay_min", "cancellation_pct", "planned_stop_count"],
    )
    figure.update_traces(
        hovertemplate=(
            "<b>%{location}</b><br>"
            "On time: %{z:.1f}%<br>"
            "Avg delay: %{customdata[0]:.1f} min<br>"
            "Cancelled: %{customdata[1]:.1f}%<br>"
            "Planned stops: %{customdata[2]:,}<extra></extra>"
        )
    )
    if not no_data.empty:
        figure.add_trace(
            go.Choropleth(
                geojson=states,
                locations=no_data["federal_state"],
                featureidkey="properties.name",
                z=[0] * len(no_data),
                colorscale=[[0, colors["line"]], [1, colors["line"]]],
                showscale=False,
                hovertemplate="<b>%{location}</b><br>No data<extra></extra>",
            )
        )
    figure.update_traces(marker_line_color=colors["card"], marker_line_width=1.5)
    if highlight:
        # Transparent fill with a dark outline marks the selected state.
        figure.add_trace(
            go.Choropleth(
                geojson=states,
                locations=[highlight],
                featureidkey="properties.name",
                z=[0],
                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
                showscale=False,
                marker_line_color=colors["ink"],
                marker_line_width=3,
                hoverinfo="skip",
            )
        )
    figure.update_geos(fitbounds="locations", visible=False, projection_type="mercator")
    figure.update_layout(
        height=560,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        geo_bgcolor="rgba(0,0,0,0)",
        font_color=colors["ink"],
        hoverlabel=hover_label(),
        coloraxis_colorbar={"title": "On time", "ticksuffix": "%", "thickness": 14},
    )
    return figure


def delay_breakdown(frame: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Long table of delay buckets with counts and shares of planned arrivals."""
    columns = [column for column, _, _ in DELAY_BUCKETS]
    labels = {column: label for column, label, _ in DELAY_BUCKETS}
    totals = (
        frame.groupby(by, as_index=False)[columns].sum()
        if by
        else frame[columns].sum().to_frame().T
    )
    long = totals.melt(
        id_vars=[by] if by else [], value_vars=columns, var_name="bucket", value_name="count"
    )
    long["bucket"] = long["bucket"].map(labels)
    long["count"] = long["count"].astype("int64")
    totals_per_row = (
        long.groupby(by)["count"].transform("sum")
        if by
        else pd.Series(long["count"].sum(), index=long.index)
    )
    long["share_pct"] = 100 * long["count"] / totals_per_row.replace(0, math.nan)
    return long


def mix_color(color: str, other: str, amount: float) -> str:
    """Blend two hex colors; amount 0 keeps `color`, 1 gives `other`."""
    a = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02X}" for x, y in zip(a, b, strict=True))


def delay_donut_html(breakdown: pd.DataFrame) -> str:
    """Shaded SVG donut: each ring slice is darker at its edges and lighter in the middle."""
    colors = {label: color for _, label, color in DELAY_BUCKETS}
    theme = palette()
    total = int(breakdown["count"].sum())
    if not total:
        return "<p>No arrivals for this selection.</p>"
    center, outer, inner = 160, 150, 92
    middle = (inner + outer) / 2 / outer

    def point(radius: float, angle: float) -> str:
        return (
            f"{center + radius * math.cos(angle):.2f} {center + radius * math.sin(angle):.2f}"
        )

    defs, slices = [], []
    angle = -math.pi / 2  # start at 12 o'clock, run clockwise
    rows = list(
        zip(breakdown["bucket"], breakdown["count"], breakdown["share_pct"], strict=True)
    )
    for index, (bucket, count, share) in enumerate(rows):
        if not count:
            continue
        sweep = min(2 * math.pi * count / total, 2 * math.pi - 1e-4)
        end = angle + sweep
        large = 1 if sweep > math.pi else 0
        color = colors[bucket]
        gradient = f"bp-donut-{index}"
        edge = mix_color(color, DONUT_EDGE, DONUT_EDGE_AMOUNT)
        defs.append(
            f'<radialGradient id="{gradient}" gradientUnits="userSpaceOnUse" '
            f'cx="{center}" cy="{center}" r="{outer}">'
            f'<stop offset="{inner / outer:.3f}" stop-color="{edge}"/>'
            f'<stop offset="{middle:.3f}" stop-color="{mix_color(color, "#FFFFFF", 0.3)}"/>'
            f'<stop offset="1" stop-color="{edge}"/>'
            "</radialGradient>"
        )
        slices.append(
            f'<path d="M {point(outer, angle)} A {outer} {outer} 0 {large} 1 {point(outer, end)} '
            f'L {point(inner, end)} A {inner} {inner} 0 {large} 0 {point(inner, angle)} Z" '
            f'fill="url(#{gradient})" '
            f'data-tip="{tooltip_text(bucket, share, count)}"></path>'
        )
        angle = end

    on_time = breakdown["share_pct"].iloc[0]
    legend = "".join(
        f'<span class="bp-donut-key"><i style="background:{colors[bucket]}"></i>'
        f"{html.escape(bucket)} · <b>{share:.1f}%</b></span>"
        for bucket, _, share in rows
    )
    return f"""
<style>
body {{ margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }}
.bp-donut {{ display: flex; flex-direction: column; align-items: center; gap: 0.75rem; }}
.bp-donut svg {{ width: 100%; max-width: 300px; height: auto; }}
.bp-donut path {{ stroke: {theme["card"]}; stroke-width: 1.5; transition: filter 0.15s; }}
.bp-donut path:hover {{ filter: brightness(1.12); }}
.bp-donut-legend {{
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.3rem 1rem;
    font-size: 0.8rem; color: {theme["ink"]};
}}
.bp-donut-key {{ display: flex; align-items: center; gap: 0.4rem; white-space: nowrap; }}
.bp-donut-key i {{ width: 0.7rem; height: 0.7rem; border-radius: 2px; flex: none; }}
</style>
<div class="bp-donut">
<svg viewBox="0 0 320 320" role="img"
     aria-label="{on_time:.1f}% of planned arrivals on time">
<defs>{"".join(defs)}</defs>
{"".join(slices)}
<text x="160" y="158" text-anchor="middle" font-size="34" font-weight="700"
      fill="{theme["ink"]}">{on_time:.1f}%</text>
<text x="160" y="184" text-anchor="middle" font-size="14" fill="{theme["muted"]}">on time</text>
</svg>
<div class="bp-donut-legend">{legend}</div>
</div>
{tooltip_assets()}
"""


def delay_bars_html(breakdown: pd.DataFrame) -> str:
    """100% stacked bars per train type, drawn in HTML so the tooltip follows the cursor."""
    colors = {label: color for _, label, color in DELAY_BUCKETS}
    theme = palette()
    groups = [group for group in GROUP_ORDER if group in breakdown["train_group"].unique()]
    rows = []
    for group in groups:
        part = breakdown.loc[breakdown["train_group"] == group]
        segments = []
        parts = zip(part["bucket"], part["count"], part["share_pct"], strict=True)
        for bucket, count, share in parts:
            if not count:
                continue
            color = colors[bucket]
            segments.append(
                f'<div class="bp-seg" style="width:{share:.3f}%;background:{color};'
                f'color:{text_color_on(color)}" '
                f'data-tip="{tooltip_text(bucket, share, count, group)}">'
                f'{f"{share:.0f}%" if share >= 8 else ""}</div>'
            )
        rows.append(
            f'<div class="bp-row"><div class="bp-name">{html.escape(group)}</div>'
            f'<div class="bp-track">{"".join(segments)}</div></div>'
        )
    ticks = "".join(
        f'<span style="left:{tick}%">{tick}%</span>' for tick in range(0, 101, 20)
    )
    return f"""
<style>
body {{
    margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color: {theme["ink"]};
}}
.bp-bars {{ display: flex; flex-direction: column; gap: 0.6rem; padding: 0.5rem 1.2rem 0 0; }}
.bp-row {{ display: flex; align-items: center; gap: 0.75rem; }}
.bp-name {{
    width: 3.2rem; text-align: right; font-size: 0.85rem; color: {theme["muted"]}; flex: none;
}}
.bp-track {{ flex: 1; display: flex; height: 2.6rem; }}
.bp-seg {{
    display: flex; align-items: center; justify-content: center; font-size: 0.8rem;
    box-shadow: inset -1.5px 0 0 {theme["card"]}; overflow: hidden; white-space: nowrap;
    transition: filter 0.15s;
}}
.bp-seg:hover {{ filter: brightness(1.1); }}
.bp-axis {{ position: relative; height: 1.2rem; margin-left: 3.95rem; font-size: 0.75rem;
           color: {theme["muted"]}; }}
.bp-axis span {{ position: absolute; transform: translateX(-50%); }}
</style>
<div class="bp-bars">{"".join(rows)}<div class="bp-axis">{ticks}</div></div>
{tooltip_assets()}
"""


def tooltip_text(bucket: str, share: float, count: int, group: str | None = None) -> str:
    """Tooltip HTML, escaped for use inside a data-tip attribute."""
    title = f"{group} · {bucket}" if group else bucket
    return html.escape(
        f"<b>{html.escape(title)}</b><br>{share:.1f}% of planned arrivals<br>{count:,} arrivals"
    )


def text_color_on(color: str) -> str:
    """Dark ink on light fills, white on dark fills."""
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return DB_INK if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else "#FFFFFF"


# Shared tooltip for the HTML charts: appears instantly and follows the cursor, flipping
# sides near the frame edges so it never gets cut off.
def tooltip_assets() -> str:
    colors = palette()
    return f"""
<style>
.bp-tip {{
    position: fixed; z-index: 10; pointer-events: none; background: {colors["card"]};
    border: 1px solid {colors["line"]}; border-radius: 4px; padding: 0.4rem 0.6rem;
    font: 0.8rem/1.4 "Helvetica Neue", Helvetica, Arial, sans-serif; color: {colors["ink"]};
    box-shadow: 0 2px 8px rgba(40, 45, 55, 0.15); white-space: nowrap;
}}
</style>
<div class="bp-tip" hidden></div>
<script>
const tip = document.querySelector(".bp-tip");
document.querySelectorAll("[data-tip]").forEach((el) => {{
  el.addEventListener("mousemove", (event) => {{
    tip.innerHTML = el.dataset.tip;
    tip.hidden = false;
    const gap = 12, box = tip.getBoundingClientRect();
    let x = event.clientX + gap, y = event.clientY + gap;
    if (x + box.width > window.innerWidth) x = event.clientX - box.width - gap;
    if (y + box.height > window.innerHeight) y = event.clientY - box.height - gap;
    tip.style.left = Math.max(0, x) + "px";
    tip.style.top = Math.max(0, y) + "px";
  }});
  el.addEventListener("mouseleave", () => {{ tip.hidden = true; }});
}});
</script>
"""


def hour_weekday_heatmap(frame: pd.DataFrame) -> tuple[go.Figure | None, str, str]:
    """On-time share by weekday and hour; sparse cells are left blank."""
    grid = frame.groupby(["iso_weekday", "service_hour"])[
        ["arrival_count", "on_time_arrival_count"]
    ].sum()
    grid = grid.loc[grid["arrival_count"] >= MIN_HEATMAP_ARRIVALS]
    if grid.empty:
        return None, "", ""
    grid["punctuality_pct"] = 100 * grid["on_time_arrival_count"] / grid["arrival_count"]
    full_index = pd.MultiIndex.from_product([range(1, 8), range(24)])
    pct = grid["punctuality_pct"].reindex(full_index).unstack()
    arrivals = grid["arrival_count"].reindex(full_index).unstack()

    def slot(position: tuple[int, int]) -> str:
        day, hour = position
        return f"{WEEKDAYS[day - 1]} {hour:02d}:00 ({grid.loc[position, 'punctuality_pct']:.0f}%)"

    best = slot(cast(tuple[int, int], grid["punctuality_pct"].idxmax()))
    worst = slot(cast(tuple[int, int], grid["punctuality_pct"].idxmin()))
    low = 5 * math.floor(grid["punctuality_pct"].min() / 5)
    high = 5 * math.ceil(grid["punctuality_pct"].max() / 5)
    figure = go.Figure(
        go.Heatmap(
            z=pct.values,
            x=list(range(24)),
            y=WEEKDAYS,
            customdata=arrivals.values,
            colorscale=DB_RED_SCALE,
            zmin=low,
            zmax=high if high > low else low + 5,
            xgap=2,
            ygap=2,
            hoverongaps=False,
            colorbar={"title": "On time", "ticksuffix": "%", "thickness": 14},
            hovertemplate=(
                "<b>%{y} %{x:02d}:00–%{x:02d}:59</b><br>On time: %{z:.1f}%<br>"
                "Arrivals: %{customdata:,}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        height=300,
        margin={"l": 8, "r": 8, "t": 10, "b": 8},
        xaxis={
            "title": "Planned arrival hour",
            "tickvals": list(range(0, 24, 3)),
            "ticktext": [f"{hour:02d}:00" for hour in range(0, 24, 3)],
            "showgrid": False,
        },
        yaxis={"autorange": "reversed", "showgrid": False},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color=palette()["ink"],
        hoverlabel=hover_label(),
    )
    return figure, best, worst


def monthly_trend(
    selected_states: pd.DataFrame, area: str | None, gaps: dict[str, int] | None = None
) -> go.Figure:
    """Train-type lines by month; with a state, solid state lines over dotted Germany lines."""
    colors = palette()
    monthly = summarize_national_months(selected_states).assign(scope="Germany")
    if area:
        state_monthly = summarize_national_months(
            selected_states.loc[selected_states["federal_state"] == area]
        ).assign(scope=area)
        monthly = pd.concat([state_monthly, monthly], ignore_index=True)
    monthly["service_month"] = pd.to_datetime(monthly["service_month_label"])
    trend = px.line(
        monthly,
        x="service_month",
        y="punctuality_pct",
        color="train_group",
        line_dash="scope" if area else None,
        line_dash_map={area: "solid", "Germany": "dot"} if area else None,
        markers=True,
        category_orders={"train_group": GROUP_ORDER, "scope": [area, "Germany"] if area else []},
        color_discrete_map=group_colors(),
    )
    trend.update_traces(
        line_width=2,
        marker_size=8,
        hovertemplate=(
            "<b>%{fullData.name}</b><br>%{x|%b %Y}<br>On time: %{y:.1f}%<extra></extra>"
        ),
    )
    if area:
        trend.update_traces(selector={"line": {"dash": "dot"}}, marker_size=5, opacity=0.75)
    trend.update_xaxes(tickformat="%b %Y", dtick="M1")
    # Shade months with data gaps so a dip there is not read as a real change.
    for month in gaps or {}:
        start = pd.Period(month).start_time
        trend.add_vrect(
            x0=start - pd.Timedelta(days=12),
            x1=start + pd.Timedelta(days=12),
            fillcolor=colors["line"],
            opacity=0.45,
            line_width=0,
            layer="below",
            annotation_text="partial data",
            annotation_position="top",
            annotation_font={"size": 11, "color": colors["muted"]},
        )
    trend.update_layout(
        height=340,
        margin={"l": 8, "r": 8, "t": 12, "b": 8},
        xaxis_title=None,
        yaxis_title="On-time arrivals (%)",
        legend_title=None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=hover_label(),
    )
    trend.update_yaxes(gridcolor=colors["line"])
    trend.update_xaxes(showgrid=False)
    return trend


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
        selected_slot = st.segmented_control("Time slot", slots, default="All day")
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


def data_gaps(coverage: pd.DataFrame, month_range: tuple[str, str]) -> dict[str, int]:
    """Months in the selected range with many low-data hours: {"2026-07": 55, ...}."""
    labels = pd.to_datetime(coverage["service_month"]).dt.strftime("%Y-%m")
    in_range = labels.between(*month_range) & (coverage["low_data_hours"] >= GAP_HOURS_WARN)
    return dict(zip(labels[in_range], coverage.loc[in_range, "low_data_hours"], strict=True))


def load_run_status() -> dict:
    status_path = PUBLISHED / "run_status.json"
    return json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}


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