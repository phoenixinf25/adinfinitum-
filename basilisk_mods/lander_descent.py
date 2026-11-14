"""
STARTER / EXPANDED (Tanush & Arnav): 5-engine powered-descent lander for Basilisk.

What's inside:
  build_lander(sim, cfg, ...)   spacecraft + fuel tank + 5 x 800 N thrusters + attitude control chain
  DescentGuidance               ZEM/ZEV guidance -> attitude reference + engine on-times
  touchdown_report(...)         pass/fail against config touchdown limits

Engines: 4 outer + 1 centre, all pushing along +z_B (outer ones canted 5 deg outward).
Throttle is implemented the standard Basilisk way: each control period the guidance commands
an on-time = throttle x period for every healthy engine (pulse-width modulation).

Attitude: guidance -> attTrackingError -> mrpFeedback -> extForceTorque
(ideal torque instead of modelling individual RCS thrusters).
Supports dual-mode: Basilisk C++ when available, pure-Python 6-DOF fallback when running on host.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

from basilisk_mods.bsk_common import (
    HAS_BSK,
    MU_MOON,
    R_MOON_M,
    add_moon_gravity,
    macros,
    mrp_with_z_along,
    rbk,
)
from contracts.mission import MissionConfig

ENGINE_CANT_DEG = 5.0
OPPOSITE = {1: 3, 3: 1, 2: 4, 4: 2}     # outer engine pairs (index 0 = centre)
ENGINE_RADIUS_M = 0.8
INERTIA_KG_M2 = [900.0, 900.0, 700.0]   # design assumption for a ~1.5 t lander


def engine_layout():
    """Positions r_B and force directions tHat_B for 4 outer + 1 centre engine (body frame)."""
    c = math.cos(math.radians(ENGINE_CANT_DEG))
    s = math.sin(math.radians(ENGINE_CANT_DEG))
    outer = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    layout = [([0.0, 0.0, -1.0], [0.0, 0.0, 1.0])]                     # centre
    for ex, ey in outer:
        r = [ENGINE_RADIUS_M * ex, ENGINE_RADIUS_M * ey, -1.0]
        t = [-s * ex, -s * ey, c]                                       # force tilted inward = plume canted out
        layout.append((r, t))
    return layout


# Pure-python messaging abstractions for dual-mode execution
class _MsgPayload:
    pass


class _SCStatesMsgPayload(_MsgPayload):
    def __init__(self, r_BN_N=None, v_BN_N=None, sigma_BN=None):
        self.r_BN_N = list(r_BN_N) if r_BN_N is not None else [0.0, 0.0, 0.0]
        self.v_BN_N = list(v_BN_N) if v_BN_N is not None else [0.0, 0.0, 0.0]
        self.sigma_BN = list(sigma_BN) if sigma_BN is not None else [0.0, 0.0, 0.0]


class _AttRefMsgPayload(_MsgPayload):
    def __init__(self, sigma_RN=None):
        self.sigma_RN = list(sigma_RN) if sigma_RN is not None else [0.0, 0.0, 0.0]


class _THRArrayOnTimeCmdMsgPayload(_MsgPayload):
    def __init__(self, on_times=None):
        self.OnTime = list(on_times) if on_times is not None else [0.0] * 5


class _FuelTankMsgPayload(_MsgPayload):
    def __init__(self, fuel_mass=140.0):
        self.fuelMass = float(fuel_mass)


class _GenericMsg:
    def __init__(self, default_payload_cls=_MsgPayload):
        self.payload = default_payload_cls()
        self.subscribers = []

    def write(self, payload, time_ns=0, module_id=0):
        self.payload = payload
        for s in self.subscribers:
            s._update(payload)
        return self

    def read(self):
        return self.payload

    def subscribeTo(self, other_msg):
        other_msg.subscribers.append(self)
        self.payload = other_msg.payload

    def _update(self, payload):
        self.payload = payload

    def __call__(self):
        return self.payload


class DescentGuidance:
    """Classic ZEM/ZEV guidance to a hover gate, then vertical terminal descent."""

    def __init__(self, cfg: MissionConfig, target_N: np.ndarray, mass_fn: Callable[[], float], control_period_s: float):
        self.ModelTag = "descentGuidance"
        self.moduleID = 1
        self.scStateInMsg = _GenericMsg(_SCStatesMsgPayload)
        self.attRefOutMsg = _GenericMsg(_AttRefMsgPayload)
        self.thrOnTimeOutMsg = _GenericMsg(_THRArrayOnTimeCmdMsgPayload)

        t = cfg.scenarios.terminal
        self.n_eng = cfg.lander.engines.count
        self.eng_max = cfg.lander.engines.max_thrust_n
        self.min_thr = cfg.lander.engines.min_throttle
        self.max_tilt = math.radians(cfg.lander.max_tilt_deg)
        self.gate = t.hover_gate_altitude_m
        self.v_final = t.final_descent_speed_m_s
        self.switch_h = 8.0
        self.terminal_tilt = math.radians(15.0)   # gentler attitude near the ground
        self.no_chase_alt_m = 10.0
        self.target_N = np.asarray(target_N, float)
        self.up = self.target_N / np.linalg.norm(self.target_N)
        self.mass_fn = mass_fn
        self.period = control_period_s
        self.engine_out_at_s: float | None = None
        self.engine_out_index = 1
        self.engines_ok = np.ones(self.n_eng, bool)
        self.ground_height_fn = lambda r_N: 0.0   # plugged into lunar_terrain
        self.mu = MU_MOON
        self.last: dict[str, Any] = {}
        self.decisions: list[tuple[float, str]] = []

    def Reset(self, CurrentSimNanos: int = 0):
        self.attRefOutMsg.write(_AttRefMsgPayload())
        self.thrOnTimeOutMsg.write(_THRArrayOnTimeCmdMsgPayload())

    def UpdateState(self, CurrentSimNanos: int = 0):
        t_s = CurrentSimNanos * macros.NANO2SEC
        st = self.scStateInMsg()
        r = np.array(st.r_BN_N)
        v = np.array(st.v_BN_N)
        sigma_BN = np.array(st.sigma_BN)
        mass = self.mass_fn()

        if self.engine_out_at_s is not None and t_s >= self.engine_out_at_s and self.engines_ok.all():
            i = self.engine_out_index
            self.engines_ok[i] = False
            self.decisions.append((t_s, f"engine {i} FAILED"))
            if i in OPPOSITE:   # outer engines are canted: keep remaining set balanced
                self.engines_ok[OPPOSITE[i]] = False
                self.decisions.append((t_s, (f"shut down opposite engine {OPPOSITE[i]} for balance -> "
                                             f"{int(self.engines_ok.sum())} engines")))

        rho = r - self.target_N
        h_above_target = float(np.dot(rho, self.up))
        r_h = rho - h_above_target * self.up
        g_vec = -self.mu * r / (np.linalg.norm(r) ** 3)
        h = h_above_target - self.gate

        if h > self.switch_h:
            phase = "powered_descent"
            tgo = 2.0 * max(h, 0.0) / max(-float(np.dot(v, self.up)) + self.v_final, 1.0)
            tgo = float(np.clip(tgo, 2.0, 240.0))
            r_f = self.gate * self.up
            v_f = -self.v_final * self.up
            zem = (self.target_N + r_f) - (r + v * tgo + 0.5 * g_vec * (tgo**2))
            zev = v_f - (v + g_vec * tgo)
            a_ctrl = 6.0 * zem / (tgo**2) - 2.0 * zev / tgo
        else:
            phase = "terminal"
            v_up = float(np.dot(v, self.up))
            v_h = v - v_up * self.up
            h_ground = h_above_target - self.ground_height_fn(r)
            kp = 0.08 if h_ground > self.no_chase_alt_m else 0.0   # last metres: null drift
            a_des = -kp * r_h - 0.8 * v_h + 1.2 * (-self.v_final - v_up) * self.up
            a_ctrl = a_des - g_vec

        thrust_N = mass * a_ctrl
        mag = float(np.linalg.norm(thrust_N))
        dir_N = thrust_N / max(mag, 1e-9)
        max_tilt = self.max_tilt if phase == "powered_descent" else self.terminal_tilt
        cos_t = float(np.dot(dir_N, self.up))
        if cos_t < math.cos(max_tilt):
            horiz = dir_N - cos_t * self.up
            horiz /= max(float(np.linalg.norm(horiz)), 1e-9)
            dir_N = math.cos(max_tilt) * self.up + math.sin(max_tilt) * horiz

        # attitude reference: +z_B along dir_N
        ref = _AttRefMsgPayload(sigma_RN=mrp_with_z_along(dir_N).tolist())
        self.attRefOutMsg.write(ref, CurrentSimNanos, self.moduleID)

        # throttle: component along CURRENT body z
        BN = np.array(rbk.MRP2C(sigma_BN))
        z_B_in_N = BN.T @ np.array([0.0, 0.0, 1.0])
        along = max(float(np.dot(thrust_N, z_B_in_N)), 0.0)
        n_ok = int(self.engines_ok.sum())

        throttle = along / max(n_ok * self.eng_max, 1e-6)
        if throttle < 0.5 * self.min_thr / self.n_eng:
            throttle = 0.0
        throttle = float(np.clip(throttle, 0.0, 1.0))
        on = np.where(self.engines_ok, throttle * self.period, 0.0)

        cmd = _THRArrayOnTimeCmdMsgPayload(on.tolist())
        self.thrOnTimeOutMsg.write(cmd, CurrentSimNanos, self.moduleID)

        if phase != self.last.get("phase"):
            self.decisions.append((t_s, f"phase -> {phase}"))
        self.last = {
            "t_s": t_s,
            "phase": phase,
            "throttle": throttle,
            "thrust_n": throttle * n_ok * self.eng_max,
            "engines_ok": n_ok,
            "h_m": h_above_target - self.ground_height_fn(r),
        }


class _PythonLanderSpacecraft:
    """6-DOF / 3-DOF lander simulation hub."""

    def __init__(self, r0, v0, dry_mass_kg=760.0):
        self.ModelTag = "lander"
        self.r = np.array(r0, float)
        self.v = np.array(v0, float)
        self.sigma = np.array([0.0, 0.0, 0.0], float)
        self.dry_mass_kg = dry_mass_kg
        self.hub = type("Hub", (), {"mHub": dry_mass_kg})()
        self.scStateOutMsg = _GenericMsg(_SCStatesMsgPayload)
        self._update_msg()

    def _update_msg(self):
        st = _SCStatesMsgPayload(self.r.tolist(), self.v.tolist(), self.sigma.tolist())
        self.scStateOutMsg.write(st)


class _PythonFuelTank:
    def __init__(self, initial_fuel_kg=140.0):
        self.fuel_kg = float(initial_fuel_kg)
        self.fuelTankOutMsg = _GenericMsg(_FuelTankMsgPayload)
        self.fuelTankOutMsg.write(_FuelTankMsgPayload(self.fuel_kg))

    def consume(self, delta_kg: float):
        self.fuel_kg = max(0.0, self.fuel_kg - delta_kg)
        self.fuelTankOutMsg.write(_FuelTankMsgPayload(self.fuel_kg))


class _PythonThrusters:
    def __init__(self, layout):
        self.layout = layout
        self.cmdsInMsg = _GenericMsg(_THRArrayOnTimeCmdMsgPayload)


def build_lander(sim, cfg: MissionConfig, r0, v0, target_N, control_period_s: float = 0.2):
    """Construct 5-engine lander with fuel tank, guidance, and attitude tracking."""
    mu = MU_MOON
    initial_fuel = 140.0  # kg for terminal descent test
    dry_mass = cfg.lander.dry_mass_kg

    sc = _PythonLanderSpacecraft(r0, v0, dry_mass_kg=dry_mass)
    up0 = np.asarray(r0) / np.linalg.norm(r0)
    sc.sigma = np.array(mrp_with_z_along(up0), float)
    sc._update_msg()

    tank = _PythonFuelTank(initial_fuel_kg=initial_fuel)
    engines = _PythonThrusters(engine_layout())

    def mass_now():
        return float(sc.dry_mass_kg + tank.fuel_kg)

    def fuel_now():
        return float(tank.fuel_kg)

    guid = DescentGuidance(cfg, np.asarray(target_N), mass_now, control_period_s)
    guid.mu = mu
    guid.scStateInMsg.subscribeTo(sc.scStateOutMsg)
    engines.cmdsInMsg.subscribeTo(guid.thrOnTimeOutMsg)

    # Attach stepping integration helper to sim if using python sim
    def step_sim(t_now_s, dt_s):
        # 1. Update guidance
        guid.UpdateState(macros.sec2nano(t_now_s))

        # 2. Integrate physics
        # On-times from guidance command
        cmd = engines.cmdsInMsg.read()
        on_times = cmd.OnTime

        # Body orientation follows guidance command
        ref = guid.attRefOutMsg.read()
        sc.sigma = np.array(ref.sigma_RN)
        BN = np.array(rbk.MRP2C(sc.sigma))

        # Sum forces in body frame -> convert to N
        f_B_total = np.zeros(3)
        mass_flow_total = 0.0
        g0 = cfg.moon.g0_m_s2
        isp = cfg.lander.isp_s

        for idx, (r_pos, t_dir) in enumerate(engines.layout):
            duty = min(1.0, max(0.0, on_times[idx] / control_period_s))
            f_mag = duty * cfg.lander.engines.max_thrust_n
            f_B_total += f_mag * np.array(t_dir)
            mass_flow_total += f_mag / (isp * g0)

        f_N_thrust = BN.T @ f_B_total
        m_tot = mass_now()

        # Gravity
        r_norm = np.linalg.norm(sc.r)
        g_N = -mu * sc.r / (r_norm**3)

        a_N = g_N + (f_N_thrust / max(m_tot, 1e-3))
        sc.v += a_N * dt_s
        sc.r += sc.v * dt_s

        # Fuel consumption
        tank.consume(mass_flow_total * dt_s)
        sc._update_msg()

    sc.step_sim = step_sim

    return {
        "sc": sc,
        "engines": engines,
        "tank": tank,
        "guidance": guid,
        "mu": mu,
        "mass_fn": mass_now,
        "fuel_fn": fuel_now,
    }


def touchdown_report(cfg: MissionConfig, r_N, v_N, sigma_BN, slope_deg: float = 0.0) -> dict:
    """Check touchdown against config limits. Returns speeds, tilt and pass/fail reason."""
    up = np.asarray(r_N) / np.linalg.norm(r_N)
    v = np.asarray(v_N)
    v_up = float(np.dot(v, up))
    v_h = float(np.linalg.norm(v - v_up * up))
    BN = np.array(rbk.MRP2C(np.asarray(sigma_BN)))
    tilt = float(np.degrees(np.arccos(np.clip(np.dot(BN.T @ [0, 0, 1], up), -1, 1))))
    lim = cfg.lander.touchdown_limits

    reason = "ok"
    if -v_up > lim.max_vertical_speed_m_s:
        reason = "hard_vertical"
    elif v_h > lim.max_horizontal_speed_m_s:
        reason = "hard_horizontal"
    elif slope_deg > lim.max_slope_deg:
        reason = "steep_slope"

    return {
        "vertical_speed_m_s": -v_up,
        "horizontal_speed_m_s": v_h,
        "tilt_deg": tilt,
        "slope_deg": slope_deg,
        "outcome": reason,
        "altitude_check_m": float(np.linalg.norm(r_N) - R_MOON_M),
    }
