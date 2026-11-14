#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Gym-style environment around :class:`~lunar_ops.rover.Rover`.

The observation is a plain JSON-serialisable dictionary so the same data can
be handed to an in-process policy or to a remote AI agent over a WebSocket.
"""

from __future__ import annotations

import math
from typing import Any

from lunar_ops.config import MissionConfig
from lunar_ops.policies import HeuristicPolicy, Policy
from lunar_ops.rover import Action, Rover
from lunar_ops.world import World

PROVENANCE = {
    "terrain": "GENERATED - NOT OBSERVED (synthetic demo tile)",
    "psr": "GENERATED (from the synthetic tile, not NASA LPSR)",
    "ice_evidence": "MODELLED (weighted composite, not a detection)",
    "illumination": "MODELLED (simplified Sun model, not SPICE)",
    "earth_link": "MODELLED (simplified libration model, Earth toward the 0 deg meridian)",
    "rover": "MODELLED (kinematic rover, ASSUMED parameters)",
}

PROVENANCE_REAL = {
    **PROVENANCE,
    "terrain": "NASA LRO LOLA 5 m terrain - observed",
    "psr": "MODELLED from the DEM (horizon test), not NASA LPSR polygons",
}


SITE_LABELS = {"lola5m_site01": "Site01, Connecting Ridge", "lola5m_site04": "Site04, Shackleton rim"}


def provenance_for(world: World) -> dict[str, str]:
    """Return the provenance labels that apply to ``world``."""
    if not getattr(world, "real", False):
        return dict(PROVENANCE)
    out = dict(PROVENANCE_REAL)
    out["terrain"] += f" ({SITE_LABELS.get(world.region, world.region)})"
    return out


class RoverEnv:
    """Rover surface mission environment.

    :param cfg: mission configuration.
    :param seed: seed for site selection and the landing point.
    """

    def __init__(self, cfg: MissionConfig | None = None, seed: int = 0) -> None:
        self.cfg = cfg or MissionConfig()
        self.seed = seed
        self.world = World(self.cfg, seed=seed)
        self.rover = Rover(self.world, self.cfg)
        self.decisions = 0
        self.blocked_recent = False

    # ---------------------------------------------------------------- lifecycle
    def reset(self, seed: int | None = None) -> dict[str, Any]:
        """Start a new episode, optionally with a different site/landing seed."""
        if seed is not None and seed != self.seed:
            self.seed = seed
            self.world = World(self.cfg, seed=seed)
            self.rover = Rover(self.world, self.cfg)
        else:
            self.rover.reset()
        self.decisions = 0
        return self.observe()

    def prior(self) -> dict[str, Any]:
        """Orbital-map prior for planners, including an illumination predictor."""
        p = self.world.prior()
        p["lit_map_fn"] = self.world.lit_map
        return p

    @property
    def done(self) -> bool:
        """True once the episode has ended (any outcome other than running)."""
        return self.rover.state.outcome != "running" or not self.rover.state.alive

    # -------------------------------------------------------------- observation
    def observe(self, with_patch: bool = True) -> dict[str, Any]:
        """Return the current observation."""
        st, w = self.rover.state, self.world
        rc = self.cfg.rover
        targets = []
        for t in w.targets:
            targets.append({**t, "sampled": t["id"] in self.rover._sampled,
                            "dist_m": round(math.hypot(t["x_m"] - st.x_m, t["y_m"] - st.y_m), 1)})
        obs: dict[str, Any] = {
            "t_s": round(st.t_s, 1),
            "pose": {"x_m": round(st.x_m, 2), "y_m": round(st.y_m, 2),
                     "heading_deg": round(math.degrees(st.heading_rad), 1)},
            "speed_m_s": round(st.speed_m_s, 5),
            "battery_wh": round(st.battery_wh, 2),
            "battery_frac": round(st.battery_wh / rc.battery_capacity_wh, 4),
            "solar_w": round(st.solar_w, 1),
            "load_w": round(st.load_w, 1),
            "lit": st.lit,
            "earth_visible": st.earth_visible,
            "in_psr": st.in_psr,
            "mode": st.mode,
            "drill_left_s": round(st.drill_left_s, 1),
            "drill_target": st.drill_target,
            "aborted": st.aborted,
            "alive": st.alive,
            "outcome": st.outcome,
            "distance_m": round(st.distance_m, 1),
            "energy_used_wh": round(st.energy_used_wh, 1),
            "slope_deg": round(w.sample(w.slope, st.x_m, st.y_m), 1),
            "hazard": round(w.sample(w.hazard, st.x_m, st.y_m), 3),
            "ice_score": round(w.sample(w.ice_score, st.x_m, st.y_m), 3),
            "height_m": round(w.sample(w.height, st.x_m, st.y_m), 2),
            "sun": {"az_deg": round(w.sun_azimuth_deg(st.t_s), 2), "elev_deg": w.sun_elevation_deg()},
            "earth_elev_deg": round(w.earth_elevation_deg(st.t_s), 2),
            "targets": targets,
            "samples": list(st.samples),
        }
        if with_patch:
            obs["patch"] = w.patch(st.x_m, st.y_m, st.t_s)
        return obs

    # --------------------------------------------------------------------- step
    def step(self, action: Action) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        """Advance one decision period.

        :return: ``(observation, events, done)``.
        """
        self.rover.step(action, self.cfg.decision_dt_s)
        self.decisions += 1
        return self.observe(), self.rover.pop_events(), self.done

    def summary(self) -> dict[str, Any]:
        """Return mission metrics for reports and baselines."""
        st = self.rover.state
        return {
            "outcome": st.outcome,
            "sim_days": round(st.t_s / 86400.0, 2),
            "samples": len(st.samples),
            "sites": len(self.world.targets),
            "evidence_total": round(sum(s["ice_evidence_score"] for s in st.samples), 3),
            "distance_m": round(st.distance_m, 1),
            "energy_used_wh": round(st.energy_used_wh, 1),
            "battery_wh": round(st.battery_wh, 1),
            "decisions": self.decisions,
        }


def run_episode(policy: Policy | None = None, cfg: MissionConfig | None = None, seed: int = 0,
                max_decisions: int | None = None, verbose: bool = False) -> dict[str, Any]:
    """Run one full episode headlessly and return its summary.

    :param policy: controller; defaults to :class:`HeuristicPolicy`.
    :param cfg: mission configuration.
    :param seed: world seed.
    :param max_decisions: optional cap on the number of decisions.
    :param verbose: print events as they happen.
    """
    env = RoverEnv(cfg, seed=seed)
    policy = policy or HeuristicPolicy()
    policy.reset(env.prior(), env.cfg)
    obs = env.observe()
    limit = max_decisions or int(env.cfg.mission_duration_s / env.cfg.decision_dt_s) + 1
    for _ in range(limit):
        act = policy.act(obs)
        obs, events, done = env.step(act)
        if verbose:
            for e in events:
                print(f"[{e['t_s'] / 3600.0:8.2f} h] {e['kind']}: {e['msg']}")
            if hasattr(policy, "drain_notes"):
                for n in policy.drain_notes():
                    print(f"[{obs['t_s'] / 3600.0:8.2f} h] note: {n}")
        if done:
            break
    return env.summary()
