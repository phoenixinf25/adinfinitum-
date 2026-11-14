"""
Unit tests for Lander Power, Comms, and Lunar Ephemeris modules.
Tests:
  - Ephemeris calculations (sun synodic period, solar constant, topocentric angles)
  - Solar power in formula (panel_area * 1361 * sun_fraction * panel_factor)
  - Subsystem loads (avionics, day/night heaters, DTE radio, rover charging)
  - Battery charge/discharge dynamics and night survival (battery > 0)
  - Mission control countdown lookaheads (time to sunset/sunrise/earthset/earthrise)
  - Docstring units adherence (AGENTS.md rule 1 and 2)
  - Full 30-day scenario execution and telemetry logging
"""

import inspect
import tempfile
import unittest
from pathlib import Path
import numpy as np

from basilisk_mods.power_comms import (
    LanderPowerConfig,
    LanderPowerState,
    PowerCommsModule
)
from worldmodel.ephem import (
    LunarEphemeris,
    SOLAR_CONSTANT_W_M2,
    R_MOON_M,
    LUNAR_SYNODIC_PERIOD_S,
    calculate_sun_fraction,
    generate_light_dataset
)


class TestDocstringUnitsPowerComms(unittest.TestCase):
    """Verify physical units are explicitly declared in docstrings and comments."""

    def test_units_in_docstrings(self):
        """All public methods must declare units in their docstrings."""
        methods = [
            PowerCommsModule.calculate_power_in,
            PowerCommsModule.calculate_loads,
            PowerCommsModule.update_battery,
            PowerCommsModule.update_thermal,
            PowerCommsModule.step,
            PowerCommsModule.run_simulation,
            PowerCommsModule.export_telemetry_csv,
            LunarEphemeris.get_sun_subsolar_latlon,
            LunarEphemeris.get_earth_subearth_latlon,
            LunarEphemeris.get_topo_angles,
            calculate_sun_fraction,
        ]
        unit_keywords = ["W", "W*h", "Wh", "deg", "s", "m", "K", "degC", "m^2"]
        for m in methods:
            doc = inspect.getdoc(m)
            self.assertIsNotNone(doc, f"Method {m.__name__} is missing a docstring")
            has_unit = any(u in doc for u in unit_keywords)
            self.assertTrue(has_unit, f"Docstring for {m.__name__} does not document physical units")


class TestLunarEphemeris(unittest.TestCase):
    """Verify astronomical calculations and topocentric projections."""

    def setUp(self):
        self.ephem = LunarEphemeris(ref_epoch_str="2026-11-14T00:00:00Z")

    def test_solar_constant_and_synodic_period(self):
        """Solar irradiance at 1 AU must be 1361 W/m^2; synodic period ~29.53 days."""
        self.assertAlmostEqual(SOLAR_CONSTANT_W_M2, 1361.0, places=1)
        period_days = LUNAR_SYNODIC_PERIOD_S / 86400.0
        self.assertAlmostEqual(period_days, 29.530588, delta=0.01)

    def test_sun_subsolar_cycle(self):
        """Sub-solar longitude must complete 360 deg in one synodic month."""
        lat0, lon0 = self.ephem.get_sun_subsolar_latlon(0.0)
        lat1, lon1 = self.ephem.get_sun_subsolar_latlon(LUNAR_SYNODIC_PERIOD_S)
        self.assertAlmostEqual(lat0, lat1, delta=0.1)
        self.assertAlmostEqual(lon0, lon1, delta=0.5)

    def test_earth_libration_bounds(self):
        """Sub-Earth latitude must remain within optical libration bounds (~+-7 deg)."""
        for t_days in [0.0, 7.0, 14.0, 21.0, 28.0]:
            lat_e, lon_e, dist_m = self.ephem.get_earth_subearth_latlon(t_days * 86400.0)
            self.assertLessEqual(abs(lat_e), 7.5)
            self.assertLessEqual(abs(lon_e), 8.5)
            self.assertGreater(dist_m, 3.5e8)
            self.assertLess(dist_m, 4.1e8)

    def test_topocentric_angles_shackleton(self):
        """At South Pole, Sun elevation stays low (-2 to +2 deg) throughout month."""
        for t_days in np.linspace(0.0, 29.5, 10):
            angles = self.ephem.get_topo_angles(-89.9, 0.0, t_days * 86400.0)
            se = angles["sun_elevation_deg"]
            self.assertGreaterEqual(se, -3.0)
            self.assertLessEqual(se, 3.0)

    def test_sun_fraction_occultation(self):
        """Sun fraction must transition from 0.0 to 1.0 across the horizon angle."""
        horiz = 1.0  # [deg]
        # Fully below
        self.assertEqual(calculate_sun_fraction(0.5, horiz), 0.0)
        # Fully above
        self.assertEqual(calculate_sun_fraction(1.5, horiz), 1.0)
        # Partial
        frac = calculate_sun_fraction(1.0, horiz)
        self.assertAlmostEqual(frac, 0.5, delta=0.1)


