"""Map, delay donut and bars, hour x weekday heatmap and monthly trend."""

from __future__ import annotations

import html
import math
from itertools import pairwise
from typing import cast

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dbp.dashboard.data import GROUP_ORDER, summarize_months
from dbp.dashboard.theme import (
    DB_INK,
    DB_RED,
    DB_RED_SCALE,
    DELAY_BUCKETS,
    DONUT_EDGE,
    DONUT_EDGE_AMOUNT,
    hover_label,
    palette,
)

MIN_HEATMAP_ARRIVALS = 50
# States with fewer arrivals in a month stay out of the trend's state range (too noisy).
MIN_RANGE_ARRIVALS = 500
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
        height=640,
        margin={"l": 0, "r": 0, "t": 0, "b": 60},
        paper_bgcolor="rgba(0,0,0,0)",
        geo_bgcolor="rgba(0,0,0,0)",
        font_color=colors["ink"],
        hoverlabel=hover_label(),
        # Legend under the map, so the map gets the card's full width.
        coloraxis_colorbar={
            "title": {"text": "On time", "side": "top"},
            "ticksuffix": "%",
            "thickness": 10,
            "orientation": "h",
            "len": 0.7,
            "x": 0.5,
            "y": -0.02,
            "yanchor": "top",
        },
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


def cancel_ticks(values: list[float]) -> tuple[float, float]:
    """Axis maximum and a round tick step, with room past the largest value for its label."""
    top = max(max(values, default=0) * 1.15, 1)
    step = next(step for step in (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50) if top / step <= 5)
    return step * math.ceil(top / step), step


def cancel_axis_html(scale: float, step: float, inset: str) -> str:
    ticks = "".join(
        f'<span style="left:{100 * step * index / scale:.2f}%">{step * index:g}%</span>'
        for index in range(round(scale / step) + 1)
    )
    return f'<div class="bp-axis" style="margin-left:{inset}">{ticks}</div>'


def cancel_bars_html(
    rows: pd.DataFrame, worst_label: str, reference: str | None = None, scope: str = ""
) -> str:
    """Ranked bars of the cancelled share per item (train type, station or line), worst first.

    `rows` holds item, stops, cancelled, cancelled_pct and a `worst` text (worst week or
    month) for the tooltip. With `reference` (e.g. "Germany"), a ref_pct column is drawn as
    a marker on each bar so a state can be read against the national rate.
    """
    theme = palette()
    ref_color = theme["trend"][4]
    has_ref = reference is not None and "ref_pct" in rows
    values = rows["cancelled_pct"].tolist() + (rows["ref_pct"].dropna().tolist() if has_ref else [])
    scale, step = cancel_ticks(values)
    sheen = (
        f"linear-gradient(180deg, {mix_color(DB_RED, '#FFFFFF', 0.18)} 0%, {DB_RED} 55%, "
        f"{mix_color(DB_RED, DONUT_EDGE, 0.3)} 100%)"
    )
    name_width = "9.5rem" if rows["item"].str.len().max() > 6 else "3.2rem"
    lines = []
    for row in rows.itertuples():
        title = f"{row.item} · {scope}" if scope else row.item
        tip = (
            f"<b>{html.escape(title)}</b><br>{row.cancelled_pct:.1f}% of stops cancelled<br>"
            f"{row.cancelled:,} of {row.stops:,} stops"
        )
        marker = ""
        if has_ref and not pd.isna(row.ref_pct):
            tip += (
                f"<br>{html.escape(reference)}: {row.ref_pct:.1f}% "
                f"({row.cancelled_pct - row.ref_pct:+.1f} pts)"
            )
            marker = (
                f'<span class="bp-ref" style="left:{100 * row.ref_pct / scale:.2f}%"></span>'
            )
        if row.worst:
            tip += f"<br>{html.escape(worst_label)}: {html.escape(row.worst)}"
        lines.append(
            f'<div class="bp-row" data-tip="{html.escape(tip)}">'
            f'<div class="bp-name" title="{html.escape(row.item)}">{html.escape(row.item)}</div>'
            f'<div class="bp-track"><div class="bp-bar" '
            f'style="width:{100 * row.cancelled_pct / scale:.2f}%"></div>'
            f'<span class="bp-value">{row.cancelled_pct:.1f}%</span>{marker}</div></div>'
        )
    legend = (
        f'<div class="bp-legend" style="margin-left:calc({name_width} + 0.75rem)">'
        f'<span><i class="bp-key-bar"></i>{html.escape(scope)}</span>'
        f'<span><i class="bp-key-ref"></i>{html.escape(reference)}</span></div>'
        if has_ref
        else ""
    )
    return f"""
<style>
body {{
    margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color: {theme["ink"]};
}}
.bp-chart {{ display: flex; flex-direction: column; gap: 0.45rem; padding: 0.4rem 1.2rem 0 0; }}
.bp-row {{ display: flex; align-items: center; gap: 0.75rem; }}
.bp-name {{
    width: {name_width}; text-align: right; font-size: 0.85rem; color: {theme["muted"]};
    flex: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.bp-track {{
    flex: 1; position: relative; display: flex; align-items: center; gap: 0.5rem;
    height: 1.9rem;
}}
.bp-bar {{
    height: 100%; background: {sheen}; border-radius: 0 6px 6px 0; min-width: 2px;
    transition: filter 0.15s;
}}
.bp-row:hover .bp-bar {{ filter: brightness(1.12); }}
.bp-value {{ font-size: 0.82rem; font-weight: 700; color: {DB_RED}; white-space: nowrap; }}
.bp-ref {{
    position: absolute; top: -3px; bottom: -3px; width: 4px; margin-left: -2px;
    background: {ref_color}; border-radius: 2px; box-shadow: 0 0 0 1.5px {theme["card"]};
}}
.bp-axis {{ position: relative; height: 1.2rem; font-size: 0.75rem; color: {theme["muted"]}; }}
.bp-axis span {{ position: absolute; transform: translateX(-50%); }}
.bp-legend {{ display: flex; gap: 1.2rem; font-size: 0.8rem; margin-top: 0.3rem; }}
.bp-legend span {{ display: flex; align-items: center; gap: 0.4rem; }}
.bp-key-bar {{ width: 14px; height: 10px; border-radius: 2px; background: {DB_RED}; }}
.bp-key-ref {{ width: 4px; height: 14px; border-radius: 2px; background: {ref_color}; }}
</style>
<div class="bp-chart">{"".join(lines)}
{cancel_axis_html(scale, step, f"calc({name_width} + 0.75rem)")}{legend}</div>
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


def rgba(color: str, alpha: float) -> str:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def spread_labels(values: list[float], gap: float) -> list[float]:
    """Nudge end-of-line label heights apart so close values do not overlap."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    placed = list(values)
    for previous, current in pairwise(order):
        placed[current] = max(placed[current], placed[previous] + gap)
    return placed


