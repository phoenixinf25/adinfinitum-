"""Data access and telemetry loaders for Mission Control (Spec §9.2).

Rules:
- Strictly reads and parses files (telemetry CSVs, rover CSVs, light PointSeries).
- No physics simulation is computed here.
- Adheres to contracts.runs.TELEMETRY_COLUMNS and docs/FORMATS.md.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import pandas as pd

from contracts.paths import data_root, repo_root, runs_root
from contracts.runs import TELEMETRY_COLUMNS, read_telemetry


class TelemetryFileInfo(NamedTuple):
    name: str
    path: Path
    is_fixture: bool
    source_label: str
    row_count: int


def get_available_telemetry_files() -> list[TelemetryFileInfo]:
    """Discover all telemetry files in tests/fixtures and runs/basilisk."""
    results: list[TelemetryFileInfo] = []
    root = repo_root()

    # 1. Fixtures in tests/fixtures/
    fixtures_dir = root / "tests" / "fixtures"
    if fixtures_dir.exists():
        for p in sorted(fixtures_dir.glob("*.csv")):
            try:
                df = pd.read_csv(p)
                results.append(
                    TelemetryFileInfo(
                        name=f"{p.name} [FIXTURE]",
                        path=p,
                        is_fixture=True,
                        source_label="FIXTURE — STAND-IN",
                        row_count=len(df),
                    )
                )
            except Exception:
                continue

    # 2. Runs in runs/basilisk/
    runs_dir = runs_root() / "basilisk"
    if runs_dir.exists():
        for p in sorted(runs_dir.glob("telemetry_*.csv")):
            try:
                df = pd.read_csv(p)
                results.append(
                    TelemetryFileInfo(
                        name=f"{p.name} (Basilisk Flight)",
                        path=p,
                        is_fixture=False,
                        source_label="MODELLED · Basilisk",
                        row_count=len(df),
                    )
                )
            except Exception:
                continue

        for p in sorted(runs_dir.glob("lander_power_*.csv")):
            try:
                df = pd.read_csv(p)
                results.append(
                    TelemetryFileInfo(
                        name=f"{p.name} (30-Day Power/Comms)",
                        path=p,
                        is_fixture=False,
                        source_label="MODELLED · Basilisk",
                        row_count=len(df),
                    )
                )
            except Exception:
                continue

    return results


def load_telemetry(path: str | Path) -> pd.DataFrame:
    """Load and normalize flight telemetry adhering to TELEMETRY_COLUMNS.
    
    Ensures numeric types for physics fields and string types for phase/decision.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Telemetry file not found: {p}")

    try:
        rows = read_telemetry(p)
        df = pd.DataFrame(rows)
    except Exception:
        df = pd.read_csv(p)

    # Ensure all contract columns exist
    for col in TELEMETRY_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan

    # Convert numeric fields
    numeric_cols = [
        "t_s", "x_m", "y_m", "alt_m", "vx_m_s", "vy_m_s", "vz_m_s",
        "mass_kg", "fuel_kg", "thrust_n", "engines_ok", "battery_wh", "solar_w"
    ]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # String & boolean columns
    df["phase"] = df["phase"].fillna("powered_descent").astype(str)
    df["decision"] = df["decision"].fillna("").astype(str)
    
    # Earth visible flag (0, 1, or NaN)
    df["earth_visible"] = pd.to_numeric(df["earth_visible"], errors="coerce")

    # Computed flight display helpers (no physics integration, just instantaneous vector norms)
    vx = df["vx_m_s"].fillna(0.0)
    vy = df["vy_m_s"].fillna(0.0)
    vz = df["vz_m_s"].fillna(0.0)
    df["v_horizontal_m_s"] = np.sqrt(vx**2 + vy**2)
    df["v_total_m_s"] = np.sqrt(vx**2 + vy**2 + vz**2)
    
    # Ground track distance from origin
    df["ground_distance_m"] = np.sqrt(df["x_m"].fillna(0.0)**2 + df["y_m"].fillna(0.0)**2)

    return df


def load_rover_telemetry(rover_path: str | Path | None = None) -> pd.DataFrame | None:
    """Load rover traverse telemetry if available."""
    if rover_path is None:
        runs_dir = runs_root() / "basilisk"
        candidate_files = [
            runs_dir / "rover_test_rover.csv",
            runs_dir / "rover_rover_01.csv",
            runs_dir / "rover_unit_test_rover.csv",
        ]
        for c in candidate_files:
            if c.exists():
                rover_path = c
                break

    if rover_path is None or not Path(rover_path).exists():
        return None

    try:
        df = pd.read_csv(rover_path)
        # Verify essential rover columns
        required = ["time_s", "x_m", "y_m", "battery_pct"]
        if all(r in df.columns for r in required):
            return df
    except Exception:
        pass
    return None


class EngineDetail(NamedTuple):
    id: int
    name: str
    position: str
    status: str
    color: str
    thrust_n: float
    throttle_pct: float


