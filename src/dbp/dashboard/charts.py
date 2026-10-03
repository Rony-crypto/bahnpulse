"""Map, delay donut and bars, hour x weekday heatmap and monthly trend."""

from __future__ import annotations

import html
import math
from typing import cast

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from dbp.dashboard.data import GROUP_ORDER, summarize_national_months
from dbp.dashboard.theme import (
    DB_INK,
    DB_RED_SCALE,
    DELAY_BUCKETS,
    DONUT_EDGE,
    DONUT_EDGE_AMOUNT,
    group_colors,
    hover_label,
    palette,
)

MIN_HEATMAP_ARRIVALS = 50
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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
