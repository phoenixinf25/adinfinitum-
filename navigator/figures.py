# ruff: noqa: C408  (plotly layout kwargs are idiomatic as dict(...))
"""Plotly figures for the Navigator. Colour-blind-safe palette (Okabe-Ito); every figure states its provenance."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import plotly.graph_objects as go

from contracts.light import PointSeries
from contracts.tiles import Tile
from navigator.metrics import earth_up, sun_up

SUN, EARTH, BOTH, BLACKOUT, GROUND = "#E69F00", "#0072B2", "#009E73", "#D55E00", "#6b6b6b"


def _times(ps: PointSeries) -> list[datetime]:
    return [datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ") for t in ps.times_utc]


def timeline_figure(ps: PointSeries, i_now: int, k: int = 0, title: str = "") -> go.Figure:
    """Lunar-day timeline: when the Sun is up, Earth is visible, both, and when neither (blackout)."""
    s, e = sun_up(ps, k), earth_up(ps, k)
    rows = [("Sun up", s, SUN), ("Earth visible", e, EARTH), ("Sun + Earth", s & e, BOTH), ("Blackout", ~s & ~e, BLACKOUT)]
    x = _times(ps)
    fig = go.Figure()
    for name, mask, color in rows:
        fig.add_trace(go.Heatmap(x=x, y=[name], z=[mask.astype(int)], zmin=0, zmax=1, showscale=False,
                                 colorscale=[[0, "rgba(0,0,0,0.06)"], [1, color]], hovertemplate=f"{name}: %{{z}}<br>%{{x}}<extra></extra>"))
    fig.add_vline(x=x[i_now], line_width=2, line_dash="dot", line_color="#222")
    fig.update_layout(title=title, height=250, margin=dict(l=10, r=10, t=40, b=30), yaxis=dict(autorange="reversed"),
                      xaxis_title="UTC (1 h samples)")
    return fig


def _wrap_break(az: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Insert NaN where a track wraps around 360 -> 0 so the line does not cross the whole plot."""
    jump = np.flatnonzero(np.abs(np.diff(az)) > 180)
    return np.insert(az.astype(float), jump + 1, np.nan), np.insert(y.astype(float), jump + 1, np.nan)


def panorama_figure(ps: PointSeries, i_now: int, k: int = 0, title: str = "") -> go.Figure:
    """The horizon as seen from the site (azimuth along the bottom, elevation up) with Sun and Earth tracks for the window.
    At the poles the Sun stays within a few degrees of the horizon, so this flat view shows more than a dome."""
    az = np.arange(360)
    hor = ps.horizon_elev_deg[k]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=az, y=hor, mode="lines", line=dict(color=GROUND, width=1), name="Terrain horizon",
                             fill="tozeroy", fillcolor="rgba(107,107,107,0.55)", hoverinfo="skip"))
    for name, a, el, color in (("Sun", ps.sun_az_deg, ps.sun_elev_deg[:, k], SUN), ("Earth", ps.earth_az_deg, ps.earth_elev_deg[:, k], EARTH)):
        xa, ya = _wrap_break(a, el)
        fig.add_trace(go.Scatter(x=xa, y=ya, mode="lines", line=dict(color=color, width=1.5), opacity=0.45, name=f"{name} path (window)",
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[a[i_now]], y=[el[i_now]], mode="markers", name=f"{name} now", marker=dict(size=16, color=color, line=dict(width=2, color="#222")),
                                 hovertemplate=f"{name}: az %{{x:.0f}}°, elev %{{y:.1f}}°<extra></extra>"))
    top = float(max(ps.sun_elev_deg[:, k].max(), ps.earth_elev_deg[:, k].max(), hor.max(), 2.0)) + 2.0
    bot = float(min(ps.sun_elev_deg[:, k].min(), ps.earth_elev_deg[:, k].min(), hor.min(), -2.0)) - 1.0
    fig.update_layout(title=title, height=360, margin=dict(l=10, r=10, t=40, b=30), legend=dict(orientation="h", y=-0.25),
                      xaxis=dict(title="Azimuth (tile frame, 0 = up on the map, clockwise)", range=[0, 360], dtick=45),
                      yaxis=dict(title="Elevation (deg)", range=[bot, top]))
    return fig


