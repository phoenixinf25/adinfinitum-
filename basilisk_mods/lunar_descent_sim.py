"""
basilisk_mods/lunar_descent_sim.py
==================================
Tanush's Lunar Lander Powered Descent & Touchdown Simulation.

Demonstrates closed-loop terminal descent trajectory landing on real terrain
using the Basilisk lunar terrain helper (basilisk_mods.lunar_terrain).

Physics & Kinematics (all units in METRES, SECONDS, KILOGRAMS):
- Lunar gravity parameter: mu_moon = 4.9048695e12 m^3/s^2 (G * M_moon)
- Reference lunar radius: R_MOON = 1,737,400.0 m (1737.4 km)
- Frame: Moon-Centred, Moon-Fixed (MOON_ME) frame [r_x, r_y, r_z] in METRES [m]
- Touchdown condition: altitude_above_ground(r_moon_fixed) <= 0.0 m
- Safe touchdown criteria:
    * Vertical velocity magnitude <= 2.0 m/s
    * Horizontal velocity magnitude <= 0.5 m/s
    * Local ground slope <= 15.0 deg

Context: Spec §7.2 Lunar Landing Simulation Architecture (Tanush / Arnav).
"""

from __future__ import annotations

import argparse
import math
from typing import Any

import numpy as np

from .lunar_terrain import (
    R_MOON_M,
    LunarTerrain,
    TouchdownReport,
    altitude_above_ground,
    check_touchdown,
    latlon_from_moon_fixed,
    moon_fixed_from_ps,
    ps_from_moon_fixed,
    touchdown_check,
)

# Standard Moon gravitational parameter in m^3/s^2
MU_MOON_M3_S2: float = 4.9048695e12


