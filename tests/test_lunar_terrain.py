"""
tests/test_lunar_terrain.py
===========================
Unit test suite for basilisk_mods.lunar_terrain and descent touchdown simulation.

Tests:
1. Coordinate transformations (ps_from_moon_fixed, moon_fixed_from_ps) on 3 known points from Imok.
2. Bilinear interpolation of terrain elevation and slope against known grid points.
3. Spacecraft altitude above ground calculation (metres).
4. Tanush's touchdown check and powered descent simulation.
5. Wavefront OBJ mesh generation for Vizard (heights x 1, vertical exaggeration).
6. Units documentation in function docstrings.
"""

from __future__ import annotations

import inspect
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from basilisk_mods.lunar_descent_sim import simulate_lunar_descent
from basilisk_mods.lunar_terrain import (
    R_MOON_KM,
    R_MOON_M,
    LunarTerrain,
    altitude_above_ground,
    check_touchdown,
    export_to_obj,
    ground_height,
    latlon_from_moon_fixed,
    load_tile,
    moon_fixed_from_latlon,
    moon_fixed_from_ps,
    ps_from_moon_fixed,
    slope,
    touchdown_check,
)


class TestLunarTerrainTransformations(unittest.TestCase):
    """Test coordinate transformations between MOON_ME frame and South Polar Stereographic."""

    def test_constants(self):
        """Verify lunar mean spherical radius constants."""
        self.assertAlmostEqual(R_MOON_M, 1737400.0, places=1)
        self.assertAlmostEqual(R_MOON_KM, 1737.4, places=2)
        self.assertAlmostEqual(R_MOON_M, R_MOON_KM * 1000.0, places=1)

    def test_ps_from_moon_fixed_three_known_points(self):
        """
        Verify ps_from_moon_fixed on 3 canonical benchmark points from Imok:
        Point 1: South Pole nadir (lat = -90.0 deg, alt = +1500.0 m)
        Point 2: Sub-Earth Shackleton crater rim (lat = -89.9 deg, lon = 0.0 deg, alt = +250.0 m)
        Point 3: Quadrant ridge (lat = -87.0 deg, lon = +90.0 deg East, alt = +5000.0 m)
        """
        # Point 1: South Pole
        # r = R + 1500 m along negative Z axis
        r_pt1 = np.array([0.0, 0.0, -(R_MOON_M + 1500.0)], dtype=np.float64)
        x1, y1, alt1 = ps_from_moon_fixed(r_pt1)
        self.assertAlmostEqual(x1, 0.0, delta=1e-3)
        self.assertAlmostEqual(y1, 0.0, delta=1e-3)
        self.assertAlmostEqual(alt1, 1500.0, delta=1e-3)

        # Point 2: Sub-Earth Prime Meridian (-89.9 deg lat, 0.0 deg lon, alt = +250.0 m)
        # Expected: x = 0, y = -2 * R * tan(0.1 deg / 2) = -3032.3358 m
        r_total_2 = R_MOON_M + 250.0
        lat2_rad = math.radians(-89.9)
        lon2_rad = math.radians(0.0)
        r_pt2 = np.array([
            r_total_2 * math.cos(lat2_rad) * math.cos(lon2_rad),
            r_total_2 * math.cos(lat2_rad) * math.sin(lon2_rad),
            r_total_2 * math.sin(lat2_rad)
        ], dtype=np.float64)

        x2, y2, alt2 = ps_from_moon_fixed(r_pt2)
        expected_rho_2 = 2.0 * R_MOON_M * math.tan(math.radians(0.1) / 2.0)
        self.assertAlmostEqual(x2, 0.0, delta=1e-3)
        self.assertAlmostEqual(y2, -expected_rho_2, delta=1e-3)
        self.assertAlmostEqual(alt2, 250.0, delta=1e-3)

        # Point 3: Quadrant ridge (-87.0 deg lat, +90.0 deg lon, alt = +5000.0 m)
        # Expected: rho = 2 * R * tan(3.0 deg / 2) = 90990.8403 m, x = +rho, y = 0
        r_total_3 = R_MOON_M + 5000.0
        lat3_rad = math.radians(-87.0)
        lon3_rad = math.radians(90.0)
        r_pt3 = np.array([
            r_total_3 * math.cos(lat3_rad) * math.cos(lon3_rad),
            r_total_3 * math.cos(lat3_rad) * math.sin(lon3_rad),
            r_total_3 * math.sin(lat3_rad)
        ], dtype=np.float64)

        x3, y3, alt3 = ps_from_moon_fixed(r_pt3)
        expected_rho_3 = 2.0 * R_MOON_M * math.tan(math.radians(3.0) / 2.0)
        self.assertAlmostEqual(x3, expected_rho_3, delta=1e-3)
        self.assertAlmostEqual(y3, 0.0, delta=1e-3)
        self.assertAlmostEqual(alt3, 5000.0, delta=1e-3)

    def test_round_trip_ps_and_moon_fixed(self):
        """Verify round-trip transformation consistency: moon_fixed -> ps -> moon_fixed."""
        test_positions = [
            np.array([0.0, 0.0, -1737400.0]),
            np.array([3032.77, 0.0, -1737647.35]),
            np.array([0.0, 91190.17, -1740012.10]),
            np.array([-5000.0, 12000.0, -1735000.0]),
            np.array([15000.0, -25000.0, -1730000.0]),
        ]
        for r_orig in test_positions:
            x, y, alt = ps_from_moon_fixed(r_orig)
            r_recovered = moon_fixed_from_ps(x, y, alt)
            np.testing.assert_allclose(r_recovered, r_orig, atol=1e-4)

    def test_latlon_helpers(self):
        """Test latlon conversions to/from MOON_ME."""
        r_orig = np.array([1000.0, 2000.0, -(R_MOON_M + 500.0)])
        lat, lon, alt = latlon_from_moon_fixed(r_orig)
        r_rec = moon_fixed_from_latlon(lat, lon, alt)
        np.testing.assert_allclose(r_rec, r_orig, atol=1e-4)


