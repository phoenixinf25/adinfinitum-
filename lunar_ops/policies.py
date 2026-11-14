#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Rover policies: the plug-in interface for AI models and a physics baseline.

Any controller (a neural network, a script, a remote agent) implements
:class:`Policy`. The baseline :class:`HeuristicPolicy` is an energy-aware
planner that every AI policy should be compared against.
"""

from __future__ import annotations

import heapq
import math
from typing import Any, Protocol, runtime_checkable

import numpy as np

from lunar_ops.config import MissionConfig
from lunar_ops.rover import Action

_NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


@runtime_checkable
class Policy(Protocol):
    """Interface every rover controller implements."""

    name: str

    def reset(self, prior: dict[str, Any], cfg: MissionConfig) -> None:
        """Called once per episode with the orbital-map prior and mission configuration."""

    def act(self, obs: dict[str, Any]) -> Action:
        """Return the next action for the observation ``obs``."""


def _wrap_pi(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


class HeuristicPolicy:
    """Energy-aware ice-evidence prospecting planner (physics baseline).

    The planner estimates the battery energy of each site's round trip with a
    risk-weighted shortest-path search, picks the site with the best
    evidence-per-energy ratio that fits the battery, drives there, drills,
    retreats to non-shadowed ground and recharges before the next dip.

    :param recharge_frac: battery fraction to reach before starting a dip [-].
    :param reserve_frac: battery fraction that must remain after a round trip [-].
    :param coarse_m: planning-grid cell size [m].
    """

    name = "baseline-heuristic"

    def __init__(self, recharge_frac: float = 0.85, reserve_frac: float = 0.2,
                 coarse_m: float = 10.0) -> None:
        self.recharge_frac = recharge_frac
        self.reserve_frac = reserve_frac
        self.coarse_m = coarse_m
        self.notes: list[str] = []
        self.retry_at_s = 0.0  # [s] earliest time of the next site selection
        self.seek_age = 0  # [-] decisions since the last lit-ground plan
        self.stuck_events = 0  # [-] consecutive blocked-terrain replans for the current goal
        self.unreachable: set[str] = set()
        self.lit_retry_at_s = 0.0  # [s] earliest time of the next lit-ground search
        self._logged: set[str] = set()

    # ------------------------------------------------------------------- set-up
    def reset(self, prior: dict[str, Any], cfg: MissionConfig) -> None:
        """Build the coarse planning grid from the orbital-map prior."""
        self.cfg = cfg
        rc = cfg.rover
        self.mpp = float(prior["mpp"])  # [m/px]
        f = max(1, int(round(self.coarse_m / self.mpp)))
        self.f = f
        self.half_x, self.half_y = float(prior["half_x"]), float(prior["half_y"])
        rows, cols = prior["slope"].shape
        R, C = rows // f, cols // f

        def coarse(a: np.ndarray, op: str) -> np.ndarray:
            a = a[: R * f, : C * f].reshape(R, f, C, f)
            return a.max(axis=(1, 3)) if op == "max" else a.mean(axis=(1, 3))

        self.slope = coarse(prior["slope"], "max")
        self.hazard = coarse(prior["hazard"], "max")
        self.psr = coarse(prior["psr"].astype(np.float32), "mean") > 0.5
        self.psr_any = coarse(prior["psr"].astype(np.float32), "max") > 0.0  # any shadowed pixel
        self.R, self.C = R, C
        self.cell_m = self.mpp * f  # [m]
        self.targets = {t["id"]: t for t in prior["targets"]}
        self.blocked = (self.slope >= rc.slope_limit_deg) | (self.hazard >= rc.hazard_block)
        self.extra_blocked: set[tuple[int, int]] = set()
        self.lit_map_fn = prior.get("lit_map_fn")

        # Per-cell move cost in Wh/m, risk weighted (planning cost, not a physical estimate).
        span = max(rc.slope_limit_deg - rc.slope_derate_start_deg, 1e-6)
        derate = np.clip(1.0 - (self.slope - rc.slope_derate_start_deg) / span, 0.2, 1.0)
        speed = rc.max_speed_m_s * derate * 0.9  # [m/s] assumed 10 % margin
        # Net drain per cell uses the predicted sunlight fraction over a lunar day (from the horizon model):
        # sunlit ground is paid for by the array, shadowed ground by the battery. A floor of a quarter of the
        # drive load is kept as a margin (ASSUMPTION, not a measured value).
        illum = prior.get("illum_frac")
        frac = coarse(illum, "mean") if illum is not None else np.where(self.psr, 0.0, 0.5)
        net = np.maximum(rc.load_drive_w * 0.25, rc.load_drive_w - rc.solar_peak_w * frac)  # [W]
        power = np.where(self.psr, rc.load_drive_w + rc.heater_w, net)  # [W]
        risk = 1.0 + 2.0 * self.slope / rc.slope_limit_deg + 4.0 * self.hazard
        self.energy_per_m = power / speed / 3600.0  # [Wh/m] physical estimate, used for the battery check
        self.wh_per_m = self.energy_per_m * risk  # [Wh/m] risk-weighted, used only to choose routes

        # Static field: cheapest energy from every cell back to non-shadowed ground.
        safe = [(r, c) for r in range(R) for c in range(C)
                if not self.psr_any[r, c] and not self.blocked[r, c]]
        self.back_cost, self.back_prev = self._dijkstra(safe)

        self.goal: str | None = None
        self.path: list[tuple[float, float]] = []
        self.state = "START"
        self.stuck_counter = 0
        self.last_xy = (0.0, 0.0)
        self.notes = []
        self._logged = set()
        self.retry_at_s = 0.0
        self.lit_retry_at_s = 0.0
        self.stuck_events = 0
        self.unreachable = set()
        self.finished = False

    # --------------------------------------------------------------- path search
    def _cell(self, x: float, y: float) -> tuple[int, int]:
        r = int((self.half_y - y) / self.cell_m)
        c = int((x + self.half_x) / self.cell_m)
        return min(max(r, 0), self.R - 1), min(max(c, 0), self.C - 1)

    def _xy(self, r: int, c: int) -> tuple[float, float]:
        return (c + 0.5) * self.cell_m - self.half_x, self.half_y - (r + 0.5) * self.cell_m

    def _dijkstra(self, sources: list[tuple[int, int]]) -> tuple[np.ndarray, np.ndarray]:
        """Energy-cost field from ``sources`` with predecessor links (flat indices)."""
        dist = np.full((self.R, self.C), np.inf)
        prev = np.full((self.R, self.C), -1, dtype=np.int64)
        heap: list[tuple[float, int, int]] = []
        for r, c in sources:
            dist[r, c] = 0.0
            heap.append((0.0, r, c))
        heapq.heapify(heap)
        wh, blocked, extra = self.wh_per_m, self.blocked, self.extra_blocked
        R, C, cm = self.R, self.C, self.cell_m
        while heap:
            d, r, c = heapq.heappop(heap)
            if d > dist[r, c]:
                continue
            for dr, dc in _NEIGHBOURS:
                nr, nc = r + dr, c + dc
                if nr < 0 or nc < 0 or nr >= R or nc >= C or blocked[nr, nc] or (nr, nc) in extra:
                    continue
                step = cm * (1.4142 if dr and dc else 1.0)
                nd = d + step * 0.5 * (wh[r, c] + wh[nr, nc])
                if nd < dist[nr, nc]:
                    dist[nr, nc] = nd
                    prev[nr, nc] = r * C + c
                    heapq.heappush(heap, (nd, nr, nc))
        return dist, prev

    def _trace(self, prev: np.ndarray, goal: tuple[int, int]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        idx = goal[0] * self.C + goal[1]
        while idx >= 0:
            r, c = divmod(idx, self.C)
            out.append(self._xy(r, c))
            idx = int(prev[r, c])
        out.reverse()
        return out

    def _path_energy(self, prev: np.ndarray, cell: tuple[int, int]) -> float:
        """Physical energy [Wh] along the predecessor chain from ``cell`` back to its source."""
        total, idx = 0.0, cell[0] * self.C + cell[1]
        while idx >= 0:
            r, c = divmod(idx, self.C)
            nxt = int(prev[r, c])
            if nxt < 0:
                break
            r2, c2 = divmod(nxt, self.C)
            step = self.cell_m * (1.4142 if (r != r2 and c != c2) else 1.0)
            total += step * 0.5 * (self.energy_per_m[r, c] + self.energy_per_m[r2, c2])
            idx = nxt
        return total

    def _cells_of(self, prev: np.ndarray, cell: tuple[int, int]) -> list[tuple[int, int]]:
        """Cells from ``cell`` back to the source of a predecessor field (inclusive)."""
        out, idx = [], cell[0] * self.C + cell[1]
        while idx >= 0:
            r, c = divmod(idx, self.C)
            out.append((r, c))
            idx = int(prev[r, c])
        return out

    def _lit(self, r: int, c: int, t_s: float) -> bool:
        if self.lit_map_fn is None:
            return not self.psr[r, c]
        m = self.lit_map_fn(t_s)
        return bool(m[min(r * self.f + self.f // 2, m.shape[0] - 1), min(c * self.f + self.f // 2, m.shape[1] - 1)])

    def simulate_trip(self, out_cells: list[tuple[int, int]], back_cells: list[tuple[int, int]], t0: float) -> tuple[float, float]:
        """Predict a trip with time-dependent sunlight.

        Drive ``out_cells``, drill, drive ``back_cells``, then wait asleep until the end cell is sunlit.
        :return: (largest battery deficit along the way [Wh], arrival time of sunlight at the end [s]).
        """
        rc = self.cfg.rover
        span = max(rc.slope_limit_deg - rc.slope_derate_start_deg, 1e-6)
        t, net, worst = t0, 0.0, 0.0

        def leg(cells: list[tuple[int, int]]) -> None:
            nonlocal t, net, worst
            for (r, c), (r2, c2) in zip(cells, cells[1:]):
                step = self.cell_m * (1.4142 if (r != r2 and c != c2) else 1.0)
                derate = min(1.0, max(0.2, 1.0 - (self.slope[r2, c2] - rc.slope_derate_start_deg) / span))
                dt = step / (rc.max_speed_m_s * derate * 0.9)
                load = rc.load_drive_w + (rc.heater_w if self.psr[r2, c2] else 0.0)
                solar = rc.solar_peak_w if self._lit(r2, c2, t) else 0.0
                net += (load - solar) * dt / 3600.0
                net = max(net, worst - (rc.battery_capacity_wh))  # cannot charge above full
                worst = max(worst, net)
                t += dt

        leg(out_cells)
        r, c = out_cells[-1]
        net += (rc.load_drill_w + (rc.heater_w if self.psr[r, c] else 0.0)) * rc.drill_duration_s / 3600.0
        worst = max(worst, net)
        t += rc.drill_duration_s
        leg(back_cells)
        r, c = back_cells[-1]
        waited = 0.0
        while not self._lit(r, c, t) and waited < 3 * 86400.0:  # sleep until sunrise at the end point
            net += rc.load_sleep_w * 1.0
            worst = max(worst, net)
            t += 3600.0
            waited += 3600.0
        if waited >= 3 * 86400.0:
            worst = float("inf")
        return worst, t

    # ------------------------------------------------------------------ decision
    def _select_target(self, obs: dict[str, Any]) -> tuple[str | None, str]:
        rc = self.cfg.rover
        start = self._cell(obs["pose"]["x_m"], obs["pose"]["y_m"])
        self.blocked[start] = False
        fwd, prev = self._dijkstra([start])
        usable = obs["battery_wh"] - self.reserve_frac * rc.battery_capacity_wh
        drill_wh = rc.load_drill_w * rc.drill_duration_s / 3600.0
        best: tuple[float, str] | None = None
        notes: list[str] = []
        for t in obs["targets"]:
            if t["sampled"]:
                continue
            if t["id"] in self.unreachable:
                continue
            cell = self._cell(t["x_m"], t["y_m"])
            e_to, e_back = fwd[cell], self.back_cost[cell]
            if not np.isfinite(e_to) or not np.isfinite(e_back):
                notes.append(f"{t['id']} rejected: no drivable path")
                continue
            out_cells = list(reversed(self._cells_of(prev, cell)))
            back_cells = list(reversed(out_cells))  # return the way it came, to the sunlit departure point
            need, _ = self.simulate_trip(out_cells, back_cells, obs["t_s"])
            if need > usable:
                notes.append(f"{t['id']} rejected: predicted battery draw {need:.0f} Wh > usable {usable:.0f} Wh"
                             if np.isfinite(need) else f"{t['id']} rejected: no sunlight at the return point within 3 days")
                continue
            value = t["ice_score"] / need
            if best is None or value > best[0]:
                best = (value, t["id"])
        for n in notes:
            if n not in self._logged:
                self._logged.add(n)
                self.notes.append(n)
        if best is None:
            self.retry_at_s = obs["t_s"] + 3600.0  # [s] do not re-plan every decision
            return None, "no reachable site within the battery budget"
        tid = best[1]
        t = self.targets[tid]
        cell = self._cell(t["x_m"], t["y_m"])
        self.path = self._trace(prev, cell)
        self.path[-1] = (t["x_m"], t["y_m"])
        out_cells = list(reversed(self._cells_of(prev, cell)))
        self.return_path = [self._xy(r, c) for r, c in reversed(out_cells)]
        self.return_path[-1] = (obs["pose"]["x_m"], obs["pose"]["y_m"])
        need, t_back = self.simulate_trip(out_cells, list(reversed(out_cells)), obs["t_s"])
        return tid, (f"Selected {tid}: ice-evidence score {t['ice_score']:.2f}, depth {t.get('depth_m', 0):.0f} m, "
                     f"predicted battery draw {need:.0f} Wh of {usable:.0f} Wh usable, back in sunlight after "
                     f"{(t_back - obs['t_s']) / 3600.0:.1f} h")

    def _plan_retreat(self, obs: dict[str, Any]) -> bool:
        """Plan the cheapest route to non-shadowed ground; prefer currently lit ground."""
        start = self._cell(obs["pose"]["x_m"], obs["pose"]["y_m"])
        self.blocked[start] = False
        if not obs["in_psr"]:
            self.path = []
            return True
        fwd, prev = self._dijkstra([start])
        cand = np.argwhere(~self.psr_any & np.isfinite(fwd))
        if len(cand) == 0:
            return False
        costs = fwd[cand[:, 0], cand[:, 1]]
        r, c = cand[int(np.argmin(costs))]
        self.path = self._trace(prev, (int(r), int(c)))
        return True

    def _follow(self, obs: dict[str, Any]) -> Action:
        x, y = obs["pose"]["x_m"], obs["pose"]["y_m"]
        hd = math.radians(obs["pose"]["heading_deg"])
        while len(self.path) > 1 and math.hypot(self.path[0][0] - x, self.path[0][1] - y) < 6.0:
            self.path.pop(0)
        if len(self.path) == 1 and math.hypot(self.path[0][0] - x, self.path[0][1] - y) < 3.0:
            self.path = []  # arrived
            return Action(mode="hold", phase="ARRIVED", reason="Reached end of planned path")
        look = self.path[0]
        for p in self.path:
            look = p
            if math.hypot(p[0] - x, p[1] - y) >= 12.0:
                break
        err = _wrap_pi(math.atan2(look[0] - x, look[1] - y) - hd)
        omega = float(np.clip(err / (self.cfg.rover.max_turn_rate_rad_s * self.cfg.decision_dt_s), -1.0, 1.0))
        v = 1.0 if abs(err) < 0.35 else 0.0
        return Action(v=v, omega=omega, mode="drive")

    def act(self, obs: dict[str, Any]) -> Action:
        """Return the next action (see :class:`Policy`)."""
        rc = self.cfg.rover
        x, y = obs["pose"]["x_m"], obs["pose"]["y_m"]
        frac = obs["battery_frac"]

        if obs["aborted"] or not obs["alive"]:
            return Action(mode="sleep", phase="SAFE", reason="Safe mode: abort latched" if obs["aborted"] else "")

        # Continue an active drill.
        if obs["drill_left_s"] > 0.0:
            return Action(mode="drill", phase="DRILL", reason=f"Drilling {obs['drill_target']}")

        # Stuck detection: no progress while commanded to drive.
        moved = math.hypot(x - self.last_xy[0], y - self.last_xy[1])
        self.last_xy = (x, y)
        if self.state in ("TRAVERSE", "RETURN") and moved < 0.05:
            self.stuck_counter += 1
        else:
            self.stuck_counter = 0
        if self.stuck_counter >= 8 and self.path:
            here = self._cell(x, y)
            self.extra_blocked.update({self._cell(*p) for p in self.path[:2]} - {here})
            self.stuck_events += 1
            self.stuck_counter = 0
            self.path = []
            if self.goal and self.stuck_events >= 3:
                self.unreachable.add(self.goal)
                self.notes.append(f"{self.goal} abandoned: repeatedly blocked by terrain")
                self.stuck_events = 0
            self.goal = None
            self.state = "REPLAN"
            self.notes.append("Blocked ahead: marking cells impassable and replanning")

        # Critical battery: leave shadow, or abandon the trip and find sunlight.
        if frac < 0.3 and not obs["lit"]:
            if obs["in_psr"] and self.state != "RETURN":
                if self._plan_retreat(obs):
                    self.state, self.goal = "RETURN", None
                    return Action(phase="RETURN", mode="hold",
                                  reason=f"Battery {frac * 100:.0f} % inside shadow: retreating to sunlit ground")
            elif not obs["in_psr"] and self.state == "TRAVERSE":
                self.state, self.goal, self.path = "RECHARGE", None, []
                self.notes.append(f"Battery {frac * 100:.0f} % in the dark: abandoning the trip to find sunlight")

        if self.state == "TRAVERSE" and self.goal:
            tgt = self.targets[self.goal]
            if (math.hypot(tgt["x_m"] - x, tgt["y_m"] - y) <= rc.sample_radius_m * 0.8
                    and not next(t for t in obs["targets"] if t["id"] == self.goal)["sampled"]):
                return Action(mode="drill", phase="DRILL", reason=f"Arrived at {self.goal}: starting drill")
            if next(t for t in obs["targets"] if t["id"] == self.goal)["sampled"]:
                if getattr(self, "return_path", None):
                    self.path, self.return_path = list(self.return_path), None
                    self.state, self.goal = "RETURN", None
                elif self._plan_retreat(obs):
                    self.state, self.goal = "RETURN", None
                return Action(mode="hold", phase="RETURN", reason=f"Sample at {tgt['id']} complete: returning to the sunlit departure point")
            act = self._follow(obs)
            act.phase = "TRAVERSE"
            act.reason = f"Driving to {self.goal}"
            return act

        if self.state == "RETURN":
            if not self.path and not obs["in_psr"]:
                self.state = "RECHARGE"
            elif not self.path and obs["in_psr"]:
                self._plan_retreat(obs)
            if self.path:
                act = self._follow(obs)
                act.phase, act.reason = "RETURN", "Returning to sunlit ground"
                return act
            self.state = "RECHARGE"

        if self.state in ("START", "REPLAN", "RECHARGE", "IDLE"):
            if frac < self.recharge_frac and obs["lit"]:
                self.state = "RECHARGE"
                return Action(mode="sleep", phase="RECHARGE", reason=f"Recharging in sunlight ({frac * 100:.0f} %)")
            if frac < self.recharge_frac and not obs["lit"] and not obs["in_psr"]:
                lit_goal = True
                if (not self.path or self.seek_age >= 20) and obs["t_s"] >= self.lit_retry_at_s:
                    lit_goal = self._plan_lit(obs)
                    self.seek_age = 0
                    if not lit_goal:
                        self.lit_retry_at_s = obs["t_s"] + 1800.0  # [s] wait before searching again
                elif not self.path:
                    lit_goal = False
                else:
                    self.seek_age += 1
                if lit_goal:
                    act = self._follow(obs)
                    act.phase, act.reason = "SEEK_SUN", "Moving to currently lit ground to recharge"
                    return act
                return Action(mode="sleep", phase="WAIT_SUN", reason="No lit ground reachable: waiting for sunrise")
            if not obs["lit"] and not obs["in_psr"]:
                # Never start a trip into shadow from darkness: find sunlight first, or wait for it.
                lit_goal = True
                if (not self.path or self.seek_age >= 20) and obs["t_s"] >= self.lit_retry_at_s:
                    lit_goal = self._plan_lit(obs)
                    self.seek_age = 0
                    if not lit_goal:
                        self.lit_retry_at_s = obs["t_s"] + 1800.0  # [s]
                elif not self.path:
                    lit_goal = False
                else:
                    self.seek_age += 1
                if lit_goal:
                    act = self._follow(obs)
                    act.phase, act.reason = "SEEK_SUN", "Rover in shadow: moving to sunlit ground before the next trip"
                    return act
                return Action(mode="sleep", phase="WAIT_SUN", reason="Rover in shadow and no sunlit ground in reach: waiting for sunrise")
            if obs["t_s"] < self.retry_at_s:
                return Action(mode="sleep", phase="IDLE", reason="Waiting before the next site selection")
            tid, why = self._select_target(obs)
            if tid is None:
                open_left = [t for t in obs["targets"] if not t["sampled"]]
                if open_left and frac < 0.97 and obs["lit"]:
                    return Action(mode="sleep", phase="RECHARGE", reason="No site fits the battery: recharging to full")
                if open_left and not self.finished:
                    self.finished = True
                    self.notes.append("No remaining site fits the battery budget: holding")
                return Action(mode="sleep", phase="IDLE", reason=why)
            self.goal, self.state = tid, "TRAVERSE"
            act = self._follow(obs)
            act.phase, act.reason = "TRAVERSE", why
            return act

        return Action(mode="hold", phase="HOLD", reason="")

    def _plan_lit(self, obs: dict[str, Any]) -> bool:
        """Plan to the cheapest currently lit, drivable cell (uses the illumination prediction)."""
        if self.lit_map_fn is None:
            return False
        full = self.lit_map_fn(obs["t_s"])[: self.R * self.f, : self.C * self.f]
        lit = full.reshape(self.R, self.f, self.C, self.f).all(axis=(1, 3))  # every pixel lit
        start = self._cell(obs["pose"]["x_m"], obs["pose"]["y_m"])
        self.blocked[start] = False
        fwd, prev = self._dijkstra([start])
        ok = np.isfinite(fwd) & ~self.psr_any & lit
        if not ok.any():
            return False
        cost = np.where(ok, fwd, np.inf)
        r, c = np.unravel_index(int(np.argmin(cost)), cost.shape)
        path = self._trace(prev, (int(r), int(c)))
        if len(path) < 2:
            return False  # already standing in the cheapest cell: nothing to plan
        self.path = path
        return True

    def drain_notes(self) -> list[str]:
        """Return and clear fact notes produced since the last call."""
        out, self.notes = self.notes, []
        return out