def monthly_trend(
    selected_states: pd.DataFrame, area: str | None, gaps: dict[str, int] | None = None
) -> go.Figure:
    """On-time lines per train type over the range across states, average delay bars below.

    With a state chosen, its lines are solid and Germany's dotted. The state band is drawn
    only for a single train type, where it stays readable.
    """
    colors = palette()
    focus = (
        selected_states.loc[selected_states["federal_state"] == area] if area else selected_states
    )
    lines = summarize_months(focus, ["train_group"])
    germany = summarize_months(selected_states, ["train_group"]) if area else None
    per_state = summarize_months(selected_states, ["train_group", "federal_state"])
    per_state = per_state.loc[per_state["arrival_count"] >= MIN_RANGE_ARRIVALS]
    delays = summarize_months(focus, [])
    groups = [group for group in GROUP_ORDER if group in set(lines["train_group"])]
    type_colors = dict(zip(groups, colors["trend"], strict=False))
    single = len(groups) == 1
    to_date = lambda labels: pd.to_datetime(labels)  # noqa: E731
    gap_note = lambda labels: [  # noqa: E731
        "<br><i>Incomplete month: some data missing</i>" if label in (gaps or {}) else ""
        for label in labels
    ]

    figure = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.74, 0.26], vertical_spacing=0.05
    )
    end_labels = []
    for group in groups:
        color = type_colors[group]
        line = lines.loc[lines["train_group"] == group].sort_values("service_month_label")
        states = per_state.loc[per_state["train_group"] == group]
        low = states.loc[states.groupby("service_month_label")["punctuality_pct"].idxmin()]
        high = states.loc[states.groupby("service_month_label")["punctuality_pct"].idxmax()]
        state_range = (
            low.set_index("service_month_label")[["federal_state", "punctuality_pct"]]
            .join(
                high.set_index("service_month_label")[["federal_state", "punctuality_pct"]],
                lsuffix="_low",
                rsuffix="_high",
            )
            .reindex(line["service_month_label"])
        )
        if single and not state_range.empty:
            band_x = to_date(state_range.index)
            figure.add_scatter(
                x=band_x,
                y=state_range["punctuality_pct_high"],
                mode="lines",
                line={"width": 0, "shape": "spline", "smoothing": 0.6},
                hoverinfo="skip",
                showlegend=False,
                row=1,
                col=1,
            )
            figure.add_scatter(
                x=band_x,
                y=state_range["punctuality_pct_low"],
                mode="lines",
                line={"width": 0, "shape": "spline", "smoothing": 0.6},
                fill="tonexty",
                fillcolor=rgba(color, 0.22),
                name="Range across states",
                hoverinfo="skip",
                row=1,
                col=1,
            )
        if germany is not None:
            national = germany.loc[germany["train_group"] == group].sort_values(
                "service_month_label"
            )
            figure.add_scatter(
                x=to_date(national["service_month_label"]),
                y=national["punctuality_pct"],
                mode="lines",
                name="Germany" if single else f"{group} · Germany",
                line={
                    "color": color,
                    "width": 2.2,
                    "dash": "dot",
                    "shape": "spline",
                    "smoothing": 0.6,
                },
                opacity=0.9,
                hovertemplate="<b>%{fullData.name}</b><br>%{x|%b %Y}<br>"
                "On time: %{y:.1f}%<extra></extra>",
                row=1,
                col=1,
            )
            end_labels.append((national, color, 0.9))
        change = line["punctuality_pct"].diff()
        range_text = [
            ""
            if pd.isna(row.punctuality_pct_low)
            else f"<br>States: {row.federal_state_low} {row.punctuality_pct_low:.0f}% – "
            f"{row.federal_state_high} {row.punctuality_pct_high:.0f}%"
            for row in state_range.itertuples()
        ]
        figure.add_scatter(
            x=to_date(line["service_month_label"]),
            y=line["punctuality_pct"],
            mode="lines+markers",
            name=(area if single else f"{group} · {area}") if area else group,
            line={"color": color, "width": 3, "shape": "spline", "smoothing": 0.6},
            marker={"size": 8, "color": color, "line": {"color": colors["card"], "width": 2}},
            customdata=list(
                zip(
                    line["avg_arrival_delay_min"],
                    ["" if pd.isna(c) else f" ({c:+.1f} pts)" for c in change],
                    range_text,
                    gap_note(line["service_month_label"]),
                    strict=True,
                )
            ),
            hovertemplate="<b>%{fullData.name}</b> · %{x|%b %Y}<br>"
            "On time: %{y:.1f}%%{customdata[1]}<br>"
            "Avg delay: %{customdata[0]:.1f} min%{customdata[2]}%{customdata[3]}<extra></extra>",
            row=1,
            col=1,
        )
        end_labels.append((line, color, 1.0))
        line_months = line["service_month_label"].tolist()
        if single and len(line_months) >= 3:
            for label, row in (
                ("Best", line.loc[line["punctuality_pct"].idxmax()]),
                ("Worst", line.loc[line["punctuality_pct"].idxmin()]),
            ):
                # Labels on the first or last month point inward, away from the axis.
                position = line_months.index(row["service_month_label"])
                figure.add_annotation(
                    x=to_date([row["service_month_label"]])[0],
                    y=row["punctuality_pct"],
                    text=f"{label} {row['punctuality_pct']:.1f}%",
                    showarrow=False,
                    yshift=16 if label == "Best" else -16,
                    xanchor="left" if position == 0 else "center",
                    xshift=-4 if position == 0 else 0,
                    font={"size": 11, "color": colors["muted"]},
                    row=1,
                    col=1,
                )

    # Latest value at the end of each line, nudged apart where lines end close together.
    end_labels = [
        (frame.dropna(subset=["punctuality_pct"]), color, opacity)
        for frame, color, opacity in end_labels
    ]
    end_labels = [entry for entry in end_labels if not entry[0].empty]
    values = pd.concat([frame["punctuality_pct"] for frame, _, _ in end_labels] or [pd.Series()])
    span = float(values.max() - values.min()) if len(values) else 0.0
    heights = spread_labels(
        [frame["punctuality_pct"].iloc[-1] for frame, _, _ in end_labels], max(span, 4) * 0.07
    )
    for (frame, color, opacity), height in zip(end_labels, heights, strict=True):
        figure.add_annotation(
            x=to_date([frame["service_month_label"].iloc[-1]])[0],
            y=height,
            text=f"<b>{frame['punctuality_pct'].iloc[-1]:.1f}%</b>",
            showarrow=False,
            xanchor="left",
            xshift=10,
            opacity=opacity,
            font={"size": 12, "color": color},
            row=1,
            col=1,
        )

    figure.add_bar(
        x=to_date(delays["service_month_label"]),
        y=delays["avg_arrival_delay_min"],
        name="Avg delay",
        showlegend=False,
        marker={"color": rgba(DELAY_BUCKETS[3][2], 0.8), "cornerradius": 4},
        customdata=list(
            zip(delays["arrival_count"], gap_note(delays["service_month_label"]), strict=True)
        ),
        hovertemplate="<b>%{x|%b %Y}</b><br>Avg arrival delay: %{y:.1f} min<br>"
        "Arrivals: %{customdata[0]:,}%{customdata[1]}<extra></extra>",
        row=2,
        col=1,
    )

    months = to_date(delays["service_month_label"])
    first, last = months.min(), months.max()
    figure.update_xaxes(
        showgrid=False,
        tickformat="%b<br>%Y",
        dtick="M1",
        ticks="",
        range=[first - pd.Timedelta(days=12), last + pd.Timedelta(days=28)],
    )
    figure.update_yaxes(gridcolor=colors["line"], zeroline=False)
    figure.update_yaxes(title_text="On time (%)", ticksuffix="%", row=1, col=1)
    figure.update_yaxes(title_text="Delay (min)", nticks=3, row=2, col=1)
    figure.update_layout(
        height=470,
        margin={"l": 8, "r": 8, "t": 30, "b": 8},
        bargap=0.45,
        hovermode="closest",
        legend={"orientation": "h", "x": 0, "y": 1.08, "yanchor": "bottom", "title": None},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color=colors["ink"],
        hoverlabel=hover_label(),
    )
    return figure