def parse_engine_cluster(
    engines_ok: int | float,
    decision_text: str = "",
    total_thrust_n: float = 0.0,
    max_engine_thrust_n: float = 800.0,
) -> dict[str, Any]:
    """Parse 5-engine cluster state from engines_ok and decision history.
    
    Lander architecture:
    - 5 × 800 N engines (Spec §4.2, config/mission.yaml).
    - Center engine: E5.
    - Peripheral engines: E1 (North / +X), E2 (East / +Y), E3 (South / -X), E4 (West / -Y).
    - Engine-out logic: If E1 fails, opposite engine E3 is shut down to eliminate net torque.
    """
    n_ok = int(engines_ok) if pd.notna(engines_ok) else 5
    total_thrust = float(total_thrust_n) if pd.notna(total_thrust_n) else 0.0
    
    # Check decision log for failure signatures
    e1_failed = "engine 1 failed" in decision_text.lower() or n_ok < 5
    e3_balanced = ("shut down opposite engine 3" in decision_text.lower() or "engine 3 for balance" in decision_text.lower()) and n_ok <= 3

    # Nominal per-engine thrust share
    active_count = max(n_ok, 1) if n_ok > 0 else 1
    nominal_thrust_per_active = total_thrust / active_count if active_count > 0 else 0.0

    engines: list[EngineDetail] = []

    # Engine 1 (North)
    if e1_failed:
        engines.append(EngineDetail(1, "E1", "North (+X)", "FAILED", "#ff2a55", 0.0, 0.0))
    else:
        pct = min(100.0, (nominal_thrust_per_active / max_engine_thrust_n) * 100.0)
        engines.append(EngineDetail(1, "E1", "North (+X)", "NOMINAL", "#00ff88", nominal_thrust_per_active, pct))

    # Engine 2 (East)
    pct2 = min(100.0, (nominal_thrust_per_active / max_engine_thrust_n) * 100.0)
    engines.append(EngineDetail(2, "E2", "East (+Y)", "NOMINAL", "#00ff88", nominal_thrust_per_active, pct2))

    # Engine 3 (South)
    if e3_balanced:
        engines.append(EngineDetail(3, "E3", "South (-X)", "OFF (BALANCED)", "#ffaa00", 0.0, 0.0))
    elif n_ok <= 2:
        engines.append(EngineDetail(3, "E3", "South (-X)", "FAILED", "#ff2a55", 0.0, 0.0))
    else:
        pct = min(100.0, (nominal_thrust_per_active / max_engine_thrust_n) * 100.0)
        engines.append(EngineDetail(3, "E3", "South (-X)", "NOMINAL", "#00ff88", nominal_thrust_per_active, pct))

    # Engine 4 (West)
    pct4 = min(100.0, (nominal_thrust_per_active / max_engine_thrust_n) * 100.0)
    engines.append(EngineDetail(4, "E4", "West (-Y)", "NOMINAL", "#00ff88", nominal_thrust_per_active, pct4))

    # Engine 5 (Center)
    pct5 = min(100.0, (nominal_thrust_per_active / max_engine_thrust_n) * 100.0)
    engines.append(EngineDetail(5, "E5", "Center", "NOMINAL", "#00ff88", nominal_thrust_per_active, pct5))

    return {
        "engines": engines,
        "engines_ok": n_ok,
        "active_count": n_ok,
        "e1_failed": e1_failed,
        "e3_balanced": e3_balanced,
        "total_thrust_n": total_thrust,
    }


def extract_decisions(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Extract all autonomous decisions made during the mission timeline."""
    decisions = []
    if "decision" not in df.columns:
        return decisions

    for _, row in df.iterrows():
        dec_text = str(row["decision"]).strip()
        if dec_text and dec_text != "nan":
            decisions.append({
                "t_s": float(row["t_s"]) if pd.notna(row["t_s"]) else 0.0,
                "phase": str(row["phase"]),
                "decision": dec_text,
                "engines_ok": int(row["engines_ok"]) if pd.notna(row["engines_ok"]) else 5,
            })
    return decisions


def get_site_countdowns(site: str = "shackleton", date: str = "2026-11-14", step_hour: int = 0) -> dict[str, Any]:
    """Retrieve countdowns to sunset/sunrise and Earthset/Earthrise matching Navigator.
    
    Reads exact data from contracts/light.py via PointSeries and computes
    using navigator.metrics.sun_countdown and earth_countdown.
    """
    try:
        from contracts.light import load_points
        from navigator.metrics import earth_countdown, format_hours, sun_countdown

        points_file = data_root() / "light" / f"{site}_{date}_points.npz"
        if not points_file.exists():
            # Try alternate fallback
            cand = list((data_root() / "light").glob(f"{site}*_points.npz"))
            if cand:
                points_file = cand[0]

        if points_file.exists():
            ps = load_points(points_file)
            i = min(step_hour, len(ps.times_utc) - 1)
            sc = sun_countdown(ps, i)
            ec = earth_countdown(ps, i)
            return {
                "available": True,
                "sun_state": sc.state,
                "sun_event": sc.event or "sunset",
                "sun_hours": sc.hours,
                "sun_str": f"{sc.event}: {format_hours(sc.hours)}" if sc.event else "no change",
                "earth_state": ec.state,
                "earth_event": ec.event or "Earthset",
                "earth_hours": ec.hours,
                "earth_str": f"{ec.event}: {format_hours(ec.hours)}" if ec.event else "no change",
                "utc": ps.times_utc[i],
            }
    except Exception:
        pass

    return {
        "available": False,
        "sun_str": "—",
        "earth_str": "—",
        "sun_hours": None,
        "earth_hours": None,
    }
