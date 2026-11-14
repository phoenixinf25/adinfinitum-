"""
tests/test_rover.py
===================
Unit test suite for basilisk_mods.rover and scenario_rover.

Verifies:
1. Rover configuration: 25 kg mass, strictly 0.01 m/s kinematic speed, 50 W solar panel.
2. Motion kinematics: distance traveled strictly respects 0.01 m/s * dt.
3. Slope limit enforcement: vehicle stops when slope > max_slope_deg.
4. Power subsystem: 50 W array charges in sunlight (+20 W net), discharges in shadow (-30 W net).
5. Line-of-sight RF communications ray casting over real DEM topography.
6. Multi-waypoint navigation: reaches 2 science waypoints and returns to the lander.
7. Telemetry flight logging to runs/basilisk/rover_<id>.csv.
8. Vizard 3D rover body OBJ export.
"""

from __future__ import annotations

import csv
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from basilisk_mods.lunar_terrain import LunarTerrain
from basilisk_mods.rover import (
    LunarRover,
    RoverConfig,
    RoverState,
    export_rover_vizard_mesh,
)
from scenario_rover import run_rover_scenario


class TestLunarRoverSubsystems(unittest.TestCase):
    """Test individual rover subsystems: motion, slope hazard, power, and comms."""

    @classmethod
    def setUpClass(cls):
        cls.terrain = LunarTerrain("demo_craters", tiles_dir="data/tiles")

    def test_rover_config_defaults(self):
        """Verify baseline rover specifications match Spec §4.3 (25 kg, 0.01 m/s, 50 W panel)."""
        cfg = RoverConfig()
        self.assertAlmostEqual(cfg.mass_kg, 25.0, places=1)
        self.assertAlmostEqual(cfg.speed_mps, 0.01, places=4)
        self.assertAlmostEqual(cfg.solar_rated_power_w, 50.0, places=1)
        self.assertAlmostEqual(cfg.drive_power_w, 30.0, places=1)
        self.assertAlmostEqual(cfg.standby_power_w, 10.0, places=1)
        self.assertAlmostEqual(cfg.max_slope_deg, 15.0, places=1)

    def test_kinematic_speed_strict(self):
        """Rover motion must strictly advance at speed_mps (0.01 m/s = 1 cm/s)."""
        cfg = RoverConfig(speed_mps=0.01, initial_battery_wh=100.0)
        lander_xy = (0.0, -2050.0)
        target_xy = [(0.0, -2000.0)]  # 50 m straight North

        rover = LunarRover(cfg, self.terrain, lander_xy, target_xy)
        dt = 50.0  # 50 seconds -> expected move: 50 s * 0.01 m/s = 0.50 m
        state = rover.step(dt)

        expected_dist = 50.0 * 0.01
        actual_dist = math.hypot(rover.x_m - lander_xy[0], rover.y_m - lander_xy[1])
        self.assertAlmostEqual(actual_dist, expected_dist, delta=1e-4)
        self.assertAlmostEqual(state.speed_mps, 0.01, delta=1e-5)

    def test_slope_limit_halts_vehicle(self):
        """Rover must stop and set is_stopped_slope=True if local slope exceeds max_slope_deg."""
        # Config with strict 5 deg slope limit placed on a 10 deg slope
        cfg = RoverConfig(max_slope_deg=5.0)
        # Center of demo_craters has slope ~10.7 deg
        lander_xy = (float(self.terrain.center_x_m), float(self.terrain.center_y_m))
        target_xy = [(lander_xy[0] + 10.0, lander_xy[1])]

        rover = LunarRover(cfg, self.terrain, lander_xy, target_xy)
        state = rover.step(10.0)

        self.assertTrue(rover.is_stopped_slope)
        self.assertFalse(rover.is_driving)
        self.assertEqual(state.speed_mps, 0.0)
        self.assertIn("HALTED_STEEP_SLOPE", state.status)

    def test_power_budget_sunlight_vs_shadow(self):
        """
        Verify power budget:
        - In direct sunlight (sun_fraction=1.0): 50 W solar - 30 W drive = +20 W net charging.
        - In shadow (sun_fraction=0.0): 0 W solar - 30 W drive = -30 W net discharging.
        """
        cfg = RoverConfig(
            solar_rated_power_w=50.0,
            drive_power_w=30.0,
            initial_battery_wh=50.0,
            battery_capacity_wh=120.0
        )
        lander_xy = (0.0, -2050.0)
        target_xy = [(10.0, -2050.0)]

        # 1. Drive in 100% sunlight for 1 hour (3600 s)
        rover_sun = LunarRover(cfg, self.terrain, lander_xy, target_xy,
                               sun_fraction_fn=lambda x, y, t: 1.0)
        rover_sun.step(3600.0)
        # +20 W for 1 h -> +20 Wh gain
        self.assertAlmostEqual(rover_sun.battery_wh, 50.0 + 20.0, delta=0.5)

        # 2. Drive in 100% shadow for 1 hour (3600 s)
        rover_shadow = LunarRover(cfg, self.terrain, lander_xy, target_xy,
                                  sun_fraction_fn=lambda x, y, t: 0.0)
        rover_shadow.step(3600.0)
        # -30 W for 1 h -> -30 Wh loss
        self.assertAlmostEqual(rover_shadow.battery_wh, 50.0 - 30.0, delta=0.5)

    def test_line_of_sight_comms(self):
        """Verify Line-of-Sight RF link logic between rover and lander."""
        cfg = RoverConfig(lander_antenna_height_m=2.5, rover_antenna_height_m=0.8)
        lander_xy = (0.0, -2050.0)
        rover = LunarRover(cfg, self.terrain, lander_xy, [(10.0, -2050.0)])

        # Clear line of sight on flat terrain 10m away
        z_rover = float(self.terrain.ground_height(10.0, -2050.0))
        has_los = rover.check_line_of_sight(10.0, -2050.0, z_rover)
        self.assertTrue(has_los)


