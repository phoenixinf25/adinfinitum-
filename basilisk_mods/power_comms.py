"""
Lander Power, Thermal, and Direct-to-Earth Communications Module.

Context: Spec §4.2 (Lander Power and Comms Subsystems), Spec §5 Phases 7-11 (Surface Operations).
Simulates solar power generation from horizon-blocked lunar illumination datasets,
tracks avionics, thermal heater, radio transmitter, and rover charging loads,
evaluates battery state-of-charge through the lunar day and night (night survival check),
models internal thermal response (simplified thermal model), and computes real-time
mission control countdowns (time to sunset/sunrise, time to Earthset/Earthrise).

Strict adherence to AGENTS.md:
- Trailing inline unit comments on all physical numeric literals.
- Full reStructuredText documentation in docstrings.
- SI units (metres, seconds, Watts, Watt-hours, degrees).
"""

from __future__ import annotations
import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union
import numpy as np

from worldmodel.ephem import (
    LunarEphemeris,
    SOLAR_CONSTANT_W_M2,
    R_MOON_M,
    calculate_sun_fraction
)


@dataclass
class LanderPowerConfig:
    """
    Configuration parameters for lander power, thermal, and comms subsystems.
    All physical literals carry trailing unit comments.
    """
    # Lander Identifier & Site
    lander_id: str = "VIKRAM_LANDER"
    site_name: str = "shackleton"
    site_lat_deg: float = -89.7995  # [deg] Planetocentric latitude
    site_lon_deg: float = 26.0496   # [deg] Planetocentric longitude

    # Solar Array Parameters
    panel_area_m2: float = 4.0           # [m^2] Total solar array surface area (config/mission.yaml)
    solar_constant_w_m2: float = 1361.0  # [W/m^2] Solar irradiance at 1 AU
    panel_factor: float = 0.28           # [-] Conversion factor (panel_efficiency: 0.28 in mission.yaml)

    # Battery Storage Parameters (12 kWh class sized for lunar night survival)
    battery_capacity_wh: float = 12000.0  # [W*h] Total nominal energy capacity
    battery_initial_wh: float = 12000.0   # [W*h] Starting energy level upon touchdown
    min_battery_wh: float = 0.0           # [W*h] Minimum cutoff threshold (0 Wh = depleted)
    charge_efficiency: float = 0.95       # [-] Battery coulombic/energy charging efficiency
    discharge_efficiency: float = 0.98    # [-] Battery discharging efficiency
    low_battery_threshold_pct: float = 15.0  # [%] Threshold below which sleep conservation engages

    # Electrical Power Loads
    load_avionics_day_w: float = 40.0     # [W] Daytime continuous avionics & payload sensors
    load_avionics_night_w: float = 15.0   # [W] Nighttime quiescent survival avionics (survival_load_w: 15.0W in mission.yaml)
    load_heater_day_w: float = 10.0       # [W] Daytime thermal control regulation
    load_heater_night_w: float = 18.0     # [W] Nighttime survival heaters (higher at night)
    load_radio_tx_w: float = 35.0         # [W] High-gain transmitter when Earth link is available
    load_radio_standby_w: float = 4.0     # [W] Low-power receiver standby
    load_rover_charging_w: float = 30.0   # [W] Power delivered to docked rover during daytime
    load_sleep_survival_w: float = 6.0    # [W] Emergency deep-sleep survival load

    # Simplified Thermal Model Parameters
    thermal_capacitance_j_k: float = 48000.0  # [J/K] Thermal inertia of internal electronics bay
    thermal_conductance_w_k: float = 0.42     # [W/K] Effective MLI conduction/radiation to environment
    target_temp_c: float = 15.0               # [degC] Thermostat nominal setpoint
    min_allowable_temp_c: float = -25.0       # [degC] Critical lower survival threshold
    initial_temp_c: float = 18.0              # [degC] Touchdown initial internal temperature