class TestLanderPowerSubsystems(unittest.TestCase):
    """Verify power conversion, loads, and battery dynamics."""

    def setUp(self):
        self.cfg = LanderPowerConfig(
            panel_area_m2=4.0,
            solar_constant_w_m2=1361.0,
            panel_factor=0.25,
            battery_capacity_wh=5000.0,
            battery_initial_wh=5000.0,
            load_avionics_day_w=40.0,
            load_avionics_night_w=15.0,
            load_heater_day_w=10.0,
            load_heater_night_w=20.0,
            load_radio_tx_w=35.0,
            load_radio_standby_w=5.0,
            load_rover_charging_w=30.0
        )
        self.module = PowerCommsModule(config=self.cfg)

    def test_solar_power_in_formula(self):
        """Power in = panel_area * 1361 * sun_fraction * panel_factor."""
        # Full sun
        p_in = self.module.calculate_power_in(1.0)
        expected = 4.0 * 1361.0 * 1.0 * 0.25
        self.assertAlmostEqual(p_in, expected, places=2)

        # Partial sun (50%)
        p_in_half = self.module.calculate_power_in(0.5)
        self.assertAlmostEqual(p_in_half, expected * 0.5, places=2)

        # Shadow
        self.assertEqual(self.module.calculate_power_in(0.0), 0.0)

    def test_subsystem_loads_day_vs_night(self):
        """Daytime loads include science/avionics; night loads use higher survival heat."""
        # Daytime with Earth link & rover charging
        loads_day = self.module.calculate_loads(is_day=True, earth_link=True, rover_charging=True)
        self.assertEqual(loads_day["avionics_w"], 40.0)
        self.assertEqual(loads_day["heaters_w"], 10.0)
        self.assertEqual(loads_day["radio_w"], 35.0)
        self.assertEqual(loads_day["rover_w"], 30.0)
        self.assertEqual(loads_day["total_w"], 115.0)

        # Nighttime with Earth link standby and no rover charging
        loads_night = self.module.calculate_loads(is_day=False, earth_link=False, rover_charging=False)
        self.assertEqual(loads_night["avionics_w"], 15.0)
        self.assertGreater(loads_night["heaters_w"], loads_day["heaters_w"])  # Higher at night
        self.assertEqual(loads_night["heaters_w"], 20.0)
        self.assertEqual(loads_night["radio_w"], 5.0)
        self.assertEqual(loads_night["rover_w"], 0.0)
        self.assertEqual(loads_night["total_w"], 40.0)

    def test_battery_charge_and_discharge_clamping(self):
        """Battery must charge with efficiency, discharge without exceeding capacity or 0."""
        self.module.battery_wh = 1000.0
        # Charge with 500W net power for 1 hour (3600s) at 0.95 efficiency
        self.module.update_battery(net_power_w=500.0, dt_s=3600.0)
        self.assertAlmostEqual(self.module.battery_wh, 1000.0 + 500.0 * 0.95, places=1)

        # Discharge with -200W net power for 2 hours at 0.98 efficiency
        bat_before = self.module.battery_wh
        self.module.update_battery(net_power_w=-200.0, dt_s=7200.0)
        expected_drain = (200.0 * 2.0) / 0.98
        self.assertAlmostEqual(self.module.battery_wh, bat_before - expected_drain, delta=0.5)

        # Overcharge test (clamps to capacity)
        self.module.update_battery(net_power_w=100000.0, dt_s=36000.0)
        self.assertEqual(self.module.battery_wh, self.cfg.battery_capacity_wh)

        # Complete drain test (clamps to min_battery_wh = 0.0)
        self.module.update_battery(net_power_w=-100000.0, dt_s=36000.0)
        self.assertEqual(self.module.battery_wh, 0.0)

    def test_thermal_model_dissipation(self):
        """Internal temperature must rise when dissipation exceeds losses and drop in night."""
        self.module.internal_temp_c = 15.0
        # Warm daytime internal dissipation
        t_day = self.module.update_thermal(is_day=True, internal_dissipation_w=200.0, dt_s=3600.0)
        self.assertGreater(t_day, 15.0)

        # Freezing nighttime drop
        t_night = self.module.update_thermal(is_day=False, internal_dissipation_w=5.0, dt_s=36000.0)
        self.assertLess(t_night, t_day)