def simulate_lunar_descent(
    region: str = "demo_craters",
    tiles_dir: str = "data/tiles",
    initial_alt_above_ground_m: float = 600.0,
    target_x_offset_m: float = 0.0,
    target_y_offset_m: float = 0.0,
    dt_sec: float = 0.1,
    max_sim_time_sec: float = 120.0,
    verbose: bool = True
) -> dict[str, Any]:
    """
    Simulate a powered descent landing onto real DEM terrain.

    Parameters:
        region: Terrain tile name (e.g. 'demo_craters' or 'shackleton').
        tiles_dir: Directory containing tile .npz files.
        initial_alt_above_ground_m: Initial clearance above ground in METRES [m] (default: 600 m).
        target_x_offset_m: Horizontal offset from tile center Easting in METRES [m].
        target_y_offset_m: Horizontal offset from tile center Northing in METRES [m].
        dt_sec: Simulation integration timestep in SECONDS [s] (default: 0.1 s).
        max_sim_time_sec: Maximum timeout in SECONDS [s] (default: 120 s).
        verbose: Print turn-by-turn telemetry log (default: True).

    Returns:
        dict[str, Any]: Final landing results and trajectory history.
    """
    terrain = LunarTerrain(region, tiles_dir=tiles_dir)

    # Landing target location in polar stereographic coordinates [m]
    target_x_m = terrain.center_x_m + target_x_offset_m
    target_y_m = terrain.center_y_m + target_y_offset_m
    target_ground_h_m = float(terrain.ground_height(target_x_m, target_y_m))

    # Initial spacecraft position in polar stereographic + altitude above sphere
    init_alt_sphere_m = target_ground_h_m + initial_alt_above_ground_m
    r_me = moon_fixed_from_ps(target_x_m, target_y_m, alt_sphere_m=init_alt_sphere_m, r_moon_radius_m=R_MOON_M)

    # Initial velocity: descending vertically towards lunar center with a slight horizontal drift
    r_norm = np.linalg.norm(r_me)
    r_hat = r_me / r_norm
    # Initial vertical speed: -18.0 m/s (downward)
    v_vert_init = -18.0
    # Small initial cross-track velocity to test lateral nulling
    v_horiz_init = np.cross(r_hat, np.array([0.0, 1.0, 0.0]))
    v_horiz_init = v_horiz_init / np.linalg.norm(v_horiz_init) * 2.5
    v_me = v_vert_init * r_hat + v_horiz_init

    if verbose:
        print("=" * 72)
        print(f"LUNAR POWERED DESCENT SIMULATION: {terrain.region.upper()}")
        print(f"Target PS coords: ({target_x_m:.1f} m, {target_y_m:.1f} m)")
        print(f"Target Ground Elevation: {target_ground_h_m:.2f} m above reference sphere")
        print(f"Initial Altitude Above Ground: {initial_alt_above_ground_m:.2f} m")
        print(f"Initial Vertical Velocity: {v_vert_init:.2f} m/s")
        print("=" * 72)

    time_sec = 0.0
    trajectory = []
    final_report: TouchdownReport | None = None

    # Autonomous guidance gains for terminal descent
    # Desired vertical velocity profile: v_des = -sqrt(2 * a_const * h) clamped to -1.0 m/s near ground
    while time_sec <= max_sim_time_sec:
        r_norm = float(np.linalg.norm(r_me))
        r_hat = r_me / r_norm

        # Query real terrain elevation and ground clearance
        h_clearance_m = terrain.altitude_above_ground(r_me)
        x_ps_m, y_ps_m, alt_sphere_m = ps_from_moon_fixed(r_me, R_MOON_M)
        local_slope_deg = float(terrain.slope(x_ps_m, y_ps_m))

        v_vert_mps = float(np.dot(v_me, r_hat))
        v_horiz_vec = v_me - v_vert_mps * r_hat
        v_horiz_mps = float(np.linalg.norm(v_horiz_vec))

        # Check touchdown via Tanush's touchdown check
        report = terrain.check_touchdown(
            r_moon_fixed=r_me,
            v_moon_fixed=v_me,
            touchdown_threshold_m=0.0,
            max_touchdown_v_mps=2.0,
            max_slope_deg=15.0
        )

        trajectory.append({
            "time_sec": time_sec,
            "alt_above_ground_m": h_clearance_m,
            "alt_above_sphere_m": alt_sphere_m,
            "ground_height_m": alt_sphere_m - h_clearance_m,
            "v_vert_mps": v_vert_mps,
            "v_horiz_mps": v_horiz_mps,
            "slope_deg": local_slope_deg,
            "x_ps_m": x_ps_m,
            "y_ps_m": y_ps_m
        })

        if report.contact:
            final_report = report
            if verbose:
                print(f"\n>>> [TOUCHDOWN EVENT at t = {time_sec:.2f} s] <<<")
                print(f"  Ground clearance:     {report.altitude_above_ground_m:+.3f} m")
                print(f"  Final ground height:  {report.ground_height_m:.2f} m")
                print(f"  Terrain slope:        {report.terrain_slope_deg:.2f} deg")
                print(f"  Touchdown vertical v: {abs(report.vertical_velocity_mps or 0.0):.2f} m/s")
                print(f"  Touchdown horizontal: {report.horizontal_speed_mps or 0.0:.2f} m/s")
                print(f"  Landing status:       {report.status}")
                print(f"  Safety assessment:    {'SAFE TOUCHDOWN' if report.is_safe else 'TOUCHDOWN CRITICAL'}")
            break

        # Lunar gravity vector towards Moon center
        g_accel_mag = MU_MOON_M3_S2 / (r_norm * r_norm)
        a_grav = -g_accel_mag * r_hat

        # Guidance: compute commanded thrust acceleration
        # Target vertical velocity as function of altitude above ground
        if h_clearance_m > 100.0:
            target_v_vert = -math.sqrt(max(1.0, 2.0 * 0.8 * (h_clearance_m - 80.0))) - 2.0
            target_v_vert = max(-25.0, target_v_vert)
        elif h_clearance_m > 15.0:
            target_v_vert = -2.5 - 0.05 * h_clearance_m
        else:
            # Constant terminal deceleration down to touchdown velocity ~1.0 m/s
            target_v_vert = -0.95

        # Proportional-Derivative acceleration command
        kp_vert = 1.2
        a_thrust_vert = (g_accel_mag + kp_vert * (target_v_vert - v_vert_mps)) * r_hat

        # Null horizontal velocity
        kp_horiz = 1.5
        a_thrust_horiz = -kp_horiz * v_horiz_vec

        a_thrust_total = a_thrust_vert + a_thrust_horiz

        # Total acceleration
        a_total = a_grav + a_thrust_total

        # Semi-implicit Euler integration
        v_me = v_me + a_total * dt_sec
        r_me = r_me + v_me * dt_sec
        time_sec += dt_sec

    if final_report is None:
        final_report = terrain.check_touchdown(r_me, v_me)

    lat_deg, lon_deg, _ = latlon_from_moon_fixed(r_me)

    return {
        "region": region,
        "touchdown": final_report.contact,
        "is_safe": final_report.is_safe,
        "status": final_report.status,
        "time_sec": time_sec,
        "final_clearance_m": final_report.altitude_above_ground_m,
        "final_ground_h_m": final_report.ground_height_m,
        "final_slope_deg": final_report.terrain_slope_deg,
        "final_v_vert_mps": final_report.vertical_velocity_mps,
        "final_v_horiz_mps": final_report.horizontal_speed_mps,
        "landing_lat_deg": lat_deg,
        "landing_lon_deg": lon_deg,
        "trajectory_steps": len(trajectory)
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate Lunar Lander Powered Descent onto Real Terrain")
    parser.add_argument("--region", default="demo_craters", help="Terrain tile (default: demo_craters)")
    parser.add_argument("--alt", type=float, default=600.0, help="Initial altitude above ground in METRES [m]")
    args = parser.parse_args()

    result = simulate_lunar_descent(region=args.region, initial_alt_above_ground_m=args.alt)
    print("\nDescent Simulation Result Summary:")
    print(f"  Touchdown: {result['touchdown']}")
    print(f"  Safe:      {result['is_safe']}")
    print(f"  Status:    {result['status']}")
    print(f"  Time:      {result['time_sec']:.2f} s")
    print(f"  Lat/Lon:   ({result['landing_lat_deg']:.4f} deg, {result['landing_lon_deg']:.4f} deg)")