def dome_figure(ps: PointSeries, i_now: int, k: int = 0, title: str = "") -> go.Figure:
    """Top-down sky dome: zenith in the centre, horizon at the rim. Terrain silhouette in grey."""
    hor = ps.horizon_elev_deg[k]
    fig = go.Figure()
    th = np.append(np.arange(360), 0)
    r_h = 90.0 - np.append(hor, hor[0])
    fig.add_trace(go.Scatterpolar(theta=th, r=r_h, mode="lines", fill="toself", fillcolor="rgba(107,107,107,0.35)",
                                  line=dict(color=GROUND), name="Terrain horizon", hoverinfo="skip"))
    for name, a, el, color in (("Sun", ps.sun_az_deg, ps.sun_elev_deg[:, k], SUN), ("Earth", ps.earth_az_deg, ps.earth_elev_deg[:, k], EARTH)):
        vis = el > -6.0
        xa, ya = _wrap_break(a[vis], 90.0 - el[vis])
        fig.add_trace(go.Scatterpolar(theta=xa, r=ya, mode="lines", line=dict(color=color, width=1.5), opacity=0.5, name=f"{name} path", hoverinfo="skip"))
        fig.add_trace(go.Scatterpolar(theta=[a[i_now]], r=[90.0 - el[i_now]], mode="markers", name=f"{name} now",
                                      marker=dict(size=15, color=color, line=dict(width=2, color="#222"))))
    fig.update_layout(title=title, height=420, margin=dict(l=30, r=30, t=50, b=20), legend=dict(orientation="h", y=-0.08),
                      polar=dict(angularaxis=dict(direction="clockwise", rotation=90, tickvals=[0, 90, 180, 270], ticktext=["0°", "90°", "180°", "270°"]),
                                 radialaxis=dict(range=[0, 96], tickvals=[0, 30, 60, 90], ticktext=["zenith", "60°", "30°", "horizon"])))
    return fig


def compare_bars(rows: list[dict]) -> go.Figure:
    """Grouped bars: Sun hours, Earth hours and both, per site/date."""
    fig = go.Figure()
    for key, label, color in (("Sun hours", "Sun up", SUN), ("Earth hours", "Earth visible", EARTH), ("Both hours", "Sun + Earth", BOTH),
                              ("Blackout hours", "Blackout", BLACKOUT)):
        fig.add_trace(go.Bar(x=[r["label"] for r in rows], y=[r[key] for r in rows], name=label, marker_color=color))
    fig.update_layout(barmode="group", height=340, margin=dict(l=10, r=10, t=30, b=30), yaxis_title="hours in the 29.5-day window",
                      legend=dict(orientation="h", y=-0.3))
    return fig


def tile_map_figure(tile: Tile, layer: str = "hazard", k_cell: tuple[int, int] | None = None, max_px: int = 400) -> go.Figure:
    """Terrain tile layer ('height', 'slope' or 'hazard'), downsampled for the browser; row 0 = north (up)."""
    arr = getattr(tile, layer).astype(np.float32)
    f = max(1, int(np.ceil(max(arr.shape) / max_px)))
    small = arr[::f, ::f]
    scale = {"height": "Gray", "slope": "Viridis", "hazard": "RdYlGn_r"}[layer]
    fig = go.Figure(go.Heatmap(z=small, colorscale=scale, colorbar=dict(title={"height": "m", "slope": "deg", "hazard": "P(unsafe)"}[layer]),
                               x=np.arange(small.shape[1]) * f * tile.meters_per_pixel, y=np.arange(small.shape[0]) * f * tile.meters_per_pixel))
    if k_cell is not None:
        fig.add_trace(go.Scatter(x=[k_cell[1] * tile.meters_per_pixel], y=[k_cell[0] * tile.meters_per_pixel], mode="markers",
                                 marker=dict(symbol="x", size=14, color="#fff", line=dict(width=2, color="#000")), name="Candidate cell"))
    fig.update_yaxes(autorange="reversed", scaleanchor="x", title="m (north up on the map)")
    fig.update_xaxes(title="m")
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=20, b=30), showlegend=False)
    return fig
