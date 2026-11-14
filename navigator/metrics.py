"""Navigator physics: what the light point series says about a site and a date (exact, no AI).

Reads only contracts.light.PointSeries (never other folders' code). Definitions, all at one cell k of the series
(k = 0 is the candidate landing cell):

* Sun up    : sun_fraction > 0, i.e. any part of the solar disk is above the terrain horizon (finite disk,
              terrain + curvature already applied by whoever wrote the file).
* Earth up  : Earth-centre elevation > the terrain horizon at Earth's azimuth (horizon_elev_deg[k, az]). Earth is a
              point here, so this is a direct-to-Earth (DTE) radio line of sight for a lander antenna at ground level.
* Blackout  : Sun down AND Earth down: no power from the panels and no radio link.

Time resolution is the file's cadence (1 h): countdowns are 'by the next sample' and say so.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from contracts.light import PointSeries

N_AZ = 360


def step_hours(ps: PointSeries) -> float:
    """Sample spacing in hours (from the ephemeris-time axis)."""
    return float(np.median(np.diff(ps.et_s)) / 3600.0)


def horizon_at(ps: PointSeries, az_deg: np.ndarray, k: int = 0) -> np.ndarray:
    """Terrain horizon elevation [T] along azimuths `az_deg` [T] (tile frame), linear between 1 deg bins."""
    a = np.asarray(az_deg, dtype=np.float64) % N_AZ
    i0 = np.floor(a).astype(int) % N_AZ
    f = a - np.floor(a)
    h = ps.horizon_elev_deg[k].astype(np.float64)
    return (1 - f) * h[i0] + f * h[(i0 + 1) % N_AZ]


def sun_up(ps: PointSeries, k: int = 0) -> np.ndarray:
    return ps.sun_fraction[:, k] > 0.0


def earth_margin_deg(ps: PointSeries, k: int = 0) -> np.ndarray:
    """Earth elevation minus the terrain horizon in Earth's direction [T] (> 0 means line of sight)."""
    return ps.earth_elev_deg[:, k].astype(np.float64) - horizon_at(ps, ps.earth_az_deg, k)


def earth_up(ps: PointSeries, k: int = 0) -> np.ndarray:
    return earth_margin_deg(ps, k) > 0.0


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Maximal runs of True as (start, stop) with stop exclusive."""
    m = np.asarray(mask, dtype=bool)
    if not m.size:
        return []
    d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


@dataclass(frozen=True)
class Summary:
    window_hours: float
    sun_hours: float
    earth_hours: float
    both_hours: float
    blackout_hours: float
    longest_dark_hours: float
    longest_dark_is_lower_bound: bool   # the run touches the window edge, so the real one may be longer
    longest_blackout_hours: float
    mean_sun_elev_deg: float            # mean while the Sun is up (nan if never)
    max_sun_elev_deg: float
    n_sunsets: int
    n_earthsets: int


def summarize(ps: PointSeries, k: int = 0) -> Summary:
    dt = step_hours(ps)
    s, e = sun_up(ps, k), earth_up(ps, k)
    dark = runs(~s)
    black = runs(~s & ~e)
    n = len(s)
    longest = max(dark, key=lambda r: r[1] - r[0]) if dark else (0, 0)
    elev = ps.sun_elev_deg[:, k]
    return Summary(
        window_hours=(n - 1) * dt,
        sun_hours=float(s.sum() * dt), earth_hours=float(e.sum() * dt), both_hours=float((s & e).sum() * dt),
        blackout_hours=float((~s & ~e).sum() * dt),
        longest_dark_hours=float((longest[1] - longest[0]) * dt),
        longest_dark_is_lower_bound=bool(dark) and (longest[0] == 0 or longest[1] == n),
        longest_blackout_hours=float(max((b - a for a, b in black), default=0) * dt),
        mean_sun_elev_deg=float(elev[s].mean()) if s.any() else float("nan"),
        max_sun_elev_deg=float(elev[s].max()) if s.any() else float("nan"),
        n_sunsets=sum(1 for _, stop in runs(s) if stop < n),
        n_earthsets=sum(1 for _, stop in runs(e) if stop < n),
    )


@dataclass(frozen=True)
class Countdown:
    state: str                 # "up" or "down" right now
    event: str | None          # "sunset"/"sunrise" (or earthset/earthrise); None if no change inside the window
    hours: float | None        # until the first sample after the change (resolution = cadence)
    at_utc: str | None


def countdown(ps: PointSeries, mask: np.ndarray, i: int, up_event: str, down_event: str) -> Countdown:
    """Time from sample i to the next change of `mask`. up_event is what ENDS an 'up' spell (e.g. 'sunset')."""
    m = np.asarray(mask, dtype=bool)
    state = bool(m[i])
    later = np.flatnonzero(m[i + 1:] != state)
    state_s = "up" if state else "down"
    if not later.size:
        return Countdown(state_s, None, None, None)
    j = i + 1 + int(later[0])
    return Countdown(state_s, up_event if state else down_event, float((j - i) * step_hours(ps)), ps.times_utc[j])


def sun_countdown(ps: PointSeries, i: int, k: int = 0) -> Countdown:
    return countdown(ps, sun_up(ps, k), i, "sunset", "sunrise")


def earth_countdown(ps: PointSeries, i: int, k: int = 0) -> Countdown:
    return countdown(ps, earth_up(ps, k), i, "Earthset", "Earthrise")


def format_hours(h: float | None) -> str:
    if h is None or not np.isfinite(h):
        return "no change in this window"
    d, r = divmod(h, 24.0)
    return f"{int(d)} d {r:.0f} h" if d >= 1 else f"{h:.0f} h"