class TestLunarTerrainInterpolation(unittest.TestCase):
    """Test DEM tile loading and bilinear interpolation."""

    @classmethod
    def setUpClass(cls):
        cls.terrain = LunarTerrain("demo_craters", tiles_dir="data/tiles")
        load_tile("demo_craters", tiles_dir="data/tiles")

    def test_tile_properties(self):
        """Verify loaded tile metadata and array shapes."""
        self.assertEqual(self.terrain.H, 400)
        self.assertEqual(self.terrain.W, 400)
        self.assertEqual(self.terrain.mpp, 5.0)
        self.assertEqual(self.terrain.region, "demo_craters")
        self.assertAlmostEqual(self.terrain.center_lat_deg, -89.9, places=3)
        self.assertAlmostEqual(self.terrain.center_lon_deg, 0.0, places=3)

    def test_known_points_exact_node_interpolation(self):
        """Points sampled exactly at grid nodes must match tile height within numerical tolerance."""
        # Test 5 distinct node locations
        sample_indices = [(0, 0), (100, 150), (200, 200), (350, 120), (399, 399)]
        for r, c in sample_indices:
            x_node = self.terrain.x_coords_m[c]
            y_node = self.terrain.y_coords_m[r]
            expected_h = float(self.terrain.height_m[r, c])
            expected_s = float(self.terrain.slope_deg[r, c])

            interp_h = float(self.terrain.ground_height(x_node, y_node))
            interp_s = float(self.terrain.slope(x_node, y_node))

            self.assertAlmostEqual(interp_h, expected_h, delta=1e-3,
                                   msg=f"Height mismatch at node ({r}, {c})")
            self.assertAlmostEqual(interp_s, expected_s, delta=1e-3,
                                   msg=f"Slope mismatch at node ({r}, {c})")

    def test_midpoint_bilinear_interpolation(self):
        """Points midway between 4 nodes must equal the average of the 4 corner heights."""
        r, c = 200, 200
        x0 = self.terrain.x_coords_m[c]
        x1 = self.terrain.x_coords_m[c + 1]
        y0 = self.terrain.y_coords_m[r]
        y1 = self.terrain.y_coords_m[r + 1]

        x_mid = 0.5 * (x0 + x1)
        y_mid = 0.5 * (y0 + y1)

        expected_mid_h = 0.25 * (
            self.terrain.height_m[r, c] +
            self.terrain.height_m[r, c + 1] +
            self.terrain.height_m[r + 1, c] +
            self.terrain.height_m[r + 1, c + 1]
        )

        interp_mid_h = float(self.terrain.ground_height(x_mid, y_mid))
        self.assertAlmostEqual(interp_mid_h, expected_mid_h, delta=1e-3)

    def test_vectorized_interpolation(self):
        """Vectorized interpolation queries must match scalar queries."""
        xs = np.linspace(-100.0, 100.0, 10)
        ys = self.terrain.center_y_m + np.linspace(-100.0, 100.0, 10)

        vec_h = self.terrain.ground_height(xs, ys)
        self.assertIsInstance(vec_h, np.ndarray)
        self.assertEqual(len(vec_h), 10)

        for i in range(10):
            scalar_h = self.terrain.ground_height(xs[i], ys[i])
            self.assertAlmostEqual(vec_h[i], scalar_h, places=4)

    def test_module_level_helpers(self):
        """Verify module-level ground_height, slope, altitude_above_ground helpers."""
        x = float(self.terrain.center_x_m)
        y = float(self.terrain.center_y_m)
        gh = ground_height(x, y)
        sl = slope(x, y)
        self.assertIsInstance(gh, float)
        self.assertIsInstance(sl, float)

        # Spacecraft 500 m above terrain center
        r_sc = moon_fixed_from_ps(x, y, alt_sphere_m=gh + 500.0)
        clearance = altitude_above_ground(r_sc)
        self.assertAlmostEqual(clearance, 500.0, delta=1e-2)