@dataclass
class LanderPowerState:
    """
    Snapshot of the lander power, thermal, battery, and comms status at a given epoch.
    """
    time_s: float = 0.0              # [s] Simulation elapsed time
    time_days: float = 0.0           # [day] Simulation elapsed days
    timestamp_utc: str = ""          # ISO timestamp
    sun_fraction: float = 0.0        # [-] Visible fraction of solar disc [0.0, 1.0]
    sun_elevation_deg: float = 0.0   # [deg] Sun elevation above local horizontal
    earth_visible: bool = False      # [-] Line-of-sight Direct-to-Earth contact available
    earth_elevation_deg: float = 0.0 # [deg] Earth elevation above local horizontal
    power_in_w: float = 0.0          # [W] Generated solar power
    load_avionics_w: float = 0.0     # [W] Avionics power demand
    load_heaters_w: float = 0.0      # [W] Survival heater power demand
    load_radio_w: float = 0.0        # [W] Communications radio power demand
    load_rover_w: float = 0.0        # [W] Rover charging power demand
    total_load_w: float = 0.0        # [W] Sum of all electrical loads
    net_power_w: float = 0.0         # [W] Net power balance (power_in - total_load)
    battery_wh: float = 0.0          # [W*h] Stored battery energy
    battery_pct: float = 0.0         # [%] State of charge
    internal_temp_c: float = 0.0     # [degC] Internal equipment temperature
    time_to_sunset_s: float = -1.0   # [s] Countdown to next sunset (-1 if in night)
    time_to_sunrise_s: float = -1.0  # [s] Countdown to next sunrise (-1 if in day)
    time_to_earthset_s: float = -1.0 # [s] Countdown to next Earth link loss (-1 if lost)
    time_to_earthrise_s: float = -1.0# [s] Countdown to next Earth link restoration
    is_surviving: bool = True        # [-] Night survival flag (battery > 0)
    status: str = "NOMINAL"          # Status description