class TestFull30DayMissionExecution(unittest.TestCase):
    """Verify 30-day simulation run, night survival, and CSV output."""

    def test_30day_simulation_night_survival(self):
        """Run 30-day simulation on Shackleton light data; verify night survival."""
        cfg = LanderPowerConfig(
            site_name="shackleton",
            battery_capacity_wh=12000.0,
            battery_initial_wh=12000.0
        )
        mod = PowerCommsModule(config=cfg, light_dataset_path="data/light/shackleton_30d.npz")
        history = mod.run_simulation(duration_days=30.0, dt_s=60.0)

        # 1. Step count check (43200 steps for 30 days @ 60s)
        self.assertEqual(len(history), 43200)

        # 2. Night survival: battery never drops to 0 Wh
        min_bat = min(s.battery_wh for s in history)
        self.assertGreater(min_bat, 0.0, "Lander battery died during night!")
        self.assertTrue(all(s.is_surviving for s in history))

        # 3. Solar power generated during day
        max_p_in = max(s.power_in_w for s in history)
        expected_max = cfg.panel_area_m2 * cfg.solar_constant_w_m2 * cfg.panel_factor
        self.assertAlmostEqual(max_p_in, expected_max, delta=1.0)

        # 4. Countdowns are non-negative and present
        s0 = history[0]
        self.assertGreater(s0.time_to_sunset_s, 0.0)
        self.assertGreater(s0.time_to_earthrise_s, 0.0)

        # 5. CSV export verification and contract conformance
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "test_telemetry.csv"
            mod.export_telemetry_csv(history, csv_path, log_interval_s=300.0)
            self.assertTrue(csv_path.exists())
            self.assertGreater(csv_path.stat().st_size, 1000)

            # Contract conformance check (contracts/runs.py TELEMETRY_COLUMNS)
            from contracts.runs import read_telemetry, TELEMETRY_COLUMNS
            rows = read_telemetry(csv_path)
            self.assertEqual(len(rows), 8640)
            self.assertEqual(tuple(rows[0].keys()), TELEMETRY_COLUMNS)
            self.assertIn("SOC", rows[0]["decision"])

    def test_spot_check_matches_navigator_metrics(self):
        """Spot-check Basilisk simulation numbers with Nimansh's Navigator (navigator/metrics.py)."""
        cfg = LanderPowerConfig(site_name="shackleton", battery_capacity_wh=12000.0)
        mod = PowerCommsModule(config=cfg, light_dataset_path="data/light/shackleton_30d.npz")
        history = mod.run_simulation(duration_days=30.0, dt_s=60.0)

        # Obtain PointSeries from module
        ps = mod.to_point_series(region="shackleton")
        from navigator.metrics import summarize, sun_countdown, earth_countdown
        s_nav = summarize(ps, k=0)

        # Basilisk metrics restricted to the synodic window
        synodic_max_s = (len(ps.times_utc) - 1) * 3600.0
        hist_syn = [s for s in history if s.time_s <= synodic_max_s]
        dt_hr = 60.0 / 3600.0

        b_sun_hours = sum(s.sun_fraction > 0.0 for s in hist_syn) * dt_hr
        b_earth_hours = sum(s.earth_visible for s in hist_syn) * dt_hr

        # Assert agreement within 1.5 hours across the ~708h month
        self.assertAlmostEqual(b_sun_hours, s_nav.sun_hours, delta=1.5)
        self.assertAlmostEqual(b_earth_hours, s_nav.earth_hours, delta=1.5)

        # Countdowns agreement at step 0
        cd_sun = sun_countdown(ps, 0)
        cd_earth = earth_countdown(ps, 0)
        self.assertAlmostEqual(history[0].time_to_sunset_s / 3600.0, cd_sun.hours, delta=1.0)
        self.assertAlmostEqual(history[0].time_to_earthrise_s / 3600.0, cd_earth.hours, delta=1.0)

    def test_load_light_from_point_series_v2(self):
        """PowerCommsModule must natively load a PointSeries archive from contracts/light.py."""
        from contracts.light import load_points
        ps_path = "data/light/shackleton_2026-11-14_points.npz"
        if not Path(ps_path).exists():
            mod0 = PowerCommsModule(light_dataset_path="data/light/shackleton_30d.npz")
            ps = mod0.to_point_series(region="shackleton")
            from contracts.light import save_points
            save_points(ps, ps_path)

        mod = PowerCommsModule(light_dataset_path=ps_path)
        self.assertTrue(mod.has_precomputed_data)
        self.assertEqual(len(mod.times_s), 709)
        self.assertGreater(mod.sun_fractions.mean(), 0.0)
        state0 = mod.step(dt_s=3600.0)
        self.assertGreater(state0.power_in_w, 0.0)


if __name__ == "__main__":
    unittest.main()
