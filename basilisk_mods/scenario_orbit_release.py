# -*- coding: utf-8 -*-
"""
Basilisk Scenario: Lunar Orbit, Spacecraft Release, and Deorbit Burn
Context: Adinfinitum (NASA Space Apps 2026), Spec §5 phases 1-3, §7.2.

Simulates:
1. Moon central gravitational body (Basilisk gravBodyFactory).
2. Combined stack (propulsion module + lander) in ~100 km circular polar orbit.
3. Release event at time T (lander detaches; masses read from config/mission.yaml).
4. Deorbit burn (impulsive retrograde burn lowering periapsis to ~15 km over target region).
5. Coast to powered descent initiation (PDI); saves state to runs/basilisk/pdi_state.json.
6. Saves Vizard binary playback file via vizSupport.
7. Produces altitude vs time publication plot.
"""

import os
import sys
import json
import math
import yaml
import numpy as np
import matplotlib.pyplot as plt

# Basilisk Simulation modules
from Basilisk.utilities import SimulationBaseClass
from Basilisk.utilities import macros
from Basilisk.utilities import orbitalMotion
from Basilisk.utilities import simIncludeGravBody
from Basilisk.utilities import simHelpers
from Basilisk.simulation import spacecraft

# Attempt Vizard visualization import
try:
    from Basilisk.utilities import vizSupport
    VIZ_AVAILABLE = vizSupport.vizFound
except ImportError:
    VIZ_AVAILABLE = False


