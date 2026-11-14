"""
STARTER / EXPANDED (Tanush & Arnav): lunar orbit -> release -> deorbit -> coast to powered-descent start.

    python -m basilisk_mods.scenario_orbit_release
    python -m basilisk_mods.scenario_orbit_release --orbit-alt-km 100 --peri-alt-km 15 --no-viz

Writes:
  runs/basilisk/pdi_state.json            state at periapsis (powered-descent initiation)
  runs/basilisk/orbit_altitude.png        altitude vs time
  runs/basilisk/_VizFiles/orbit_release_UnityViz.bin   open in Vizard
  runs/basilisk/_VizFiles/orbit_release_UnityViz.json  open in Vizard / Web Replay

Physics: point-mass Moon, impulsive deorbit burn (a real burn takes ~10 s at 4 kN, so the
impulsive model is a good first approximation). Masses from config/mission.yaml.
Propulsion module continues in 100 km orbit after release so both objects appear in Vizard (KAN-41).
Includes Sun and Earth pointing lines, custom lander mesh (KAN-47).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from basilisk_mods.bsk_common import (
    HAS_BSK,
    MU_MOON,
    R_MOON_M,
    add_moon_gravity,
    macros,
    mission,
    new_sim,
    out_dir,
    rbk,
)
from basilisk_mods import viz_support
from contracts.provenance import Meta, Provenance


def elem2rv_kepler(mu: float, a: float, e: float, inc_rad: float, raan_rad: float, omega_rad: float, f_rad: float):
    """Compute position and velocity vectors from Keplerian orbital elements."""
    p = a * (1.0 - e**2)
    r_orbit = p / (1.0 + e * math.cos(f_rad))
    r_perifocal = np.array([r_orbit * math.cos(f_rad), r_orbit * math.sin(f_rad), 0.0])
    v_perifocal = np.array([-math.sqrt(mu / p) * math.sin(f_rad), math.sqrt(mu / p) * (e + math.cos(f_rad)), 0.0])

    R_z_raan = np.array([
        [math.cos(raan_rad), -math.sin(raan_rad), 0.0],
        [math.sin(raan_rad), math.cos(raan_rad), 0.0],
        [0.0, 0.0, 1.0],
    ])
    R_x_inc = np.array([
        [1.0, 0.0, 0.0],
        [0.0, math.cos(inc_rad), -math.sin(inc_rad)],
        [0.0, math.sin(inc_rad), math.cos(inc_rad)],
    ])
    R_z_omega = np.array([
        [math.cos(omega_rad), -math.sin(omega_rad), 0.0],
        [math.sin(omega_rad), math.cos(omega_rad), 0.0],
        [0.0, 0.0, 1.0],
    ])
    R_matrix = R_z_raan @ R_x_inc @ R_z_omega
    r_vec = R_matrix @ r_perifocal
    v_vec = R_matrix @ v_perifocal
    return r_vec, v_vec


def run(
    orbit_alt_km: float = 100.0,
    peri_alt_km: float = 15.0,
    inclination_deg: float = 90.0,
    raan_deg: float = 30.0,
    release_after_s: float = 600.0,
    viz: bool = True,
    plot: bool = True,
) -> dict:
    cfg = mission()
    lander_mass = cfg.lander.wet_mass_at_release_kg
    prop_module_mass = cfg.lander.propulsion_module_mass_kg
    total_mass = lander_mass + prop_module_mass
    mu = MU_MOON

    a_init = R_MOON_M + orbit_alt_km * 1e3
    inc_rad = math.radians(inclination_deg)
    raan_rad = math.radians(raan_deg)
    T_orbit = 2.0 * math.pi * math.sqrt(a_init**3 / mu)

    # Initial state
    r0, v0 = elem2rv_kepler(mu, a_init, 0.0, inc_rad, raan_rad, 0.0, 0.0)

    # Calculate deorbit burn
    ra = a_init
    rp = R_MOON_M + peri_alt_km * 1e3
    a_deorbit = 0.5 * (ra + rp)
    v_a_transfer = math.sqrt(mu * (2.0 / ra - 1.0 / a_deorbit))
    v_circ = math.sqrt(mu / ra)
    dv = v_a_transfer - v_circ  # negative = retrograde burn
    prop_used = lander_mass * (1.0 - math.exp(-abs(dv) / (cfg.lander.isp_s * cfg.moon.g0_m_s2)))
    t_coast = math.pi * math.sqrt(a_deorbit**3 / mu)
    total_sim_time = release_after_s + t_coast

    # Prepare Vizard recording
    vizard_rec = None
    if viz:
        vizard_rec = viz_support.enableUnityVisualization(
            sim=None,
            taskName="dynTask",
            scList=None,
            saveFile=str(out_dir() / "orbit_release"),
        )
        # Custom lander model
        vizard_dir = Path("vizard")
        lander_obj = vizard_dir / "lander_body.obj"
        if lander_obj.exists():
            viz_support.createCustomModel(
                vizard_rec,
                modelPath=str(lander_obj),
                simBodiesToModify=["lander", "lander_stack"],
                scale=[1.0, 1.0, 1.0],
            )
        # Pointing lines: Sun and Earth
        viz_support.createPointLine(vizard_rec, toBodyName="sun_planet_data", lineColor="yellow")
        viz_support.createPointLine(vizard_rec, toBodyName="earth_planet_data", lineColor=[0, 150, 255, 255])

    # Simulation trajectory points (dt = 5s)
    dt = 5.0
    times = np.arange(0.0, total_sim_time + dt, dt)
    alt_history = []
    t_history = []

    # States
    r_lander = np.copy(r0)
    v_lander = np.copy(v0)
    r_prop = np.copy(r0)
    v_prop = np.copy(v0)

    # Constant celestial directions (approximate Moon South Pole view)
    sun_dir = [0.0, math.cos(math.radians(1.5)), math.sin(math.radians(1.5))]
    earth_dir = [math.cos(math.radians(6.5)), 0.0, math.sin(math.radians(6.5))]

    def rk4_step(r, v, dt_step):
        def acc(pos):
            norm_r = math.sqrt(pos[0]**2 + pos[1]**2 + pos[2]**2)
            return -mu * pos / (norm_r**3)

        k1_v = acc(r)
        k1_r = v

        k2_v = acc(r + 0.5 * dt_step * k1_r)
        k2_r = v + 0.5 * dt_step * k1_v

        k3_v = acc(r + 0.5 * dt_step * k2_r)
        k3_r = v + 0.5 * dt_step * k2_v

        k4_v = acc(r + dt_step * k3_r)
        k4_r = v + dt_step * k3_v

        r_next = r + (dt_step / 6.0) * (k1_r + 2.0 * k2_r + 2.0 * k3_r + k4_r)
        v_next = v + (dt_step / 6.0) * (k1_v + 2.0 * k2_v + 2.0 * k3_v + k4_v)
        return r_next, v_next

    for t in times:
        alt_now = float(np.linalg.norm(r_lander) - R_MOON_M)
        alt_history.append(alt_now)
        t_history.append(t)

        # Deorbit impulse at release_after_s
        if abs(t - release_after_s) < 0.5 * dt:
            v_dir = v_lander / np.linalg.norm(v_lander)
            v_lander = v_dir * v_a_transfer

        # Vizard record frame
        if vizard_rec and (t % 15.0 < dt or t == times[-1]):
            # Attitude pointing: align +z with retrograde thrust vector during deorbit, or nadir
            z_nadir = -r_lander / np.linalg.norm(r_lander)
            v_dir = v_lander / np.linalg.norm(v_lander)
            dcm = np.vstack([
                np.cross(v_dir, z_nadir),
                v_dir,
                z_nadir
            ])
            mrp = rbk.C2MRP(dcm).tolist()

            bodies = {
                "lander": {
                    "r_m": r_lander.tolist(),
                    "v_m_s": v_lander.tolist(),
                    "mrp": mrp,
                }
            }
            if t >= release_after_s:
                # Propulsion module continuing in circular orbit
                bodies["propulsion_module"] = {
                    "r_m": r_prop.tolist(),
                    "v_m_s": v_prop.tolist(),
                    "mrp": [0.0, 0.0, 0.0],
                }

            vizard_rec.record_frame(
                time_s=t,
                bodies_state=bodies,
                thrusters=[1.0 if abs(t - release_after_s) < 15.0 else 0.0],
                sun_direction=sun_dir,
                earth_direction=earth_dir,
                notes="Release & Deorbit" if abs(t - release_after_s) < 15.0 else "",
            )

        # Step forward
        r_lander, v_lander = rk4_step(r_lander, v_lander, dt)
        if t >= release_after_s:
            r_prop, v_prop = rk4_step(r_prop, v_prop, dt)
        else:
            r_prop = np.copy(r_lander)
            v_prop = np.copy(v_lander)

    alt_history = np.array(alt_history)
    t_history = np.array(t_history)
    r_f = r_lander
    v_f = v_lander

    state = {
        "t_s": float(total_sim_time),
        "r_BN_N_m": r_f.tolist(),
        "v_BN_N_m_s": v_f.tolist(),
        "mass_kg": float(lander_mass - prop_used),
        "altitude_m": float(np.linalg.norm(r_f) - R_MOON_M),
        "speed_m_s": float(np.linalg.norm(v_f)),
        "deorbit_dv_m_s": float(dv),
        "deorbit_propellant_kg": float(prop_used),
        "meta": Meta(
            provenance=Provenance.MODELLED,
            source="Basilisk / pure Python point-mass Moon, impulsive deorbit",
            frame="Moon-centred inertial (Basilisk N), non-rotating Moon",
            units={"r_BN_N_m": "m", "v_BN_N_m_s": "m/s", "mass_kg": "kg", "t_s": "s"},
            created_by="basilisk_mods.scenario_orbit_release"
        ).model_dump(mode="json"),
    }

    (out_dir() / "pdi_state.json").write_text(json.dumps(state, indent=2))

    if vizard_rec:
        bin_p, json_p = vizard_rec.save()
        print(f"saved Vizard replay  : {bin_p} ({json_p.name})")

    if plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(8, 4))
            ax.plot(t_history / 60, alt_history / 1e3, color="#00bcd4", lw=2, label="Lander Altitude")
            ax.axvline(release_after_s / 60, ls="--", color="gray", label="Release & Deorbit Burn")
            ax.text(release_after_s / 60 + 0.5, alt_history.max() / 1e3 * 0.9, " Release & Deorbit", color="#ffd54f")
            ax.set_xlabel("Time [min]")
            ax.set_ylabel("Altitude above 1737.4 km sphere [km]")
            ax.set_title("Lunar Orbit -> Release -> Deorbit -> PDI (MODELLED, Basilisk / LOLA)")
            ax.grid(True, alpha=0.3)
            ax.legend()
            fig.tight_layout()
            fig.savefig(out_dir() / "orbit_altitude.png", dpi=130)
            plt.close(fig)
        except Exception as e:
            print(f"plot warning: {e}")

    print(f"orbit period         : {T_orbit / 60:.1f} min")
    print(f"deorbit delta-v      : {dv:.1f} m/s  ({prop_used:.1f} kg propellant)")
    print(f"PDI altitude         : {state['altitude_m'] / 1e3:.2f} km  after {t_coast / 60:.1f} min coast")
    print(f"PDI speed            : {state['speed_m_s']:.1f} m/s")
    print(f"wrote                : {out_dir() / 'pdi_state.json'}")
    return state


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orbit-alt-km", type=float, default=100.0)
    ap.add_argument("--peri-alt-km", type=float, default=15.0)
    ap.add_argument("--inclination-deg", type=float, default=90.0)
    ap.add_argument("--release-after-s", type=float, default=600.0)
    ap.add_argument("--no-viz", action="store_true")
    a = ap.parse_args()
    run(a.orbit_alt_km, a.peri_alt_km, a.inclination_deg, release_after_s=a.release_after_s, viz=not a.no_viz)


if __name__ == "__main__":
    main()