class TestRoverScenarioExecution(unittest.TestCase):
    """Test full multi-waypoint science traverse mission."""

    def test_full_scenario_execution(self):
        """
        Execute full mission:
        - Rover reaches 2 waypoints and returns to the lander
        - Respects speed and slope limits
        - Dips into shadow and recovers battery
        """
        results = run_rover_scenario(
            region="demo_craters",
            rover_id="test_rover",
            dt_sec=30.0,
            verbose=False
        )

        self.assertTrue(results["speed_check_passed"], "Speed limit check failed.")
        self.assertTrue(results["slope_check_passed"], "Slope limit check failed.")
        self.assertTrue(results["shadow_entered"], "Rover did not enter cold-trap shadow.")
        self.assertTrue(results["shadow_exited"], "Rover did not exit shadow back to sunlight.")
        self.assertTrue(results["waypoints_completed"], "Rover failed to complete waypoints and return to lander.")
        self.assertTrue(results["is_returned"], "Rover is_returned flag is False.")

        # Check CSV output
        csv_path = Path(results["csv_log_path"])
        self.assertTrue(csv_path.exists())
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertGreater(len(rows), 50)
            # Check required columns
            for col in ["time_s", "x_m", "y_m", "battery_wh", "sun_fraction", "link_los"]:
                self.assertIn(col, reader.fieldnames)

    def test_vizard_rover_mesh_export(self):
        """Verify export_rover_vizard_mesh produces a valid Wavefront OBJ file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_obj = Path(tmpdir) / "test_rover.obj"
            export_rover_vizard_mesh(out_obj)
            self.assertTrue(out_obj.exists())
            self.assertGreater(out_obj.stat().st_size, 500)

            # Check vertex and face lines
            v_cnt, f_cnt = 0, 0
            with open(out_obj, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("v "):
                        v_cnt += 1
                    elif line.startswith("f "):
                        f_cnt += 1
            self.assertGreater(v_cnt, 8)
            self.assertGreater(f_cnt, 10)


if __name__ == "__main__":
    unittest.main()
