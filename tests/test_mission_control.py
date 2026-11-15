"""Unit and integration tests for Mission Control Console (Spec §9.2, KAN-48).

Verifies:
- Loading telemetry fixture and real Basilisk flight logs via mission_control.data.
- 5-engine cluster fault parsing and autonomous balance detection.
- Decision log extraction.
- Countdown values matching Navigator physics exactly.
- Rover surface telemetry integration.
- Provenance badge discrimination (FIXTURE vs MODELLED · Basilisk).
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.paths import repo_root
from contracts.runs import TELEMETRY_COLUMNS
from mission_control.data import (
    extract_decisions,
    get_available_telemetry_files,
    get_site_countdowns,
    load_rover_telemetry,
    load_telemetry,
    parse_engine_cluster,
)


class TestMissionControlDataLoaders(unittest.TestCase):
    """Test loading telemetry datasets through the same functions used by the Streamlit console."""

    def setUp(self):
        self.root = repo_root()
        self.fixture_path = self.root / "tests" / "fixtures" / "telemetry_basilisk_engine_out.csv"
        self.engine_out_run = self.root / "runs" / "basilisk" / "telemetry_engine_out.csv"
        self.nominal_run = self.root / "runs" / "basilisk" / "telemetry_nominal.csv"

    def test_load_fixture_telemetry(self):
        """App loader must successfully read the stand-in fixture dataset."""
        self.assertTrue(self.fixture_path.exists(), f"Fixture missing: {self.fixture_path}")
        df = load_telemetry(self.fixture_path)
        
        self.assertEqual(len(df), 93, "Fixture should have exactly 93 rows")
        for col in TELEMETRY_COLUMNS:
            self.assertIn(col, df.columns, f"Required contract column missing: {col}")

        # Check numeric conversions
        self.assertTrue(pd.api.types.is_numeric_dtype(df["t_s"]))
        self.assertTrue(pd.api.types.is_numeric_dtype(df["alt_m"]))
        self.assertTrue(pd.api.types.is_numeric_dtype(df["vz_m_s"]))
        self.assertTrue(pd.api.types.is_numeric_dtype(df["fuel_kg"]))
        self.assertTrue(pd.api.types.is_numeric_dtype(df["thrust_n"]))

    def test_load_real_basilisk_telemetry(self):
        """App loader must successfully read Tanush's real closed-loop Basilisk flight telemetry."""
        if self.engine_out_run.exists():
            df = load_telemetry(self.engine_out_run)
            self.assertGreater(len(df), 50)
            self.assertEqual(df["phase"].iloc[-1], "touchdown")
            self.assertLessEqual(abs(df["vz_m_s"].iloc[-1]), 1.5, "Touchdown vertical velocity within limits")

        if self.nominal_run.exists():
            df_nom = load_telemetry(self.nominal_run)
            self.assertGreater(len(df_nom), 50)
            self.assertEqual(df_nom["phase"].iloc[-1], "touchdown")

    def test_file_discovery_and_fixture_labeling(self):
        """File discovery must distinguish fixtures from real Basilisk runs."""
        files = get_available_telemetry_files()
        self.assertGreaterEqual(len(files), 1)

        fixture_entries = [f for f in files if f.is_fixture]
        self.assertGreaterEqual(len(fixture_entries), 1)
        self.assertEqual(fixture_entries[0].source_label, "FIXTURE — STAND-IN")

        run_entries = [f for f in files if not f.is_fixture]
        if run_entries:
            self.assertEqual(run_entries[0].source_label, "MODELLED · Basilisk")


