"""DB colors, page CSS, the hero banner and the page-wide JavaScript helpers."""

from __future__ import annotations

import base64
import html

import pandas as pd
import streamlit as st

from dbp.dashboard.data import GROUP_ORDER

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
        # Monthly trend lines, in selection order: DB red, dark red, crimson, raspberry,
        # wine, plum.
        "trend": ["#EC0016", "#9B000E", "#B71D47", "#DB4568", "#851637", "#7A4A68"],
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
        "trend": ["#FF3B4A", "#FF7A85", "#E0607E", "#C2416A", "#F7A1B5", "#B286A8"],
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
/* Attribution line at the page bottom */
.bp-footer {{
  margin-top: 2rem; padding-top: 0.8rem; border-top: 1px solid {colors["line"]};
  text-align: center; font-size: 0.75rem; color: {colors["muted"]};
}}
.bp-footer a {{ color: {colors["muted"]}; }}
/* Section titles with a red accent */
[data-testid="stHeadingWithActionElements"] h3 {{
  border-left: 4px solid #EC0016; padding-left: 0.6rem; font-size: 1.35rem;
}}
</style>
"""