class TestTouchdownCheckAndDescent(unittest.TestCase):
    """Test Tanush's touchdown check evaluator and closed-loop descent simulation."""

    @classmethod
    def setUpClass(cls):
        cls.terrain = LunarTerrain("demo_craters", tiles_dir="data/tiles")

    def test_touchdown_check_airborne(self):
        """Spacecraft above ground must return contact=False, AIRBORNE_DESCENT."""
        x = self.terrain.center_x_m
        y = self.terrain.center_y_m
        gh = self.terrain.ground_height(x, y)

        r_sc = moon_fixed_from_ps(x, y, alt_sphere_m=gh + 120.0)
        v_sc = np.array([0.0, 0.0, 10.0])

        report = check_touchdown(r_sc, v_sc)
        self.assertFalse(report.contact)
        self.assertFalse(report.is_safe)
        self.assertEqual(report.status, "AIRBORNE_DESCENT")
        self.assertAlmostEqual(report.altitude_above_ground_m, 120.0, delta=1e-2)

    def test_touchdown_check_nominal_contact(self):
        """Spacecraft making contact with safe velocity and slope must return TOUCHDOWN_NOMINAL."""
        x = self.terrain.center_x_m
        y = self.terrain.center_y_m
        gh = self.terrain.ground_height(x, y)

        # Contact position (clearance = -0.01 m)
        r_contact = moon_fixed_from_ps(x, y, alt_sphere_m=gh - 0.01)
        r_hat = r_contact / np.linalg.norm(r_contact)
        v_contact = -1.2 * r_hat  # descending at 1.2 m/s (< 2.0 m/s limit)

        report = touchdown_check(r_contact, v_contact, max_slope_deg=20.0)
        self.assertTrue(report.contact)
        self.assertTrue(report.is_safe)
        self.assertEqual(report.status, "TOUCHDOWN_NOMINAL")

    def test_touchdown_check_hard_landing_failure(self):
        """Excessive touchdown velocity must flag TOUCHDOWN_FAILED with velocity reason."""
        x = self.terrain.center_x_m
        y = self.terrain.center_y_m
        gh = self.terrain.ground_height(x, y)

        r_contact = moon_fixed_from_ps(x, y, alt_sphere_m=gh - 0.01)
        r_hat = r_contact / np.linalg.norm(r_contact)
        v_hard = -4.5 * r_hat  # 4.5 m/s > 2.0 m/s limit

        report = check_touchdown(r_contact, v_hard, max_touchdown_v_mps=2.0)
        self.assertTrue(report.contact)
        self.assertFalse(report.is_safe)
        self.assertIn("EXCESSIVE_VERTICAL_VELOCITY", report.status)

    def test_simulate_lunar_descent_lands_on_real_terrain(self):
        """Closed-loop descent simulation lands on real DEM terrain and achieves safe touchdown."""
        result = simulate_lunar_descent(
            region="demo_craters",
            initial_alt_above_ground_m=200.0,
            verbose=False
        )
        self.assertTrue(result["touchdown"], "Descent simulation did not detect touchdown.")
        self.assertTrue(result["is_safe"], f"Descent touchdown flagged unsafe: {result['status']}")
        self.assertEqual(result["status"], "TOUCHDOWN_NOMINAL")
        self.assertLessEqual(abs(result["final_v_vert_mps"]), 2.0)
        self.assertLessEqual(result["final_slope_deg"], 15.0)


