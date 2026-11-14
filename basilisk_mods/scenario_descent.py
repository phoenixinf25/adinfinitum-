"""
STARTER / EXPANDED (Tanush & Arnav): fly the 5-engine lander from terminal-descent start to touchdown on real terrain.

    python -m basilisk_mods.scenario_descent                       # nominal
    python -m basilisk_mods.scenario_descent --engine-out-at 20    # engine 1 fails at t = 20 s
    python -m basilisk_mods.scenario_descent --tile data/tiles/demo_craters.npz
    python -m basilisk_mods.scenario_descent --tile data/tiles/shackleton.npz

Writes:
  runs/basilisk/telemetry_<id>.csv              -> mission-control window
  runs/basilisk/descent_<id>.json               touchdown report
  runs/basilisk/_VizFiles/descent_<id>_UnityViz.bin   Vizard binary playback
  runs/basilisk/_VizFiles/descent_<id>_UnityViz.json  Vizard / Web 3D replay
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from basilisk_mods.bsk_common import (
    R_MOON_M,
    local_frame,
    macros,
    mission,
    new_sim,
    out_dir,
    rbk,
)
from basilisk_mods.lander_descent import build_lander, touchdown_report
from basilisk_mods.lunar_terrain import LunarTerrain, ps_from_moon_fixed
from basilisk_mods import viz_support
from contracts.provenance import Meta, Provenance
from contracts.runs import write_telemetry

TARGET_LAT_DEG = -89.0   # demo target near south pole
TARGET_LON_DEG = 30.0


def target_point_N(lat_deg=TARGET_LAT_DEG, lon_deg=TARGET_LON_DEG, height_m=0.0) -> np.ndarray:
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    return (R_MOON_M + height_m) * np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])


def run(
    run_id="demo",
    alt=2000.0,
    offset_east=300.0,
    offset_north=-200.0,
    v_down=45.0,
    v_east=10.0,
    engine_out_at=None,
    tile="data/tiles/demo_craters.npz",
    target_x=None,
    target_y=None,
    viz=True,
    max_time=300.0,
) -> dict:
    cfg = mission()
    dyn_dt, ctrl_dt = 0.01, 0.2

    # Load real terrain DEM
    terrain = None
    tile_path = Path(tile)
    if tile_path.exists():
        terrain = LunarTerrain(tile_path)
    elif Path("data/tiles/demo_craters.npz").exists():
        terrain = LunarTerrain("data/tiles/demo_craters.npz")

    # Target point
    tgt_height = 0.0
    if terrain is not None and target_x is not None and target_y is not None:
        tgt_height = float(terrain.ground_height(target_x, target_y))
    tgt = target_point_N(height_m=tgt_height)

    E, N, U = local_frame(tgt)
    r0 = tgt + alt * U + offset_east * E + offset_north * N
    v0 = -v_down * U + v_east * E

    sim = new_sim({"dynTask": dyn_dt, "fswTask": ctrl_dt})
    h = build_lander(sim, cfg, r0, v0, tgt, control_period_s=ctrl_dt)
    guid = h["guidance"]
    guid.engine_out_at_s = engine_out_at

    # Ground height function on terrain
    def ground_height_fn(r_curr):
        if terrain is None:
            return 0.0
        # Project r_curr into local frame relative to target
        rho = r_curr - tgt
        x_local = float(np.dot(rho, E))
        y_local = float(np.dot(rho, N))
        ref_x = target_x if target_x is not None else 0.0
        ref_y = target_y if target_y is not None else 0.0
        return float(terrain.ground_height(ref_x + x_local, ref_y + y_local)) - tgt_height

    guid.ground_height_fn = ground_height_fn

    # Prepare Vizard recording
    vizard_rec = None
    if viz:
        vizard_rec = viz_support.enableUnityVisualization(
            sim,
            "dynTask",
            h["sc"],
            saveFile=str(out_dir() / f"descent_{run_id}"),
            thrEffectorList=[h["engines"]],
        )
        # Custom lander mesh
        lander_obj = Path("vizard/lander_body.obj")
        if lander_obj.exists():
            viz_support.createCustomModel(
                vizard_rec,
                modelPath=str(lander_obj),
                simBodiesToModify=[h["sc"].ModelTag, "lander"],
                scale=[1.0, 1.0, 1.0],
            )
        # Terrain mesh
        terrain_obj = Path("vizard/terrain_demo_craters.obj")
        if "shackleton" in str(tile):
            terrain_obj = Path("vizard/terrain_shackleton.obj")
        if terrain_obj.exists():
            viz_support.createCustomModel(
                vizard_rec,
                modelPath=str(terrain_obj),
                simBodiesToModify=["terrain"],
                scale=[1.0, 1.0, 1.0],
            )
        # Pointing lines
        viz_support.createPointLine(vizard_rec, toBodyName="sun_planet_data", lineColor="yellow")
        viz_support.createPointLine(vizard_rec, toBodyName="earth_planet_data", lineColor=[0, 150, 255, 255])

    sim.InitializeSimulation()

    rows, t, report = [], 0.0, None
    state_msg = h["sc"].scStateOutMsg

    sun_dir = [0.0, math.cos(math.radians(1.5)), math.sin(math.radians(1.5))]
    earth_dir = [math.cos(math.radians(6.5)), 0.0, math.sin(math.radians(6.5))]

    while t < max_time:
        # Step simulation by ctrl_dt
        # Using pure-Python step_sim attached to spacecraft if available
        if hasattr(h["sc"], "step_sim"):
            # Internal substeps of dyn_dt
            steps = int(round(ctrl_dt / dyn_dt))
            for _ in range(steps):
                h["sc"].step_sim(t, dyn_dt)
                t += dyn_dt
        else:
            t += ctrl_dt
            sim.ConfigureStopTime(macros.sec2nano(t))
            sim.ExecuteSimulation()

        st = state_msg.read()
        r = np.array(st.r_BN_N)
        v = np.array(st.v_BN_N)
        ground = guid.ground_height_fn(r)
        alt_now = float(np.dot(r - tgt, U)) - ground

        # Calculate slope at lander ground footprint
        slope_deg = 0.0
        if terrain is not None:
            rho = r - tgt
            x_loc = float(np.dot(rho, E)) + (target_x if target_x is not None else 0.0)
            y_loc = float(np.dot(rho, N)) + (target_y if target_y is not None else 0.0)
            slope_deg = float(terrain.slope(x_loc, y_loc))

        # Log once per second or at touchdown
        if abs(t - round(t)) < 0.015 or alt_now <= 0.0:
            rel = r - tgt
            fuel = h["fuel_fn"]()
            decision = "; ".join(d for (td, d) in guid.decisions if (t - 1.01) <= td <= (t + 0.01))
            rows.append({
                "t_s": round(t, 2),
                "phase": guid.last.get("phase", ""),
                "x_m": float(rel @ E),
                "y_m": float(rel @ N),
                "alt_m": alt_now,
                "vx_m_s": float(v @ E),
                "vy_m_s": float(v @ N),
                "vz_m_s": float(v @ U),
                "mass_kg": h["mass_fn"](),
                "fuel_kg": fuel,
                "thrust_n": guid.last.get("thrust_n", 0.0),
                "engines_ok": guid.last.get("engines_ok", 5),
                "battery_wh": "",
                "solar_w": "",
                "earth_visible": "",
                "decision": decision,
            })

            # Record Vizard frame
            if vizard_rec:
                cmd = h["engines"].cmdsInMsg.read()
                thr_pcts = [min(1.0, ot / ctrl_dt) for ot in cmd.OnTime]
                vizard_rec.record_frame(
                    time_s=t,
                    bodies_state={
                        "lander": {
                            "r_m": r.tolist(),
                            "v_m_s": v.tolist(),
                            "mrp": st.sigma_BN,
                        }
                    },
                    thrusters=thr_pcts,
                    sun_direction=sun_dir,
                    earth_direction=earth_dir,
                    notes=decision,
                )

        if alt_now <= 0.0:
            report = touchdown_report(cfg, r, v, st.sigma_BN, slope_deg=slope_deg)
            report.update({
                "t_s": t,
                "x_m": float((r - tgt) @ E),
                "y_m": float((r - tgt) @ N),
                "fuel_left_kg": h["fuel_fn"](),
                "engine_out_at_s": engine_out_at,
            })
            rows[-1]["phase"] = "touchdown"
            rows[-1]["decision"] = f"TOUCHDOWN {report['outcome']}"
            break

        if h["fuel_fn"]() <= 0.01:
            report = {"outcome": "out_of_fuel", "t_s": t}
            break

    if report is None:
        report = {"outcome": "timeout", "t_s": t}

    meta = Meta(
        provenance=Provenance.MODELLED,
        source="Basilisk 6-DOF / Python rigid body, 5 thrusters, ideal attitude torque",
        frame="local east/north/up at target; LOLA terrain DEM ground",
        created_by="basilisk_mods.scenario_descent",
    )
    report["meta"] = meta.model_dump(mode="json")
    write_telemetry(rows, out_dir() / f"telemetry_{run_id}.csv")
    (out_dir() / f"descent_{run_id}.json").write_text(json.dumps(report, indent=2))

    if vizard_rec:
        bin_p, json_p = vizard_rec.save()
        print(f"saved Vizard replay  : {bin_p} ({json_p.name})")

    print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in report.items() if k != "meta"}, indent=1))
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="demo")
    ap.add_argument("--alt", type=float, default=2000.0)
    ap.add_argument("--offset-east", type=float, default=300.0)
    ap.add_argument("--offset-north", type=float, default=-200.0)
    ap.add_argument("--v-down", type=float, default=45.0)
    ap.add_argument("--v-east", type=float, default=10.0)
    ap.add_argument("--engine-out-at", type=float, default=None)
    ap.add_argument("--tile", default="data/tiles/demo_craters.npz")
    ap.add_argument("--target-x", type=float, default=None)
    ap.add_argument("--target-y", type=float, default=None)
    ap.add_argument("--no-viz", action="store_true")
    a = ap.parse_args()
    run(
        run_id=a.id,
        alt=a.alt,
        offset_east=a.offset_east,
        offset_north=a.offset_north,
        v_down=a.v_down,
        v_east=a.v_east,
        engine_out_at=a.engine_out_at,
        tile=a.tile,
        target_x=a.target_x,
        target_y=a.target_y,
        viz=not a.no_viz,
    )


if __name__ == "__main__":
    main()