def load_mission_config(config_path="config/mission.yaml"):
    """Reads spacecraft masses and orbital parameters from YAML."""
    if not os.path.exists(config_path):
        parent_config = os.path.join("..", config_path)
        if os.path.exists(parent_config):
            config_path = parent_config
        else:
            raise FileNotFoundError(f"Cannot find mission configuration at {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def run_scenario(show_plots=False):
    # 1. Load mission configuration (DO NOT hard-code masses)
    cfg = load_mission_config()
    
    m_prop = cfg["spacecraft"]["propulsion_module"]["wet_mass_kg"]
    m_lander = cfg["spacecraft"]["lander"]["wet_mass_kg"]
    m_combined = cfg["spacecraft"]["combined_stack"]["total_mass_kg"]
    
    h_init_km = cfg["orbit"]["initial_altitude_km"]
    h_target_pdi_km = cfg["maneuvers"]["target_periapsis_km"]
    t_release_sec = cfg["maneuvers"]["release_time_sec"]
    target_region = cfg["maneuvers"]["target_region"]

    print("=" * 65)
    print("BASILISK LUNAR ORBIT, RELEASE & DEORBIT SIMULATION")
    print(f"Mission: {cfg.get('mission_name', 'Adinfinitum')}")
    print(f"Combined Stack Mass: {m_combined:.1f} kg (Lander: {m_lander:.1f} kg, PM: {m_prop:.1f} kg)")
    print(f"Initial Orbit: ~{h_init_km:.1f} km Circular Polar Orbit")
    print(f"Release Event Scheduled: T = {t_release_sec:.1f} s")
    print(f"Target Periapsis (PDI): ~{h_target_pdi_km:.1f} km over {target_region.get('name', 'South Pole')}")
    print("=" * 65)

    # 2. Create simulation container and process
    scSim = SimulationBaseClass.SimBaseClass()
    simTaskName = "dynamicsTask"
    simProcessName = "dynamicsProcess"
    
    simTimeStepSec = 2.0  # 2.0s integration step
    simulationTimeStep = macros.sec2nano(simTimeStepSec)
    dynProcess = scSim.CreateNewProcess(simProcessName)
    dynProcess.addTask(scSim.CreateNewTask(simTaskName, simulationTimeStep))

    # 3. Setup central gravity body (Moon)
    gravFactory = simIncludeGravBody.gravBodyFactory()
    moon = gravFactory.createMoon()
    moon.isCentralBody = True
    mu = moon.mu
    r_moon = moon.radEquator  # 1,737,400.0 m

    # 4. Setup Spacecraft module (Starts as Combined Stack)
    scObject = spacecraft.Spacecraft()
    scObject.ModelTag = "Adinfinitum-Spacecraft"
    scObject.hub.mHub = m_combined
    scObject.hub.IHubPntBc_B = [[1000.0, 0.0, 0.0],
                                [0.0, 1000.0, 0.0],
                                [0.0, 0.0, 1000.0]]
    scSim.AddModelToTask(simTaskName, scObject)
    gravFactory.addBodiesTo(scObject)

    # 5. Define Initial Orbit: 100 km circular polar orbit
    r_init_m = r_moon + (h_init_km * 1000.0)
    oe = orbitalMotion.ClassicElements()
    oe.a = r_init_m
    oe.e = cfg["orbit"].get("eccentricity", 0.0001)
    oe.i = cfg["orbit"]["inclination_deg"] * macros.D2R
    oe.Omega = 0.0 * macros.D2R
    oe.omega = 0.0 * macros.D2R
    oe.f = cfg["orbit"].get("true_anomaly_deg", 0.0) * macros.D2R

    rN, vN = orbitalMotion.elem2rv(mu, oe)
    scObject.hub.r_CN_NInit = rN
    scObject.hub.v_CN_NInit = vN

    # 6. Setup Data Logger for Spacecraft States
    dataRec = scObject.scStateOutMsg.recorder(macros.sec2nano(5.0))
    scSim.AddModelToTask(simTaskName, dataRec)

    # 7. Setup Vizard Visualization File
    runs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs", "basilisk")
    os.makedirs(runs_dir, exist_ok=True)
    vizard_filename = os.path.join(runs_dir, "scenario_orbit_release_UnityViz.bin")

    if VIZ_AVAILABLE:
        viz = vizSupport.enableUnityVisualization(
            scSim, simTaskName, scObject,
            saveFile=vizard_filename,
            oscOrbitColorList=[vizSupport.toRGBA255("gold")],
            trueOrbitColorList=[vizSupport.toRGBA255("cyan")]
        )
        viz.settings.mainCameraTarget = "moon"
        viz.settings.showCelestialBodyLabels = 1
        viz.settings.showSpacecraftLabels = 1
        viz.settings.trueTrajectoryLinesOn = 3

    # 8. Initialize Simulation
    scSim.InitializeSimulation()

    posRef = scObject.dynManager.getStateObject(scObject.hub.nameOfHubPosition)
    velRef = scObject.dynManager.getStateObject(scObject.hub.nameOfHubVelocity)

    # -------------------------------------------------------------
    # PHASE 1: Combined Stack Orbit up to Release Time T
    # -------------------------------------------------------------
    print(f"\n[Phase 1] Simulating combined stack orbit for {t_release_sec:.1f} s...")
    scSim.ConfigureStopTime(macros.sec2nano(t_release_sec))
    scSim.ExecuteSimulation()

    # -------------------------------------------------------------
    # PHASE 2: Release Event & Deorbit Burn
    # -------------------------------------------------------------
    print(f"[Phase 2] Executing spacecraft release event at T = {t_release_sec:.1f} s:")
    print(f"          - Lander separates from propulsion module.")
    print(f"          - Lander mass is now {m_lander:.1f} kg.")
    scObject.hub.mHub = m_lander

    r_curr = simHelpers.EigenVector3d2np(posRef.getState())
    v_curr = simHelpers.EigenVector3d2np(velRef.getState())
    r_mag = np.linalg.norm(r_curr)
    v_mag = np.linalg.norm(v_curr)

    # Calculate required Delta-V for Hohmann transfer to 15 km periapsis
    r_target_periapsis = r_moon + (h_target_pdi_km * 1000.0)
    a_transfer = (r_mag + r_target_periapsis) / 2.0
    v_target_apo = math.sqrt(mu * (2.0 / r_mag - 1.0 / a_transfer))
    delta_v_mag = v_mag - v_target_apo  # Retrograde impulse

    v_hat = v_curr / v_mag
    v_new = v_curr - (delta_v_mag * v_hat)
    velRef.setState(v_new)

    print(f"          - Executing retrograde deorbit burn: Delta-V = {delta_v_mag:.2f} m/s")
    print(f"          - Pre-burn orbital speed: {v_mag:.2f} m/s -> Post-burn: {np.linalg.norm(v_new):.2f} m/s")

    # Half orbital period of transfer ellipse to reach periapsis
    t_transfer_half_sec = math.pi * math.sqrt((a_transfer ** 3) / mu)
    t_pdi_total_sec = t_release_sec + t_transfer_half_sec
    print(f"          - Coast duration to periapsis (PDI): {t_transfer_half_sec:.1f} s ({t_transfer_half_sec/60.0:.2f} min)")

    # -------------------------------------------------------------
    # PHASE 3: Coast to Powered-Descent Initiation (Periapsis)
    # -------------------------------------------------------------
    print(f"[Phase 3] Coasting down to periapsis altitude (~{h_target_pdi_km:.1f} km)...")
    scSim.ConfigureStopTime(macros.sec2nano(t_pdi_total_sec))
    scSim.ExecuteSimulation()

    # -------------------------------------------------------------
    # Retrieve Final State at Descent Start (PDI)
    # -------------------------------------------------------------
    r_pdi = simHelpers.EigenVector3d2np(posRef.getState())
    v_pdi = simHelpers.EigenVector3d2np(velRef.getState())
    r_pdi_mag = np.linalg.norm(r_pdi)
    v_pdi_mag = np.linalg.norm(v_pdi)
    h_pdi_km = (r_pdi_mag - r_moon) / 1000.0

    print("\n" + "=" * 65)
    print("SIMULATION RESULTS: POWERED DESCENT INITIATION (PDI)")
    print("=" * 65)
    print(f"Periapsis Altitude at Descent Start: {h_pdi_km:.2f} km")
    print(f"Time to Descent Start (from burn):   {t_transfer_half_sec:.1f} s ({t_transfer_half_sec/60.0:.2f} min)")
    print(f"Total Simulation Epoch at PDI:       {t_pdi_total_sec:.1f} s ({t_pdi_total_sec/60.0:.2f} min)")
    print(f"Orbital Velocity at PDI:             {v_pdi_mag:.2f} m/s")
    print(f"Lander Mass at PDI:                  {m_lander:.1f} kg")
    print(f"Position Inertial [m]:               [{r_pdi[0]:.1f}, {r_pdi[1]:.1f}, {r_pdi[2]:.1f}]")
    print(f"Velocity Inertial [m/s]:             [{v_pdi[0]:.2f}, {v_pdi[1]:.2f}, {v_pdi[2]:.2f}]")
    print("=" * 65)

    # 9. Save State to runs/basilisk/pdi_state.json
    pdi_data = {
        "mission": cfg.get("mission_name", "Adinfinitum"),
        "event": "Powered Descent Initiation (PDI)",
        "central_body": "Moon",
        "time_epoch_sec": round(float(t_pdi_total_sec), 2),
        "time_from_burn_sec": round(float(t_transfer_half_sec), 2),
        "periapsis_altitude_km": round(float(h_pdi_km), 3),
        "spacecraft_mass_kg": float(m_lander),
        "position_inertial_m": [float(r_pdi[0]), float(r_pdi[1]), float(r_pdi[2])],
        "velocity_inertial_mps": [float(v_pdi[0]), float(v_pdi[1]), float(v_pdi[2])],
        "target_region": target_region,
        "delta_v_deorbit_mps": round(float(delta_v_mag), 2),
        "vizard_file": vizard_filename
    }

    pdi_json_path = os.path.join(runs_dir, "pdi_state.json")
    with open(pdi_json_path, "w", encoding="utf-8") as f:
        json.dump(pdi_data, f, indent=2)
    print(f"\n[Saved] PDI state saved to: {pdi_json_path}")

    # 10. Extract timeseries & generate publication plot
    times_sec = dataRec.times() * macros.NANO2SEC
    r_history = dataRec.r_BN_N
    altitudes_km = (np.linalg.norm(r_history, axis=1) - r_moon) / 1000.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    fig.patch.set_facecolor('#0f172a')
    for ax in (ax1, ax2):
        ax.set_facecolor('#1e293b')
        ax.grid(True, linestyle='--', alpha=0.3, color='#94a3b8')
        ax.tick_params(colors='#e2e8f0', labelsize=10)
        for spine in ax.spines.values():
            spine.set_color('#475569')

    ax1.plot(times_sec / 60.0, altitudes_km, color='#38bdf8', linewidth=2.2, label='Spacecraft Altitude')
    ax1.axvline(t_release_sec / 60.0, color='#f59e0b', linestyle='--', linewidth=1.8, label=f'Separation & Deorbit Burn (T={t_release_sec/60:.1f}m)')
    ax1.axvline(t_pdi_total_sec / 60.0, color='#10b981', linestyle='--', linewidth=1.8, label=f'Descent Start / PDI (T={t_pdi_total_sec/60:.1f}m)')
    ax1.axhline(15.0, color='#ef4444', linestyle=':', alpha=0.7, label='Target PDI Periapsis (15 km)')
    ax1.set_ylabel('Altitude above Moon (km)', fontsize=11, fontweight='bold', color='#f8fafc')
    ax1.set_title('Adinfinitum: Lunar Orbit Insertion, Release & Deorbit Trajectory (Spec §5 & §7.2)',
                  fontsize=12, fontweight='bold', color='#f8fafc', pad=12)
    ax1.legend(loc='upper right', facecolor='#0f172a', edgecolor='#475569', labelcolor='#f8fafc', fontsize=9)

    ax2.plot(times_sec / 60.0, np.linalg.norm(dataRec.v_BN_N, axis=1), color='#a855f7', linewidth=2.0, label='Orbital Speed (m/s)')
    ax2.axvline(t_release_sec / 60.0, color='#f59e0b', linestyle='--', linewidth=1.8)
    ax2.axvline(t_pdi_total_sec / 60.0, color='#10b981', linestyle='--', linewidth=1.8)
    ax2.set_xlabel('Mission Elapsed Time (minutes)', fontsize=11, fontweight='bold', color='#f8fafc')
    ax2.set_ylabel('Speed (m/s)', fontsize=11, fontweight='bold', color='#f8fafc')
    ax2.legend(loc='upper left', facecolor='#0f172a', edgecolor='#475569', labelcolor='#f8fafc', fontsize=9)

    plt.tight_layout()

    plot_path_runs = os.path.join(runs_dir, "orbit_altitude_vs_time.png")
    plt.savefig(plot_path_runs, dpi=200, facecolor=fig.get_facecolor(), bbox_inches='tight')
    print(f"[Saved] Orbit trajectory plot saved to: {plot_path_runs}")

    docs_fig_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "figures")
    os.makedirs(docs_fig_dir, exist_ok=True)
    plot_path_docs = os.path.join(docs_fig_dir, "orbit_altitude_vs_time.png")
    plt.savefig(plot_path_docs, dpi=200, facecolor=fig.get_facecolor(), bbox_inches='tight')

    brain_fig = r"C:\Users\Priyanka Mokashi\.gemini\antigravity\brain\5dfd8fca-e4ba-42a3-bed9-b6a333ceb0d5\orbit_altitude_vs_time.png"
    plt.savefig(brain_fig, dpi=200, facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.close()

    if VIZ_AVAILABLE:
        print(f"[Saved] Vizard binary simulation stream saved to: {vizard_filename}")
    else:
        print("[Note] Vizard interface not linked; simulated states logged to JSON and PNG.")

    return h_pdi_km, t_transfer_half_sec


if __name__ == "__main__":
    show_plot_flag = "--show_plots" in sys.argv
    run_scenario(show_plots=show_plot_flag)
