# -*- coding: utf-8 -*-
"""
Main Lunar Descent Scenario Runner
Context: Adinfinitum (NASA Space Apps 2026), Spec §4.2 lander table, §5 phases 4-6.

Executes:
1. Nominal Descent Scenario (5 thrusters, Isp 310s, classic guidance to touchdown).
2. Engine-Out Demonstration Scenario (Thruster 2 fails at t = 120s, compensation active).
3. Verifies touchdown parameters against config limits (vertical <= 2 m/s, horiz <= 0.5 m/s, tilt <= 12 deg).
4. Emits per-second telemetry to runs/basilisk/telemetry_<id>.csv readable by Mission Control.
5. Saves Vizard binary visualization stream files.
6. Generates multi-panel trajectory comparison plots.
"""

import os
import sys
import json
import matplotlib.pyplot as plt
import numpy as np

# Add repo root and basilisk_mods to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
mods_dir = os.path.join(current_dir, "basilisk_mods")
if os.path.exists(mods_dir) and mods_dir not in sys.path:
    sys.path.insert(0, mods_dir)

try:
    from basilisk_mods.lander_descent import run_descent, LanderMissionConfig
except ImportError:
    from lander_descent import run_descent, LanderMissionConfig


def main():
    print("=" * 70)
    print("ADINFINITUM: POWERED DESCENT INITIATION TO TOUCHDOWN SIMULATION")
    print("Spec §4.2 Lander Propulsion & §5 Phases 4-6 Descent Guidance")
    print("=" * 70)

    # 1. Run Nominal Descent (All 5 Engines)
    nom_stat, nom_telem = run_descent(run_id="nominal", engine_out=False)

    # 2. Run Engine-Out Descent (1 Engine Fails at t = 120s)
    eo_stat, eo_telem = run_descent(run_id="engine_out", engine_out=True, engine_out_time=120.0)

    # 3. Export Summary JSON
    repo_root = current_dir if os.path.exists(os.path.join(current_dir, "config")) else os.path.dirname(current_dir)
    runs_dir = os.path.join(repo_root, "runs", "basilisk")
    os.makedirs(runs_dir, exist_ok=True)

    summary = {
        "mission": "Adinfinitum Lunar Lander",
        "nominal_run": nom_stat,
        "engine_out_run": eo_stat
    }

    summary_file = os.path.join(runs_dir, "descent_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[Saved] Descent summary saved to: {summary_file}")

    # 4. Generate Multi-Panel Comparison Plot
    nom_t = np.array([r["time"] for r in nom_telem])
    nom_alt = np.array([r["altitude_m"] for r in nom_telem]) / 1000.0
    nom_v_vert = np.array([r["v_vertical_mps"] for r in nom_telem])
    nom_v_horiz = np.array([r["v_horizontal_mps"] for r in nom_telem])
    nom_fuel = np.array([r["fuel_mass_kg"] for r in nom_telem])
    nom_thrust = np.array([r["total_thrust_N"] for r in nom_telem])

    eo_t = np.array([r["time"] for r in eo_telem])
    eo_alt = np.array([r["altitude_m"] for r in eo_telem]) / 1000.0
    eo_v_vert = np.array([r["v_vertical_mps"] for r in eo_telem])
    eo_v_horiz = np.array([r["v_horizontal_mps"] for r in eo_telem])
    eo_fuel = np.array([r["fuel_mass_kg"] for r in eo_telem])
    eo_thrust = np.array([r["total_thrust_N"] for r in eo_telem])

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.patch.set_facecolor('#0b0f19')

    for row in axes:
        for ax in row:
            ax.set_facecolor('#131a29')
            ax.grid(True, linestyle='--', alpha=0.25, color='#94a3b8')
            ax.tick_params(colors='#e2e8f0', labelsize=9)
            for s in ax.spines.values():
                s.set_color('#334155')

    # Panel 1: Altitude vs Time
    axes[0, 0].plot(nom_t / 60.0, nom_alt, color='#38bdf8', linewidth=2.0, label='Nominal (5 Thrusters)')
    axes[0, 0].plot(eo_t / 60.0, eo_alt, color='#f43f5e', linestyle='--', linewidth=2.0, label='Engine-Out (1 Failed @ t=120s)')
    axes[0, 0].axvline(120.0 / 60.0, color='#f59e0b', linestyle=':', label='Engine Flameout (t=2.0m)')
    axes[0, 0].set_ylabel('Altitude (km)', fontsize=10, fontweight='bold', color='#f8fafc')
    axes[0, 0].set_xlabel('Descent Time (minutes)', fontsize=10, fontweight='bold', color='#f8fafc')
    axes[0, 0].set_title('Altitude Profile: Nominal vs Engine-Out', fontsize=11, fontweight='bold', color='#f8fafc')
    axes[0, 0].legend(facecolor='#0b0f19', edgecolor='#334155', labelcolor='#f8fafc', fontsize=8.5)

    # Panel 2: Velocity Profile
    axes[0, 1].plot(nom_t / 60.0, nom_v_horiz, color='#a855f7', linewidth=2.0, label='Nominal Horizontal Speed')
    axes[0, 1].plot(nom_t / 60.0, abs(nom_v_vert), color='#10b981', linewidth=2.0, label='Nominal Vertical Speed')
    axes[0, 1].plot(eo_t / 60.0, eo_v_horiz, color='#ec4899', linestyle='--', linewidth=1.8, label='Engine-Out Horizontal')
    axes[0, 1].plot(eo_t / 60.0, abs(eo_v_vert), color='#34d399', linestyle='--', linewidth=1.8, label='Engine-Out Vertical')
    axes[0, 1].axhline(2.0, color='#ef4444', linestyle=':', label='Max Vertical Touchdown (2.0 m/s)')
    axes[0, 1].axhline(0.5, color='#fbbf24', linestyle=':', label='Max Horiz Touchdown (0.5 m/s)')
    axes[0, 1].set_ylabel('Velocity (m/s)', fontsize=10, fontweight='bold', color='#f8fafc')
    axes[0, 1].set_xlabel('Descent Time (minutes)', fontsize=10, fontweight='bold', color='#f8fafc')
    axes[0, 1].set_title('Velocity Deceleration: Horizontal & Vertical', fontsize=11, fontweight='bold', color='#f8fafc')
    axes[0, 1].legend(facecolor='#0b0f19', edgecolor='#334155', labelcolor='#f8fafc', fontsize=8)

    # Panel 3: Total Thrust Demands
    axes[1, 0].plot(nom_t / 60.0, nom_thrust, color='#38bdf8', linewidth=2.0, label='Nominal Total Thrust (5x 800N max)')
    axes[1, 0].plot(eo_t / 60.0, eo_thrust, color='#f43f5e', linestyle='--', linewidth=2.0, label='Engine-Out Thrust (4x 800N max)')
    axes[1, 0].axhline(4000.0, color='#64748b', linestyle=':', label='5-Engine Max (4,000 N)')
    axes[1, 0].axhline(3200.0, color='#ef4444', linestyle=':', label='4-Engine Cap (3,200 N)')
    axes[1, 0].set_ylabel('Total Thrust Force (N)', fontsize=10, fontweight='bold', color='#f8fafc')
    axes[1, 0].set_xlabel('Descent Time (minutes)', fontsize=10, fontweight='bold', color='#f8fafc')
    axes[1, 0].set_title('Propulsion Authority & Compensation', fontsize=11, fontweight='bold', color='#f8fafc')
    axes[1, 0].legend(facecolor='#0b0f19', edgecolor='#334155', labelcolor='#f8fafc', fontsize=8.5)

    # Panel 4: Fuel Mass Depletion
    axes[1, 1].plot(nom_t / 60.0, nom_fuel, color='#10b981', linewidth=2.0, label='Nominal Fuel Remaining')
    axes[1, 1].plot(eo_t / 60.0, eo_fuel, color='#f59e0b', linestyle='--', linewidth=2.0, label='Engine-Out Fuel Remaining')
    axes[1, 1].axhline(0.0, color='#ef4444', linestyle=':', label='Empty Tank Limit')
    axes[1, 1].set_ylabel('Propellant Mass (kg)', fontsize=10, fontweight='bold', color='#f8fafc')
    axes[1, 1].set_xlabel('Descent Time (minutes)', fontsize=10, fontweight='bold', color='#f8fafc')
    axes[1, 1].set_title('Fuel Depletion vs Time (Isp = 310 s)', fontsize=11, fontweight='bold', color='#f8fafc')
    axes[1, 1].legend(facecolor='#0b0f19', edgecolor='#334155', labelcolor='#f8fafc', fontsize=8.5)

    plt.suptitle('Adinfinitum: Powered Descent Guidance & Engine-Out Contingency Analysis (Spec §4.2 & §5)',
                 fontsize=13, fontweight='bold', color='#ffffff', y=0.99)
    plt.tight_layout()

    plot_file_runs = os.path.join(runs_dir, "descent_trajectory_comparison.png")
    plt.savefig(plot_file_runs, dpi=200, facecolor=fig.get_facecolor(), bbox_inches='tight')
    print(f"[Saved] Trajectory comparison plot saved to: {plot_file_runs}")

    docs_fig_dir = os.path.join(repo_root, "docs", "figures")
    os.makedirs(docs_fig_dir, exist_ok=True)
    plot_file_docs = os.path.join(docs_fig_dir, "descent_trajectory_comparison.png")
    plt.savefig(plot_file_docs, dpi=200, facecolor=fig.get_facecolor(), bbox_inches='tight')

    brain_fig = r"C:\Users\Priyanka Mokashi\.gemini\antigravity\brain\5dfd8fca-e4ba-42a3-bed9-b6a333ceb0d5\descent_trajectory_comparison.png"
    plt.savefig(brain_fig, dpi=200, facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.close()

    # 5. Final Mission Assessment
    print("\n" + "=" * 70)
    print("MISSION CONTROL TOUCHDOWN VERIFICATION TABLE")
    print("=" * 70)
    print(f"{'Metric':<28} | {'Nominal Run':<18} | {'Engine-Out Run':<18} | {'Limit':<12}")
    print("-" * 70)
    print(f"{'Vertical Touchdown Speed':<28} | {nom_stat['vertical_speed_mps']:<18.3f} | {eo_stat['vertical_speed_mps']:<18.3f} | <= 2.0 m/s")
    print(f"{'Horizontal Touchdown Speed':<28} | {nom_stat['horizontal_speed_mps']:<18.3f} | {eo_stat['horizontal_speed_mps']:<18.3f} | <= 0.5 m/s")
    print(f"{'Lander Tilt Angle':<28} | {nom_stat['tilt_deg']:<18.2f} | {eo_stat['tilt_deg']:<18.2f} | <= 12.0 deg")
    print(f"{'Remaining Fuel Mass':<28} | {nom_stat['fuel_remaining_kg']:<18.2f} | {eo_stat['fuel_remaining_kg']:<18.2f} | > 0.0 kg")
    print(f"{'Touchdown Elapsed Time':<28} | {nom_stat['touchdown_time_sec']:<18.1f} | {eo_stat['touchdown_time_sec']:<18.1f} | -")
    print(f"{'Status Assessment':<28} | [{nom_stat['status']:^16}] | [{eo_stat['status']:^16}] | PASS")
    print("=" * 70)

if __name__ == "__main__":
    main()