class TestPropulsionAndDecisionParsing(unittest.TestCase):
    """Test 5-engine cluster visualization and autonomous decision extraction."""

    def test_nominal_5_engine_cluster(self):
        """When engines_ok == 5, all 5 engines must report NOMINAL with equal thrust."""
        cluster = parse_engine_cluster(engines_ok=5, decision_text="", total_thrust_n=2000.0)
        self.assertEqual(cluster["active_count"], 5)
        self.assertFalse(cluster["e1_failed"])
        self.assertFalse(cluster["e3_balanced"])

        for eng in cluster["engines"]:
            self.assertEqual(eng.status, "NOMINAL")
            self.assertEqual(eng.color, "#00ff88")
            self.assertAlmostEqual(eng.thrust_n, 400.0, places=1)

    def test_engine_out_and_autonomous_balancing(self):
        """When Engine 1 fails, E1 must be FAILED (red) and opposite E3 must be OFF (balanced, amber)."""
        cluster = parse_engine_cluster(
            engines_ok=3,
            decision_text="engine 1 FAILED; shut down opposite engine 3 for balance -> 3 engines",
            total_thrust_n=2100.0,
        )
        self.assertEqual(cluster["active_count"], 3)
        self.assertTrue(cluster["e1_failed"])
        self.assertTrue(cluster["e3_balanced"])

        engines_by_id = {eng.id: eng for eng in cluster["engines"]}
        
        # E1 is failed (red)
        self.assertEqual(engines_by_id[1].status, "FAILED")
        self.assertEqual(engines_by_id[1].color, "#ff2a55")
        self.assertEqual(engines_by_id[1].thrust_n, 0.0)

        # E3 is shut down for torque balance (amber)
        self.assertEqual(engines_by_id[3].status, "OFF (BALANCED)")
        self.assertEqual(engines_by_id[3].color, "#ffaa00")
        self.assertEqual(engines_by_id[3].thrust_n, 0.0)

        # E2, E4, E5 are active (green, 700 N each)
        for e_id in (2, 4, 5):
            self.assertEqual(engines_by_id[e_id].status, "NOMINAL")
            self.assertEqual(engines_by_id[e_id].color, "#00ff88")
            self.assertAlmostEqual(engines_by_id[e_id].thrust_n, 700.0, places=1)

    def test_extract_decisions(self):
        """Extract decisions from telemetry dataframe without commentary text."""
        fixture_path = repo_root() / "tests" / "fixtures" / "telemetry_basilisk_engine_out.csv"
        df = load_telemetry(fixture_path)
        decisions = extract_decisions(df)

        self.assertGreaterEqual(len(decisions), 2)
        dec_texts = [d["decision"] for d in decisions]
        
        # Check presence of the real failure event
        has_failure_dec = any("engine 1 FAILED" in t for t in dec_texts)
        self.assertTrue(has_failure_dec, "Decision log must capture the engine failure event")

        # Check presence of touchdown event
        has_touchdown = any("TOUCHDOWN ok" in t for t in dec_texts)
        self.assertTrue(has_touchdown, "Decision log must capture touchdown")


class TestNavigatorCountdownAgreement(unittest.TestCase):
    """Verify that Mission Control countdown values match Navigator metrics exactly."""

    def test_countdowns_match_navigator_shackleton(self):
        """Countdowns computed by mission_control.data must match navigator.metrics."""
        from contracts.light import load_points
        from navigator.metrics import earth_countdown, format_hours, sun_countdown

        points_path = repo_root() / "data" / "light" / "shackleton_2026-11-14_points.npz"
        if not points_path.exists():
            self.skipTest("Light dataset not present")

        # Navigator direct physics calculation
        ps = load_points(points_path)
        expected_sun = sun_countdown(ps, 0)
        expected_earth = earth_countdown(ps, 0)
        expected_sun_str = f"{expected_sun.event}: {format_hours(expected_sun.hours)}"
        expected_earth_str = f"{expected_earth.event}: {format_hours(expected_earth.hours)}"

        # Mission control data query
        mc_cd = get_site_countdowns(site="shackleton", date="2026-11-14", step_hour=0)
        self.assertTrue(mc_cd["available"])
        self.assertEqual(mc_cd["sun_str"], expected_sun_str)
        self.assertEqual(mc_cd["earth_str"], expected_earth_str)
        self.assertEqual(mc_cd["sun_hours"], expected_sun.hours)
        self.assertEqual(mc_cd["earth_hours"], expected_earth.hours)


class TestRoverMiniPanelData(unittest.TestCase):
    """Verify rover mini-panel data loader."""

    def test_load_rover_telemetry(self):
        """Rover telemetry loader must read available rover CSV files."""
        rdf = load_rover_telemetry()
        if rdf is not None:
            self.assertIn("battery_pct", rdf.columns)
            self.assertIn("speed_mps", rdf.columns)
            self.assertIn("distance_to_lander_m", rdf.columns)
            # Speed must be 0.01 m/s (1 cm/s) when driving
            drive_speeds = rdf[rdf["speed_mps"] > 0]["speed_mps"]
            if not drive_speeds.empty:
                self.assertAlmostEqual(drive_speeds.iloc[0], 0.01, places=3)


if __name__ == "__main__":
    unittest.main()
