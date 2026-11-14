#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Rover dynamics, power system and ice-evidence sampling.

Basilisk has no surface-rover model, so this module provides one. It is a
**MODELLED** kinematic rover: a unicycle with slope-dependent speed, a
solar/battery power balance, and a drill that records ice evidence. It does
not model wheel slip, thermal state or attitude.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from lunar_ops.config import MissionConfig
from lunar_ops.world import World

MODES = ("drive", "hold", "sleep", "drill")


@dataclass
class Action:
    """One command from a policy, operator or external AI agent.

    :param v: forward speed command, 0 to 1 of the maximum speed [-].
    :param omega: turn command, -1 (counter-clockwise) to 1 (clockwise) [-].
    :param mode: one of ``drive``, ``hold``, ``sleep`` or ``drill``.
    :param phase: short mission-phase label shown in the timeline.
    :param reason: facts-only explanation of why this action was chosen.
    """

    v: float = 0.0
    omega: float = 0.0
    mode: str = "hold"
    phase: str = "HOLD"
    reason: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Action":
        """Build a validated action from an untrusted dictionary."""
        mode = str(d.get("mode", "drive"))
        if mode not in MODES:
            mode = "hold"
        return cls(
            v=min(max(float(d.get("v", 0.0)), 0.0), 1.0),
            omega=min(max(float(d.get("omega", 0.0)), -1.0), 1.0),
            mode=mode,
            phase=str(d.get("phase", mode.upper()))[:24],
            reason=str(d.get("reason", ""))[:240],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {"v": self.v, "omega": self.omega, "mode": self.mode,
                "phase": self.phase, "reason": self.reason}


@dataclass
class RoverState:
    """Full rover state."""

    x_m: float = 0.0  # [m]
    y_m: float = 0.0  # [m]
    heading_rad: float = 0.0  # [rad] clockwise from grid +y
    speed_m_s: float = 0.0  # [m/s]
    battery_wh: float = 0.0  # [Wh]
    t_s: float = 0.0  # [s]
    mode: str = "hold"
    drill_left_s: float = 0.0  # [s]
    drill_target: str | None = None
    distance_m: float = 0.0  # [m]
    alive: bool = True
    outcome: str = "running"
    aborted: bool = False
    solar_w: float = 0.0  # [W]
    load_w: float = 0.0  # [W]
    lit: bool = False
    earth_visible: bool = False
    in_psr: bool = False
    energy_used_wh: float = 0.0  # [Wh]
    samples: list[dict[str, Any]] = field(default_factory=list)


class Rover:
    """Rover plus power model operating in a :class:`World`.

    :param world: surface world.
    :param cfg: mission configuration.
    """

    def __init__(self, world: World, cfg: MissionConfig | None = None) -> None:
        self.world = world
        self.cfg = cfg or world.cfg
        self.events: list[dict[str, Any]] = []
        self.state = RoverState()
        self.reset()

    # -------------------------------------------------------------------- reset
    def reset(self) -> None:
        """Return the rover to the landing point with a charged battery."""
        rc = self.cfg.rover
        st = self.world.start
        self.state = RoverState(
            x_m=st["x_m"], y_m=st["y_m"], heading_rad=math.radians(st["heading_deg"]),
            battery_wh=rc.battery_capacity_wh * rc.battery_initial_frac,
        )
        self.events = []
        self._update_environment()
        self._sampled: set[str] = set()

    # ------------------------------------------------------------------- events
    def _event(self, kind: str, msg: str, **data: Any) -> None:
        self.events.append({"t_s": round(self.state.t_s, 1), "kind": kind, "msg": msg, **data})

    def pop_events(self) -> list[dict[str, Any]]:
        """Return and clear events produced since the last call."""
        ev, self.events = self.events, []
        return ev

    # --------------------------------------------------------------- environment
    def _update_environment(self) -> None:
        st, w = self.state, self.world
        st.lit = w.lit_at(st.x_m, st.y_m, st.t_s)
        st.earth_visible = w.earth_visible_at(st.x_m, st.y_m, st.t_s)
        st.in_psr = w.psr_at(st.x_m, st.y_m)

    def nearest_open_target(self) -> tuple[dict[str, Any], float] | None:
        """Return the nearest unsampled target and its distance [m]."""
        best: tuple[dict[str, Any], float] | None = None
        for t in self.world.targets:
            if t["id"] in self._sampled:
                continue
            d = math.hypot(t["x_m"] - self.state.x_m, t["y_m"] - self.state.y_m)
            if best is None or d < best[1]:
                best = (t, d)
        return best

    # --------------------------------------------------------------------- step
    def abort(self, reason: str = "operator abort") -> None:
        """Latch safe mode: stop, abandon the drill, keep only survival loads."""
        if not self.state.aborted:
            self.state.aborted = True
            self.state.drill_left_s = 0.0
            self.state.drill_target = None
            self._event("abort", f"SAFE MODE latched: {reason}")

    def step(self, action: Action, dt_s: float) -> None:
        """Advance the rover by ``dt_s`` seconds holding ``action``."""
        remaining = dt_s
        sub = self.cfg.physics_dt_s
        while remaining > 1e-9 and self.state.alive and self.state.outcome == "running":
            h = min(sub, remaining)
            self._substep(action, h)
            remaining -= h

    def _substep(self, action: Action, dt: float) -> None:
        st, rc, w = self.state, self.cfg.rover, self.world
        was_lit, was_earth, was_psr = st.lit, st.earth_visible, st.in_psr

        mode = "sleep" if st.aborted else action.mode
        v_cmd, omega_cmd = (0.0, 0.0) if st.aborted else (action.v, action.omega)

        # Drill bookkeeping: drilling needs an open target in range and no motion.
        if mode == "drill" and st.drill_left_s <= 0.0 and st.drill_target is None:
            near = self.nearest_open_target()
            if near and near[1] <= rc.sample_radius_m:
                st.drill_target = near[0]["id"]
                st.drill_left_s = rc.drill_duration_s
                self._event("drill_start", f"Drilling at {near[0]['id']} ({near[1]:.1f} m from site centre)",
                            target=near[0]["id"])
            else:
                mode = "hold"
                if action.mode == "drill":
                    self._event("drill_refused", "Drill refused: no unsampled site within "
                                f"{rc.sample_radius_m:.0f} m")
        if st.drill_left_s > 0.0:
            mode = "drill"
            v_cmd = omega_cmd = 0.0

        # Motion (unicycle with slope-derated speed).
        speed = 0.0
        if mode == "drive" and v_cmd > 0.0:
            slope_here = w.sample(w.slope, st.x_m, st.y_m)
            derate = 1.0
            if slope_here > rc.slope_derate_start_deg:
                span = max(rc.slope_limit_deg - rc.slope_derate_start_deg, 1e-6)
                derate = max(0.2, 1.0 - (slope_here - rc.slope_derate_start_deg) / span)
            speed = v_cmd * rc.max_speed_m_s * derate
            st.heading_rad = (st.heading_rad + omega_cmd * rc.max_turn_rate_rad_s * dt) % (2.0 * math.pi)
            nx = st.x_m + math.sin(st.heading_rad) * speed * dt
            ny = st.y_m + math.cos(st.heading_rad) * speed * dt
            if not w.inside(nx, ny):
                speed = 0.0
                self._event("blocked", "Blocked: tile boundary", cause="out_of_bounds")
            elif (w.sample(w.slope, nx, ny) >= rc.slope_limit_deg
                  or w.sample(w.hazard, nx, ny) >= rc.hazard_block):
                speed = 0.0
                if int(st.t_s) % 60 < dt:  # rate-limit the message
                    self._event("blocked", "Blocked: ground ahead exceeds slope/hazard limit",
                                cause="slope_or_hazard")
            else:
                st.x_m, st.y_m = nx, ny
                st.distance_m += speed * dt
        elif mode == "drive":
            # turning in place
            st.heading_rad = (st.heading_rad + omega_cmd * rc.max_turn_rate_rad_s * dt) % (2.0 * math.pi)
        st.speed_m_s = speed

        # Time and environment.
        st.t_s += dt
        self._update_environment()

        # Power balance.
        solar = rc.solar_peak_w if st.lit else 0.0
        if mode == "drive":
            load = rc.load_drive_w if speed > 0.0 else rc.load_hold_w
        elif mode == "drill":
            load = rc.load_drill_w
        elif mode == "sleep":
            load = rc.load_sleep_w
        else:
            load = rc.load_hold_w
        if st.in_psr:
            load += rc.heater_w
        st.solar_w, st.load_w, st.mode = solar, load, mode
        net_wh = (solar - load) * dt / 3600.0
        st.battery_wh = min(st.battery_wh + net_wh, rc.battery_capacity_wh)
        if net_wh < 0.0:
            st.energy_used_wh += -net_wh

        # Drill completion.
        if st.drill_left_s > 0.0:
            st.drill_left_s -= dt
            if st.drill_left_s <= 0.0 and st.drill_target is not None:
                tid = st.drill_target
                tgt = next(t for t in w.targets if t["id"] == tid)
                evidence = w.sample(w.ice_score, st.x_m, st.y_m)
                self._sampled.add(tid)
                st.samples.append({"target": tid, "t_s": round(st.t_s, 1),
                                   "ice_evidence_score": round(evidence, 3),
                                   "x_m": round(st.x_m, 1), "y_m": round(st.y_m, 1)})
                st.drill_target = None
                st.drill_left_s = 0.0
                self._event("sample", f"Sample at {tid} complete: modelled ice-evidence score "
                            f"{evidence:.2f} (site {tgt['ice_score']:.2f})", target=tid)

        # Transition events (facts only).
        if was_lit and not st.lit:
            self._event("sunset", "Sun lost at rover position")
        elif not was_lit and st.lit:
            self._event("sunrise", "Sun regained at rover position")
        if was_earth and not st.earth_visible:
            self._event("link_lost", "Direct-to-Earth link lost")
        elif not was_earth and st.earth_visible:
            self._event("link_up", "Direct-to-Earth link acquired")
        if not was_psr and st.in_psr:
            self._event("enter_psr", "Entered permanently shadowed region")
        elif was_psr and not st.in_psr:
            self._event("leave_psr", "Left permanently shadowed region")

        # Termination.
        if st.battery_wh <= 0.0:
            st.battery_wh = 0.0
            st.alive = False
            st.outcome = "night_death"
            self._event("dead", "Battery empty: rover lost (night_death)")
        elif len(self._sampled) == len(w.targets) and w.targets:
            st.outcome = "complete"
            self._event("complete", "All sites sampled")
        elif st.t_s >= self.cfg.mission_duration_s:
            st.outcome = "timeout"
            self._event("timeout", "Mission duration reached")
