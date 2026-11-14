"""Typed, validated view of config/mission.yaml.

    from contracts.mission import load_mission
    cfg = load_mission()
    cfg.lander.engines.max_thrust_n

Run `python -m contracts.mission` to validate the file and print derived numbers.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.paths import mission_config_path

Range = Annotated[list[float], Field(min_length=2, max_length=2)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Moon(_Strict):
    gravity_m_s2: float = Field(gt=0)
    radius_m: float = Field(gt=0)
    g0_m_s2: float = Field(gt=0)


class Engines(_Strict):
    count: int = Field(ge=1)
    max_thrust_n: float = Field(gt=0)
    min_throttle: float = Field(ge=0, le=1)


class AttitudeThrusters(_Strict):
    count: int = Field(ge=0)
    thrust_n: float = Field(ge=0)


class TouchdownLimits(_Strict):
    max_vertical_speed_m_s: float = Field(gt=0)
    max_horizontal_speed_m_s: float = Field(gt=0)
    max_slope_deg: float = Field(gt=0, lt=90)


class Lander(_Strict):
    wet_mass_at_release_kg: float = Field(gt=0)
    dry_mass_kg: float = Field(gt=0)
    isp_s: float = Field(gt=0)
    engines: Engines
    max_tilt_deg: float = Field(ge=0, le=90)
    attitude_thrusters: AttitudeThrusters
    touchdown_limits: TouchdownLimits
    descent_delta_v_budget_m_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _dry_lt_wet(self) -> Lander:
        if self.dry_mass_kg >= self.wet_mass_at_release_kg:
            raise ValueError("dry_mass_kg must be < wet_mass_at_release_kg")
        return self

    @property
    def max_total_thrust_n(self) -> float:
        return self.engines.count * self.engines.max_thrust_n


class Rover(_Strict):
    mass_kg: float = Field(gt=0)
    speed_m_s: float = Field(gt=0)
    max_slope_deg: float = Field(gt=0, lt=90)
    solar_panel_w: float = Field(ge=0)
    battery_wh: float = Field(ge=0)
    comms: str


class Power(_Strict):
    panel_area_m2: float = Field(gt=0)
    panel_efficiency: float = Field(gt=0, le=1)
    solar_constant_w_m2: float = Field(gt=0)
    battery_wh_min: float = Field(gt=0)
    battery_wh_max: float = Field(gt=0)
    heater_w_min: float = Field(ge=0)
    heater_w_max: float = Field(ge=0)
    survival_load_w: float = Field(ge=0)


class TerminalScenario(_Strict):
    dt_s: float = Field(gt=0)
    max_time_s: float = Field(gt=0)
    start_altitude_m: Range
    start_horizontal_offset_m: Range
    start_vertical_speed_m_s: Range
    start_horizontal_speed_m_s: Range
    start_mass_kg: float = Field(gt=0)
    start_propellant_kg: float = Field(ge=0)
    hover_gate_altitude_m: float = Field(gt=0)
    final_descent_speed_m_s: float = Field(gt=0)


class Scenarios(_Strict):
    terminal: TerminalScenario


class Failures(_Strict):
    engine_out_prob: float = Field(ge=0, le=1)
    nav_drift_prob: float = Field(ge=0, le=1)
    nav_drift_m_s: float = Field(ge=0)
    camera_blind_prob: float = Field(ge=0, le=1)
    surprise_hazard_prob: float = Field(ge=0, le=1)


class SensorNoise(_Strict):
    altimeter_m: float = Field(ge=0)
    velocimeter_m_s: float = Field(ge=0)
    position_m: float = Field(ge=0)


class Scoring(_Strict):
    landing_gate: bool
    w_landed: float
    w_target_distance_per_m: float
    w_fuel_per_kg: float
    w_ice_reached: float
    w_rover_returned: float
    w_survived_night: float
    w_data_per_mb: float


class Swarm(_Strict):
    population: int = Field(ge=1)
    generations_overnight: int = Field(ge=1)
    seed: int


class HazardDetector(_Strict):
    decision_threshold: float = Field(gt=0, lt=1)
    gap_fill_sigma_px: Annotated[list[float], Field(min_length=1)]


class MissionWindow(_Strict):
    start_utc: str
    end_utc: str

    @model_validator(mode="after")
    def _ordered(self) -> MissionWindow:
        from datetime import datetime
        s = datetime.fromisoformat(self.start_utc)
        e = datetime.fromisoformat(self.end_utc)
        if e <= s:
            raise ValueError("mission_window end must be after start")
        return self


class MissionConfig(_Strict):
    schema_version: int
    mission_window: MissionWindow
    moon: Moon
    lander: Lander
    rover: Rover
    power: Power
    scenarios: Scenarios
    failures: Failures
    sensor_noise: SensorNoise
    scoring: Scoring
    swarm: Swarm
    hazard_detector: HazardDetector

    @model_validator(mode="after")
    def _consistent(self) -> MissionConfig:
        t = self.scenarios.terminal
        dry_at_start = t.start_mass_kg - t.start_propellant_kg
        if abs(dry_at_start - self.lander.dry_mass_kg) > 1.0:
            raise ValueError(
                f"terminal start_mass - start_propellant = {dry_at_start} kg "
                f"but lander.dry_mass_kg = {self.lander.dry_mass_kg} kg"
            )
        # Lander must be able to hover with one engine out at terminal start mass.
        one_out = (self.lander.engines.count - 1) * self.lander.engines.max_thrust_n
        if one_out <= t.start_mass_kg * self.moon.gravity_m_s2:
            raise ValueError("lander cannot hover with one engine out at terminal start mass")
        return self

    # ---- derived numbers (handy for UI + sanity checks) ----
    def thrust_to_weight_at_release(self, engines_out: int = 0) -> float:
        thrust = (self.lander.engines.count - engines_out) * self.lander.engines.max_thrust_n
        return thrust / (self.lander.wet_mass_at_release_kg * self.moon.gravity_m_s2)

    def propellant_at_release_kg(self) -> float:
        return self.lander.wet_mass_at_release_kg - self.lander.dry_mass_kg

    def delta_v_available_m_s(self, wet_kg: float | None = None) -> float:
        wet = wet_kg if wet_kg is not None else self.lander.wet_mass_at_release_kg
        return self.lander.isp_s * self.moon.g0_m_s2 * math.log(wet / self.lander.dry_mass_kg)


def load_mission(path: str | Path | None = None) -> MissionConfig:
    p = Path(path) if path else mission_config_path()
    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return MissionConfig.model_validate(raw)


if __name__ == "__main__":
    cfg = load_mission()
    print("mission.yaml OK")
    print(f"  T/W at release           : {cfg.thrust_to_weight_at_release():.2f}")
    print(f"  T/W at release, 1 out    : {cfg.thrust_to_weight_at_release(1):.2f}")
    print(f"  propellant at release    : {cfg.propellant_at_release_kg():.0f} kg")
    print(f"  delta-v available        : {cfg.delta_v_available_m_s():.0f} m/s "
          f"(budget {cfg.lander.descent_delta_v_budget_m_s:.0f})")
    t = cfg.scenarios.terminal
    print(f"  terminal-phase delta-v   : {cfg.delta_v_available_m_s(t.start_mass_kg):.0f} m/s")
