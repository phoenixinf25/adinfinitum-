#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Frames for the orbit, deorbit and powered-descent phases of the mission.

* **Orbit and deorbit** are an analytic Keplerian model (MODELLED, not Basilisk):
  a 100 km circular polar orbit, a deorbit burn at the north pole, and a coast
  half-orbit to a 15 km periapsis over the south pole. The numbers (100 km,
  15 km, -19.5 m/s, 1,692 m/s) are those in the team's Basilisk handbook; the
  model reproduces the 1,692 m/s periapsis speed, which checks the geometry.
* **Powered descent** is real Basilisk telemetry (``sample/descent_basilisk.csv``,
  recorded by the team's ``scenario_descent --engine-out-at 20``).

The braking arc between the 15 km periapsis and the 1.95 km start of the
Basilisk descent file is NOT simulated here, and the timeline says so.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

MU_MOON = 4902.800066  # [km^3/s^2] lunar gravitational parameter
R_MOON = 1737.4  # [km] lunar radius
ALT_ORBIT_KM = 100.0  # [km] circular parking orbit (handbook)
ALT_PDI_KM = 15.0  # [km] periapsis after the deorbit burn (handbook)
DEORBIT_DV = -19.5  # [m/s] deorbit burn (handbook)
N_ORBITS_BEFORE_BURN = 1.5  # [-] orbits flown before the deorbit burn (burn at the north pole)
SAMPLE_S = 60.0  # [s] orbit frame spacing


def _kepler_ellipse(n_samples: int) -> list[tuple[float, float, float]]:
    """Return (t_since_burn [s], true anomaly [rad], radius [km]) from apoapsis to periapsis."""
    ra, rp = R_MOON + ALT_ORBIT_KM, R_MOON + ALT_PDI_KM
    a = 0.5 * (ra + rp)
    e = (ra - rp) / (ra + rp)
    n = math.sqrt(MU_MOON / a ** 3)  # [rad/s]
    out = []
    for i in range(n_samples + 1):
        m = math.pi * (1.0 - i / n_samples)  # mean anomaly from pi (apoapsis) down to 0 (periapsis)
        ecc = m
        for _ in range(50):
            ecc -= (ecc - e * math.sin(ecc) - m) / (1.0 - e * math.cos(ecc))
        theta = 2.0 * math.atan2(math.sqrt(1 + e) * math.sin(ecc / 2.0), math.sqrt(1 - e) * math.cos(ecc / 2.0))
        r = a * (1.0 - e * math.cos(ecc))
        out.append((math.pi / n * i / (1.0) * (1.0) if False else (math.pi - m) / n, theta, r))
    return out


def speed_at_periapsis_m_s() -> float:
    """Vis-viva speed at the 15 km periapsis [m/s] (should match the handbook's 1,692 m/s)."""
    ra, rp = R_MOON + ALT_ORBIT_KM, R_MOON + ALT_PDI_KM
    a = 0.5 * (ra + rp)
    return math.sqrt(MU_MOON * (2.0 / rp - 1.0 / a)) * 1000.0


def orbit_frames(site_lat_deg: float, site_lon_deg: float, sun: dict[str, float]) -> list[dict[str, Any]]:
    """Frames from the start of autonomy in orbit to periapsis over the landing site."""
    r_c = R_MOON + ALT_ORBIT_KM
    period = 2.0 * math.pi * math.sqrt(r_c ** 3 / MU_MOON)  # [s]
    v_c = math.sqrt(MU_MOON / r_c) * 1000.0  # [m/s]
    t_burn = N_ORBITS_BEFORE_BURN * period
    frames: list[dict[str, Any]] = []

    def pos(u_deg: float) -> tuple[float, float]:
        """Latitude and longitude of a polar orbit with argument of latitude ``u``."""
        u = u_deg % 360.0
        if u <= 90.0:
            return u, site_lon_deg
        if u <= 270.0:
            return 180.0 - u, site_lon_deg + 180.0
        return u - 360.0, site_lon_deg

    t = 0.0
    first = True
    while t < t_burn:
        u = -90.0 + 360.0 * t / period  # starts over the south pole region side
        lat, lon = pos(u)
        f = {"type": "frame", "t_s": round(t, 1), "mission_phase": "ORBIT", "control": "autonomy", "phase": "ORBIT",
             "reason": "", "orbit": {"lat_deg": lat, "lon_deg": ((lon + 180.0) % 360.0) - 180.0, "alt_km": ALT_ORBIT_KM,
                                     "speed_m_s": round(v_c, 1), "orbit_no": 1 + int(t // period)},
             "sun": sun, "earth_elev_deg": 0.0, "events": []}
        if first:
            f["events"] = [{"t_s": 0.0, "kind": "decision",
                            "msg": f"Autonomy engaged in a {ALT_ORBIT_KM:.0f} km polar orbit (period {period / 60:.1f} min, "
                                   f"{v_c:.0f} m/s)"}]
            first = False
        frames.append(f)
        t += SAMPLE_S

    # Deorbit burn at the north pole, then coast along the transfer ellipse to periapsis.
    ell = _kepler_ellipse(120)
    t_coast = ell[-1][0]
    frames.append({"type": "frame", "t_s": round(t_burn, 1), "mission_phase": "DEORBIT", "control": "autonomy",
                   "phase": "DEORBIT BURN", "reason": "", "orbit": {"lat_deg": 90.0, "lon_deg": site_lon_deg,
                                                                     "alt_km": ALT_ORBIT_KM, "speed_m_s": round(v_c, 1),
                                                                     "orbit_no": 2},
                   "sun": sun, "earth_elev_deg": 0.0,
                   "events": [{"t_s": round(t_burn, 1), "kind": "decision",
                               "msg": f"Deorbit burn {DEORBIT_DV:.1f} m/s at the north pole: periapsis lowered to "
                                      f"{ALT_PDI_KM:.0f} km"}]})
    for dt, theta, r in ell[1:]:
        u = 90.0 + math.degrees(math.pi - theta) * 1.0  # apoapsis (theta=pi) at u=90, periapsis (0) at u=270
        lat, lon = pos(u)
        frames.append({"type": "frame", "t_s": round(t_burn + dt, 1), "mission_phase": "DEORBIT", "control": "autonomy",
                       "phase": "COAST", "reason": "",
                       "orbit": {"lat_deg": lat, "lon_deg": ((lon + 180.0) % 360.0) - 180.0, "alt_km": round(r - R_MOON, 2),
                                 "speed_m_s": round(math.sqrt(MU_MOON * (2.0 / r - 2.0 / (2 * R_MOON + ALT_ORBIT_KM + ALT_PDI_KM))) * 1000.0, 1),
                                 "orbit_no": 2},
                       "sun": sun, "earth_elev_deg": 0.0, "events": []})
    frames[-1]["events"] = [{"t_s": frames[-1]["t_s"], "kind": "decision",
                             "msg": f"Periapsis {ALT_PDI_KM:.0f} km at {speed_at_periapsis_m_s():.0f} m/s: powered descent initiation"}]
    _ = t_coast
    return frames


def descent_frames(csv_path: Path, t0: float, start_xy: tuple[float, float], sun: dict[str, float]) -> list[dict[str, Any]]:
    """Frames from real Basilisk telemetry, positioned around the landing point ``start_xy`` [m]."""
    rows = list(csv.DictReader(open(csv_path, newline="", encoding="utf-8")))
    frames: list[dict[str, Any]] = []
    prev_ok: int | None = None
    for i, r in enumerate(rows):
        ok = int(float(r["engines_ok"]))
        f = {"type": "frame", "t_s": round(t0 + float(r["t_s"]), 1), "mission_phase": "DESCENT", "control": "autonomy",
             "phase": "POWERED DESCENT", "reason": "",
             "lander": {"x_m": start_xy[0] + float(r["x_m"]), "y_m": start_xy[1] + float(r["y_m"]),
                        "alt_m": float(r["alt_m"]), "vx_m_s": float(r["vx_m_s"]), "vy_m_s": float(r["vy_m_s"]),
                        "vz_m_s": float(r["vz_m_s"]), "mass_kg": float(r["mass_kg"]), "fuel_kg": float(r["fuel_kg"]),
                        "thrust_n": float(r["thrust_n"]), "engines_ok": ok},
             "sun": sun, "earth_elev_deg": 0.0, "events": []}
        if i == 0:
            f["events"].append({"t_s": f["t_s"], "kind": "event",
                                "msg": "Basilisk terminal descent begins at %.0f m. The braking arc from the 15 km "
                                       "periapsis to this point is not in this replay" % float(r["alt_m"])})
        if prev_ok is not None and ok != prev_ok:
            f["events"].append({"t_s": f["t_s"], "kind": "event",
                                "msg": f"Engine failure: {ok} of 5 engines available; guidance rebalances thrust"})
        prev_ok = ok
        frames.append(f)
    last = rows[-1]
    vh = math.hypot(float(last["vx_m_s"]), float(last["vy_m_s"]))
    frames[-1]["events"].append({"t_s": frames[-1]["t_s"], "kind": "sample",
                                 "msg": f"Touchdown: vertical {abs(float(last['vz_m_s'])):.2f} m/s, horizontal {vh:.2f} m/s, "
                                        f"{float(last['fuel_kg']):.0f} kg fuel left"})
    return frames