class TestWavefrontObjExport(unittest.TestCase):
    """Test OBJ mesh generation for Basilisk Vizard."""

    def test_export_to_obj_valid_file(self):
        """Verify exported OBJ has valid header, vertices, texture coords, normals, and faces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "test_terrain.obj"
            terrain = LunarTerrain("demo_craters", tiles_dir="data/tiles")
            # Export with step=4 for fast test execution
            res_path = export_to_obj(terrain, out_file, vertical_exaggeration=1.5, step=4)

            self.assertTrue(res_path.exists())
            self.assertGreater(res_path.stat().st_size, 1000)

            v_count = 0
            vt_count = 0
            vn_count = 0
            f_count = 0
            has_exaggeration_header = False

            with open(res_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "Vertical Exaggeration: 1.50x" in line:
                        has_exaggeration_header = True
                    if line.startswith("v "):
                        v_count += 1
                    elif line.startswith("vt "):
                        vt_count += 1
                    elif line.startswith("vn "):
                        vn_count += 1
                    elif line.startswith("f "):
                        f_count += 1

            self.assertTrue(has_exaggeration_header)
            self.assertEqual(v_count, 100 * 100)
            self.assertEqual(vt_count, 100 * 100)
            self.assertEqual(vn_count, 100 * 100)
            self.assertEqual(f_count, 99 * 99 * 2)


class TestDocstringUnits(unittest.TestCase):
    """Validate that every public function docstring clearly mentions units."""

    def test_function_docstrings_contain_units(self):
        """Verify units are explicitly documented in all public helper functions."""
        funcs = [
            ps_from_moon_fixed,
            moon_fixed_from_ps,
            latlon_from_moon_fixed,
            moon_fixed_from_latlon,
            ground_height,
            slope,
            altitude_above_ground,
            check_touchdown,
            export_to_obj,
            LunarTerrain.ground_height,
            LunarTerrain.slope,
            LunarTerrain.altitude_above_ground,
            LunarTerrain.check_touchdown,
            LunarTerrain.export_to_obj,
        ]

        for fn in funcs:
            doc = inspect.getdoc(fn)
            self.assertIsNotNone(doc, f"Function {fn.__name__} has no docstring!")
            doc_lower = doc.lower()
            self.assertTrue(
                "metre" in doc_lower or "meter" in doc_lower or "deg" in doc_lower or "[m]" in doc_lower,
                f"Function {fn.__name__} docstring does not mention units (metres/degrees)!"
            )


if __name__ == "__main__":
    unittest.main()