class PowerCommsModule:
    """
    Basilisk simulation module for lander solar power generation, Direct-to-Earth
    communications windows, battery state-of-charge integration, and thermal management.
    """

    def __init__(
        self,
        config: LanderPowerConfig | None = None,
        light_dataset_path: str | Path | None = None,
        ephem_model: LunarEphemeris | None = None,
        horizon_mask_deg: np.ndarray | None = None
    ):
        """
        Initialize the power and comms module.

        Parameters:
            config: Lander configuration object.
            light_dataset_path: Path to data/light/<region>_<range>.npz file.
            ephem_model: Optional LunarEphemeris instance if computing on-the-fly.
            horizon_mask_deg: Optional 360-element horizon mask array [deg].
        """
        self.config = config or LanderPowerConfig()
        self.battery_wh: float = self.config.battery_initial_wh  # [W*h]
        self.internal_temp_c: float = self.config.initial_temp_c # [degC]
        self.current_time_s: float = 0.0  # [s]

        # Ephemeris / Light arrays
        self.times_s: np.ndarray = np.array([], dtype=np.float64)
        self.sun_fractions: np.ndarray = np.array([], dtype=np.float32)
        self.sun_elevations: np.ndarray = np.array([], dtype=np.float32)
        self.earth_visibles: np.ndarray = np.array([], dtype=bool)
        self.earth_elevations: np.ndarray = np.array([], dtype=np.float32)
        self.horizon_mask_deg = horizon_mask_deg

        # Precomputed fast O(1) countdown arrays
        self.countdowns_sunset: np.ndarray = np.array([], dtype=np.float32)
        self.countdowns_sunrise: np.ndarray = np.array([], dtype=np.float32)
        self.countdowns_earthset: np.ndarray = np.array([], dtype=np.float32)
        self.countdowns_earthrise: np.ndarray = np.array([], dtype=np.float32)

        self.ephem = ephem_model or LunarEphemeris()
        self.step_idx: int = 0
        self.has_precomputed_data: bool = False
        self.point_series = None

        if light_dataset_path is not None:
            self.load_light_dataset(light_dataset_path)

    def load_light_dataset(self, npz_path: str | Path, cell_idx: int = 0) -> None:
        """
        Load precomputed illumination and Earth visibility data from a NumPy archive,
        supporting contracts/light.py PointSeries / LightField as well as raw simulation archives,
        and precompute O(1) countdown lookahead tables in a single backward pass.

        Parameters:
            npz_path: Path to data/light/<region>_<range>.npz or <region>_<date>_points.npz.
            cell_idx: Candidate cell index (default: 0) when reading PointSeries.
        """
        p = Path(npz_path)
        if not p.exists():
            raise FileNotFoundError(f"Light dataset not found: {p}")

        data = np.load(p, allow_pickle=True)
        if "header" in data.files:
            # PointSeries or LightField format from contracts/light.py
            try:
                from contracts.light import load_points
                ps = load_points(p)
                self.times_s = ps.et_s - ps.et_s[0]
                self.sun_fractions = ps.sun_fraction[:, cell_idx]
                self.sun_elevations = ps.sun_elev_deg[:, cell_idx]
                self.earth_visibles = ps.earth_visible()[:, cell_idx]
                self.earth_elevations = ps.earth_elev_deg[:, cell_idx]
                self.horizon_mask_deg = ps.horizon_elev_deg[cell_idx]
                self.point_series = ps
            except Exception:
                from contracts.light import load_light
                lf = load_light(p)
                self.times_s = lf.et_s - lf.et_s[0]
                r, c = (lf.sun_fraction.shape[1] // 2, lf.sun_fraction.shape[2] // 2)
                self.sun_fractions = lf.sun_fraction[:, r, c]
                self.sun_elevations = lf.sun_elev_deg[:, r, c]
                self.earth_visibles = lf.earth_visible()[:, r, c]
                self.earth_elevations = lf.earth_elev_deg[:, r, c]
                self.point_series = None
        elif "time_s" in data.files:
            self.times_s = data["time_s"]
            self.sun_fractions = data["sun_fraction"]
            self.sun_elevations = data["sun_elevation_deg"]
            self.earth_visibles = data["earth_visible"]
            self.earth_elevations = data["earth_elevation_deg"]
            self.sun_azimuths = data["sun_azimuth_deg"] if "sun_azimuth_deg" in data.files else np.zeros(len(self.times_s), dtype=np.float32)
            self.earth_azimuths = data["earth_azimuth_deg"] if "earth_azimuth_deg" in data.files else np.zeros(len(self.times_s), dtype=np.float32)
            if "horizon_mask_deg" in data.files:
                self.horizon_mask_deg = data["horizon_mask_deg"]
            self.point_series = None
        else:
            raise ValueError(f"Unrecognized light archive keys: {data.files}")

        self.has_precomputed_data = True
        self.step_idx = 0

        # Vectorized precomputation of countdowns in O(N)
        self._precompute_countdowns()
        print(f"[PowerComms] Loaded light dataset from {p} ({len(self.times_s)} points)")

    def to_point_series(
        self,
        region: str | None = None,
        date_str: str = "2026-11-14",
        cadence_s: float = 3600.0,
        max_samples: int = 709
    ) -> Any:
        """
        Export module illumination and visibility profile into a standardized PointSeries (contracts/light.py).
        Extracts at 1-hour cadence for Navigator analysis.

        Parameters:
            region: Optional region name (defaults to self.config.site_name).
            date_str: ISO start date string YYYY-MM-DD (default: '2026-11-14').
            cadence_s: Sampling interval in seconds [s] (default: 3600 s = 1 hr).
            max_samples: Maximum number of synodic samples (default: 709).

        Returns:
            PointSeries instance compliant with light contract v2.
        """
        if self.point_series is not None:
            return self.point_series

        from datetime import datetime, timedelta, UTC
        from contracts.light import PointSeries
        from contracts.provenance import Meta, Provenance

        reg = region or self.config.site_name
        dt_sim = float(self.times_s[1] - self.times_s[0]) if len(self.times_s) > 1 else 60.0
        step_stride = max(1, int(round(cadence_s / dt_sim)))

        indices = np.arange(0, len(self.times_s), step_stride)
        if len(indices) > max_samples:
            indices = indices[:max_samples]
        elif len(indices) < max_samples:
            indices = np.pad(indices, (0, max_samples - len(indices)), mode="edge")

        t0 = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
        times_utc = [(t0 + timedelta(seconds=float(self.times_s[i]))).strftime("%Y-%m-%dT%H:%M:%SZ") for i in indices]
        et_s = np.array([(t0 + timedelta(seconds=float(self.times_s[i])) - j2000).total_seconds() for i in indices])

        sun_frac = self.sun_fractions[indices, None].astype(np.float32)
        sun_el = self.sun_elevations[indices, None].astype(np.float32)
        earth_el = self.earth_elevations[indices, None].astype(np.float32)

        if self.horizon_mask_deg is not None and len(self.horizon_mask_deg) == 360:
            horiz = self.horizon_mask_deg.reshape(1, 360).astype(np.float32)
        else:
            horiz = np.zeros((1, 360), dtype=np.float32)

        sun_az = self.sun_azimuths[indices].astype(np.float32) if hasattr(self, "sun_azimuths") and len(self.sun_azimuths) > 0 else np.zeros(len(indices), dtype=np.float32)
        earth_az = self.earth_azimuths[indices].astype(np.float32) if hasattr(self, "earth_azimuths") and len(self.earth_azimuths) > 0 else np.zeros(len(indices), dtype=np.float32)

        meta = Meta(provenance=Provenance.MODELLED, source=f"PowerCommsModule simulation {reg}")
        ps = PointSeries(
            region=reg,
            date=date_str,
            cells=np.array([[0, 0]]),
            times_utc=times_utc,
            et_s=et_s,
            sun_fraction=sun_frac,
            sun_elev_deg=sun_el,
            earth_elev_deg=earth_el,
            sun_az_deg=sun_az,
            earth_az_deg=earth_az,
            horizon_elev_deg=horiz,
            meta=meta
        )
        ps.validate()
        return ps

    def _precompute_countdowns(self) -> None:
        """Precompute countdown times to sunset, sunrise, Earthset, Earthrise in O(N)."""
        n = len(self.times_s)
        self.countdowns_sunset = np.full(n, -1.0, dtype=np.float32)
        self.countdowns_sunrise = np.full(n, -1.0, dtype=np.float32)
        self.countdowns_earthset = np.full(n, -1.0, dtype=np.float32)
        self.countdowns_earthrise = np.full(n, -1.0, dtype=np.float32)

        sun_lit = self.sun_fractions > 0.0
        earth_lit = self.earth_visibles

        next_sunset_t = -1.0
        next_sunrise_t = -1.0
        next_earthset_t = -1.0
        next_earthrise_t = -1.0

        for i in range(n - 2, -1, -1):
            t_now = float(self.times_s[i])
            t_next = float(self.times_s[i + 1])

            # Transition detections at boundary i -> i+1
            if sun_lit[i] and not sun_lit[i + 1]:
                next_sunset_t = t_next
            elif not sun_lit[i] and sun_lit[i + 1]:
                next_sunrise_t = t_next

            if earth_lit[i] and not earth_lit[i + 1]:
                next_earthset_t = t_next
            elif not earth_lit[i] and earth_lit[i + 1]:
                next_earthrise_t = t_next

            if sun_lit[i] and next_sunset_t >= 0.0:
                self.countdowns_sunset[i] = next_sunset_t - t_now
            elif not sun_lit[i] and next_sunrise_t >= 0.0:
                self.countdowns_sunrise[i] = next_sunrise_t - t_now

            if earth_lit[i] and next_earthset_t >= 0.0:
                self.countdowns_earthset[i] = next_earthset_t - t_now
            elif not earth_lit[i] and next_earthrise_t >= 0.0:
                self.countdowns_earthrise[i] = next_earthrise_t - t_now

    def calculate_power_in(self, sun_fraction: float) -> float:
        """
        Calculate instantaneous solar power entering the lander solar array.

        Formula:
            Power_in = panel_area * 1361.0 W/m^2 * sun_fraction * panel_factor

        Parameters:
            sun_fraction: Visible fraction of the solar disc [0.0, 1.0].

        Returns:
            power_in_w: Generated power in Watts [W].
        """
        if sun_fraction <= 0.0:
            return 0.0  # [W] In total shadow / lunar night
        # Physical solar array conversion
        p_in = (
            self.config.panel_area_m2 *
            self.config.solar_constant_w_m2 *
            float(sun_fraction) *
            self.config.panel_factor
        )
        return float(p_in)  # [W]

    def calculate_loads(
        self,
        is_day: bool,
        earth_link: bool,
        rover_charging: bool = False,
        in_sleep_mode: bool = False
    ) -> dict[str, float]:
        """
        Calculate instantaneous electrical consumption for each onboard subsystem.

        Parameters:
            is_day: True if sun is illuminating the lander (sun_fraction > 0).
            earth_link: True if direct line-of-sight to Earth is established.
            rover_charging: True if rover is actively drawing charge power.
            in_sleep_mode: True if low-battery emergency deep-sleep is active.

        Returns:
            Dict containing individual and total loads in Watts [W].
        """
        if in_sleep_mode:
            # Low-power emergency survival mode
            return {
                "avionics_w": 2.5,   # [W] Essential telemetry clock
                "heaters_w": 3.0,   # [W] Minimum survival heat
                "radio_w": 0.5,      # [W] Low rate beacon
                "rover_w": 0.0,      # [W]
                "total_w": self.config.load_sleep_survival_w  # [W]
            }

        # 1. Avionics load (daytime science/monitoring vs night quiescent)
        if is_day:
            p_avionics = self.config.load_avionics_day_w    # [W]
        else:
            p_avionics = self.config.load_avionics_night_w  # [W]

        # 2. Heaters load (higher at night to prevent freezing in -180 degC cold)
        if is_day:
            p_heaters = self.config.load_heater_day_w       # [W]
        else:
            p_heaters = self.config.load_heater_night_w     # [W]

        # 3. Radio load (active transmission when Earth link is up, standby during night/occlusion)
        if earth_link and is_day:
            p_radio = self.config.load_radio_tx_w           # [W]
        else:
            p_radio = self.config.load_radio_standby_w      # [W]

        # 4. Rover charging (only during day when sun is available)
        if rover_charging and is_day:
            p_rover = self.config.load_rover_charging_w     # [W]
        else:
            p_rover = 0.0  # [W]

        total = p_avionics + p_heaters + p_radio + p_rover  # [W]
        return {
            "avionics_w": p_avionics,
            "heaters_w": p_heaters,
            "radio_w": p_radio,
            "rover_w": p_rover,
            "total_w": total
        }

    def update_battery(self, net_power_w: float, dt_s: float) -> tuple[float, float]:
        """
        Integrate stored battery energy over time interval dt_s.

        Parameters:
            net_power_w: Net electrical power balance (power_in - total_load) [W].
            dt_s: Time step in seconds [s].

        Returns:
            (battery_wh, battery_pct): New energy in [W*h] and State-of-Charge [%].
        """
        dt_hours = dt_s / 3600.0  # [hr]

        if net_power_w >= 0.0:
            # Charging: energy gained with charge efficiency
            delta_e = net_power_w * dt_hours * self.config.charge_efficiency  # [W*h]
            self.battery_wh = min(self.config.battery_capacity_wh, self.battery_wh + delta_e)
        else:
            # Discharging: energy drained with discharge efficiency
            delta_e = (abs(net_power_w) * dt_hours) / self.config.discharge_efficiency  # [W*h]
            self.battery_wh = max(self.config.min_battery_wh, self.battery_wh - delta_e)

        battery_pct = (self.battery_wh / self.config.battery_capacity_wh) * 100.0  # [%]
        return self.battery_wh, battery_pct

    def update_thermal(self, is_day: bool, internal_dissipation_w: float, dt_s: float) -> float:
        """
        Simplified internal thermal model.
        Balances internal dissipation against external radiative/conductive losses to space.

        Parameters:
            is_day: True if daytime, False if nighttime.
            internal_dissipation_w: Total internal electrical dissipation [W].
            dt_s: Time step in seconds [s].

        Returns:
            internal_temp_c: Updated internal equipment bay temperature [degC].
        """
        # Ambient sink temperature: ~ -15 degC day (under sunlit MLI), ~ -160 degC night
        sink_temp_c = -15.0 if is_day else -160.0  # [degC]

        # Heat loss through MLI blankets: Q_loss = G * (T_int - T_sink)
        q_loss_w = self.config.thermal_conductance_w_k * (self.internal_temp_c - sink_temp_c)  # [W]
        q_net_w = internal_dissipation_w - q_loss_w  # [W]

        # dT = (Q_net * dt) / C_thermal
        delta_t_c = (q_net_w * dt_s) / self.config.thermal_capacitance_j_k  # [degC]
        self.internal_temp_c += delta_t_c

        # Cap between -50 degC and +45 degC for physical bounds
        self.internal_temp_c = float(np.clip(self.internal_temp_c, -50.0, 45.0))
        return self.internal_temp_c

    def step(self, dt_s: float = 60.0, rover_charging: bool = False) -> LanderPowerState:
        """
        Advance the simulation state by time step dt_s.

        Parameters:
            dt_s: Time step in seconds [s] (default: 60 s = 1 minute).
            rover_charging: True if rover is docked and drawing power.

        Returns:
            LanderPowerState object containing the latest telemetry.
        """
        if self.has_precomputed_data and self.step_idx < len(self.times_s):
            t_s = float(self.times_s[self.step_idx])
            sun_frac = float(self.sun_fractions[self.step_idx])
            sun_elev = float(self.sun_elevations[self.step_idx])
            earth_vis = bool(self.earth_visibles[self.step_idx])
            earth_elev = float(self.earth_elevations[self.step_idx])

            # Fast O(1) table lookup
            t_sunset = float(self.countdowns_sunset[self.step_idx])
            t_sunrise = float(self.countdowns_sunrise[self.step_idx])
            t_earthset = float(self.countdowns_earthset[self.step_idx])
            t_earthrise = float(self.countdowns_earthrise[self.step_idx])

            self.step_idx += 1
        else:
            # Query ephemeris directly
            t_s = self.current_time_s
            angles = self.ephem.get_topo_angles(
                self.config.site_lat_deg,
                self.config.site_lon_deg,
                t_s
            )
            sun_elev = angles["sun_elevation_deg"]
            earth_elev = angles["earth_elevation_deg"]
            horiz_deg = 0.5
            sun_frac = calculate_sun_fraction(sun_elev, horiz_deg)
            earth_vis = bool(earth_elev > 0.0)
            t_sunset, t_sunrise, t_earthset, t_earthrise = -1.0, -1.0, -1.0, -1.0
            self.current_time_s += dt_s

        self.current_time_s = t_s
        is_day = bool(sun_frac > 0.0)

        # 1. Solar power generation
        power_in = self.calculate_power_in(sun_frac)  # [W]

        # 2. Check if deep sleep mode should engage
        pct = (self.battery_wh / self.config.battery_capacity_wh) * 100.0
        in_sleep = bool(not is_day and pct <= self.config.low_battery_threshold_pct)

        # 3. Subsystem electrical loads
        loads = self.calculate_loads(
            is_day=is_day,
            earth_link=earth_vis,
            rover_charging=rover_charging,
            in_sleep_mode=in_sleep
        )
        total_load = loads["total_w"]  # [W]
        net_power = power_in - total_load  # [W]

        # 4. Integrate battery energy
        bat_wh, bat_pct = self.update_battery(net_power, dt_s)

        # 5. Internal thermal update
        temp_c = self.update_thermal(is_day, total_load, dt_s)

        # 6. Operational status determination
        is_surviving = bool(bat_wh > 0.0)
        if not is_surviving:
            status = "POWER_DEPLETED_CRITICAL"
        elif in_sleep:
            status = "NIGHT_DEEP_SLEEP_SURVIVAL"
        elif is_day and earth_vis:
            status = "DAY_NOMINAL_DTE_ACTIVE"
        elif is_day:
            status = "DAY_NOMINAL_EARTH_BLOCKED"
        elif earth_vis:
            status = "NIGHT_SURVIVAL_DTE_ACTIVE"
        else:
            status = "NIGHT_SURVIVAL_STANDBY"

        state = LanderPowerState(
            time_s=t_s,
            time_days=t_s / 86400.0,
            timestamp_utc=f"T+ {t_s/86400.0:.2f}d",
            sun_fraction=sun_frac,
            sun_elevation_deg=sun_elev,
            earth_visible=earth_vis,
            earth_elevation_deg=earth_elev,
            power_in_w=power_in,
            load_avionics_w=loads["avionics_w"],
            load_heaters_w=loads["heaters_w"],
            load_radio_w=loads["radio_w"],
            load_rover_w=loads["rover_w"],
            total_load_w=total_load,
            net_power_w=net_power,
            battery_wh=bat_wh,
            battery_pct=bat_pct,
            internal_temp_c=temp_c,
            time_to_sunset_s=t_sunset,
            time_to_sunrise_s=t_sunrise,
            time_to_earthset_s=t_earthset,
            time_to_earthrise_s=t_earthrise,
            is_surviving=is_surviving,
            status=status
        )
        return state

    def run_simulation(
        self,
        duration_days: float = 30.0,
        dt_s: float = 60.0,
        rover_charging_hours_per_day: float = 4.0
    ) -> list[LanderPowerState]:
        """
        Execute a multi-day (e.g. 30-day) simulation run, collecting full telemetry history.

        Parameters:
            duration_days: Length of simulation in Earth days (default: 30 days).
            dt_s: Time step in seconds [s].
            rover_charging_hours_per_day: Daily hours devoted to charging the rover.

        Returns:
            history: List of LanderPowerState snapshots.
        """
        total_steps = int((duration_days * 86400.0) / dt_s)
        history: list[LanderPowerState] = []

        # Reset state to initial conditions
        self.battery_wh = self.config.battery_initial_wh
        self.internal_temp_c = self.config.initial_temp_c
        self.step_idx = 0
        self.current_time_s = 0.0

        for i in range(total_steps):
            t_s = i * dt_s
            day_hour = (t_s % 86400.0) / 3600.0
            # Rover charges during mid-day window (hours 10:00 to 14:00)
            charge_rover = bool(10.0 <= day_hour <= 10.0 + rover_charging_hours_per_day)

            state = self.step(dt_s=dt_s, rover_charging=charge_rover)
            history.append(state)

        return history

    def export_telemetry_csv(
        self,
        history: list[LanderPowerState],
        output_csv_path: str | Path = "runs/basilisk/lander_power_telemetry.csv",
        log_interval_s: float = 300.0  # Log every 5 minutes by default
    ) -> Path:
        """
        Export simulation telemetry history to a standardized CSV file.
        Writes both the team contract format (contracts/runs.py TELEMETRY_COLUMNS)
        and an extended engineering breakdown CSV (<name>_detailed.csv).

        Parameters:
            history: List of LanderPowerState records.
            output_csv_path: Target CSV file path.
            log_interval_s: Decimation logging period in seconds (default: 300 s = 5 min).

        Returns:
            out_path: Absolute Path to the generated CSV file.
        """
        out_path = Path(output_csv_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Standard Contract Telemetry (contracts/runs.py TELEMETRY_COLUMNS)
        standard_rows = []
        last_logged_t = -log_interval_s
        for s in history:
            if s.time_s - last_logged_t >= log_interval_s - 1e-4:
                countdowns = []
                if s.time_to_sunset_s >= 0:
                    countdowns.append(f"sunset in {s.time_to_sunset_s/3600.0:.1f}h")
                elif s.time_to_sunrise_s >= 0:
                    countdowns.append(f"sunrise in {s.time_to_sunrise_s/3600.0:.1f}h")
                if s.time_to_earthset_s >= 0:
                    countdowns.append(f"earthset in {s.time_to_earthset_s/3600.0:.1f}h")
                elif s.time_to_earthrise_s >= 0:
                    countdowns.append(f"earthrise in {s.time_to_earthrise_s/3600.0:.1f}h")
                cd_text = ", ".join(countdowns) if countdowns else "no transition in window"
                decision_str = f"SOC {s.battery_pct:.1f}% | {cd_text} | status: {s.status}"

                standard_rows.append({
                    "t_s": s.time_s,
                    "phase": "surface",
                    "x_m": 0.0,
                    "y_m": 0.0,
                    "alt_m": 0.0,
                    "vx_m_s": 0.0,
                    "vy_m_s": 0.0,
                    "vz_m_s": 0.0,
                    "mass_kg": 760.0,
                    "fuel_kg": 0.0,
                    "thrust_n": 0.0,
                    "engines_ok": 1,
                    "battery_wh": round(s.battery_wh, 2),
                    "solar_w": round(s.power_in_w, 2),
                    "earth_visible": 1 if s.earth_visible else 0,
                    "decision": decision_str,
                })
                last_logged_t = s.time_s

        try:
            from contracts.runs import write_telemetry
            write_telemetry(standard_rows, out_path)
            print(f"[PowerComms CSV] Exported {len(standard_rows)} records to {out_path.resolve()} (contract format)")
        except Exception as e:
            print(f"[PowerComms CSV] Fallback standard writer: {e}")

        # 2. Detailed Engineering Breakdown CSV
        detailed_path = out_path.parent / f"{out_path.stem}_detailed.csv"
        detailed_fieldnames = [
            "time_s", "time_days", "sun_fraction", "sun_elevation_deg",
            "earth_visible", "earth_elevation_deg", "power_in_w",
            "load_total_w", "load_avionics_w", "load_heaters_w", "load_radio_w", "load_rover_w",
            "net_power_w", "battery_wh", "battery_pct", "temperature_c",
            "time_to_sunset_s", "time_to_sunrise_s", "time_to_earthset_s", "time_to_earthrise_s",
            "status"
        ]

        last_logged_t = -log_interval_s
        rows = 0
        with open(detailed_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=detailed_fieldnames)
            writer.writeheader()
            for s in history:
                if s.time_s - last_logged_t >= log_interval_s - 1e-4:
                    writer.writerow({
                        "time_s": f"{s.time_s:.1f}",
                        "time_days": f"{s.time_days:.4f}",
                        "sun_fraction": f"{s.sun_fraction:.4f}",
                        "sun_elevation_deg": f"{s.sun_elevation_deg:.2f}",
                        "earth_visible": 1 if s.earth_visible else 0,
                        "earth_elevation_deg": f"{s.earth_elevation_deg:.2f}",
                        "power_in_w": f"{s.power_in_w:.2f}",
                        "load_total_w": f"{s.total_load_w:.2f}",
                        "load_avionics_w": f"{s.load_avionics_w:.2f}",
                        "load_heaters_w": f"{s.load_heaters_w:.2f}",
                        "load_radio_w": f"{s.load_radio_w:.2f}",
                        "load_rover_w": f"{s.load_rover_w:.2f}",
                        "net_power_w": f"{s.net_power_w:.2f}",
                        "battery_wh": f"{s.battery_wh:.2f}",
                        "battery_pct": f"{s.battery_pct:.2f}",
                        "temperature_c": f"{s.internal_temp_c:.2f}",
                        "time_to_sunset_s": f"{s.time_to_sunset_s:.0f}",
                        "time_to_sunrise_s": f"{s.time_to_sunrise_s:.0f}",
                        "time_to_earthset_s": f"{s.time_to_earthset_s:.0f}",
                        "time_to_earthrise_s": f"{s.time_to_earthrise_s:.0f}",
                        "status": s.status
                    })
                    last_logged_t = s.time_s
                    rows += 1

        print(f"[PowerComms CSV] Exported {rows} detailed records to {detailed_path.resolve()}")
        return out_path
