#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Wire protocol between any backend and the mission-control user interface.

The user interface only understands the messages built here, so any backend
(this package's simulator, the Adinfinitium world models, a Basilisk replay)
can drive it by emitting the same messages. See ``lunar_ops/PROTOCOL.md``.
"""

from __future__ import annotations

import base64
from typing import Any

import numpy as np

from lunar_ops.env import RoverEnv, provenance_for
from lunar_ops.rover import Action

PROTOCOL_VERSION = 1

# AI stack shown in the UI. ``status`` is one of: attached, fallback, not attached.
# Backends update entries (matched by ``id``) with a ``models`` message; ``params`` is filled by them.
DEFAULT_MODELS: list[dict[str, Any]] = [
    {"id": "pilot", "name": "Pilot brain", "kind": "NEAT", "role": "Flies the lander", "phase": "DESCENT",
     "owner": "Imok", "status": "not attached", "params": None},
    {"id": "meta", "name": "Meta layer", "kind": "Dream-RSI", "role": "Tunes how the pilot evolves", "phase": "DESCENT",
     "owner": "Imok", "status": "not attached", "params": None},
    {"id": "rover", "name": "Rover brain", "kind": "PPO", "role": "Drives the rover", "phase": "ROVER OPS",
     "owner": "Nimansh", "status": "fallback", "params": None, "fallback": "physics baseline planner"},
    {"id": "light", "name": "Light model", "kind": "neural skyline", "role": "Is Sun / Earth visible here, now?",
     "phase": "ROVER OPS", "owner": "Nimansh", "status": "fallback", "params": None, "fallback": "simplified Sun model"},
    {"id": "hazard", "name": "Hazard detector", "kind": "U-Net", "role": "Marks slopes and rocks safe or dangerous",
     "phase": "ROVER OPS", "owner": "Nimansh", "status": "fallback", "params": None, "fallback": "slope rule"},
    {"id": "terrain", "name": "Terrain generator", "kind": "diffusion", "role": "Makes extra GENERATED terrain to test on",
     "phase": "ROVER OPS", "owner": "Tanush, Arnav", "status": "not attached", "params": None},
]


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def world_message(env: RoverEnv) -> dict[str, Any]:
    """Build the one-off ``world`` message (terrain rasters and static metadata).

    Rasters are row-major, row 0 is the northern edge. ``height_f32`` is
    little-endian float32 [m]; the others are uint8.
    """
    w, cfg = env.world, env.cfg
    return {
        "type": "world",
        "protocol": PROTOCOL_VERSION,
        "region": w.region,
        "rows": int(w.rows),
        "cols": int(w.cols),
        "mpp": float(w.mpp),  # [m/px]
        "half_x": float(w.half_x),  # [m]
        "half_y": float(w.half_y),  # [m]
        "provenance": provenance_for(w),
        "site": w.site,
        "height_f32": _b64(w.height.astype("<f4")),
        "slope_u8": _b64(np.clip(np.rint(w.slope), 0, 90).astype(np.uint8)),  # [deg]
        "psr_u8": _b64(w.psr.astype(np.uint8)),
        "ice_u8": _b64(np.clip(np.rint(w.ice_score * 255.0), 0, 255).astype(np.uint8)),  # score * 255
        "hazard_u8": _b64(np.clip(np.rint(w.hazard * 255.0), 0, 255).astype(np.uint8)),  # hazard * 255
        "models": DEFAULT_MODELS,
        "photo": w.photo,
        "context": None if w.context is None else {
            "rows": int(w.context["height"].shape[0]), "cols": int(w.context["height"].shape[1]),
            "mpp": w.context["mpp"], "offset_x_m": w.context["offset_m"][0], "offset_y_m": w.context["offset_m"][1],
            "height_f32": _b64(w.context["height"].astype("<f4")), "provenance": "NASA LRO LOLA 5 m terrain, 20 m display copy"},
        "targets": w.targets,
        "start": w.start,
        "limits": {
            "battery_capacity_wh": cfg.rover.battery_capacity_wh,
            "solar_peak_w": cfg.rover.solar_peak_w,
            "slope_limit_deg": cfg.rover.slope_limit_deg,
            "max_speed_m_s": cfg.rover.max_speed_m_s,
        },
        "sky": {"sun_elevation_deg": cfg.sky.sun_elevation_deg,
                "synodic_period_s": cfg.sky.synodic_period_s,
                "earth_azimuth_deg": cfg.sky.earth_azimuth_deg},
    }


class FrameBuilder:
    """Turns environment observations into ``frame`` messages.

    A packed illumination mask is attached only when the Sun azimuth has
    moved by at least ``lit_step_deg``, to keep frames small.

    :param env: environment to read illumination from.
    :param lit_step_deg: minimum Sun azimuth change between masks [deg].
    """

    def __init__(self, env: RoverEnv, lit_step_deg: float = 2.0) -> None:
        self.env = env
        self.lit_step_deg = lit_step_deg
        self._last_az: float | None = None

    def reset(self) -> None:
        """Forget the last sent illumination mask."""
        self._last_az = None

    def frame(self, obs: dict[str, Any], action: Action | None, source: str,
              events: list[dict[str, Any]] | None = None, mission_phase: str = "ROVER OPS",
              path: list[tuple[float, float]] | None = None) -> dict[str, Any]:
        """Build one ``frame`` message."""
        msg: dict[str, Any] = {
            "type": "frame",
            "t_s": obs["t_s"],
            "mission_phase": mission_phase,
            "control": source,
            "phase": action.phase if action else "HOLD",
            "reason": action.reason if action else "",
            "pose": obs["pose"],
            "speed_m_s": obs["speed_m_s"],
            "battery_wh": obs["battery_wh"],
            "battery_frac": obs["battery_frac"],
            "solar_w": obs["solar_w"],
            "load_w": obs["load_w"],
            "lit": obs["lit"],
            "earth_visible": obs["earth_visible"],
            "in_psr": obs["in_psr"],
            "mode": obs["mode"],
            "slope_deg": obs["slope_deg"],
            "hazard": obs["hazard"],
            "ice_score": obs["ice_score"],
            "height_m": obs["height_m"],
            "sun": obs["sun"],
            "earth_elev_deg": obs["earth_elev_deg"],
            "drill_left_s": obs["drill_left_s"],
            "drill_target": obs["drill_target"],
            "aborted": obs["aborted"],
            "alive": obs["alive"],
            "outcome": obs["outcome"],
            "distance_m": obs["distance_m"],
            "energy_used_wh": obs["energy_used_wh"],
            "targets": [{"id": t["id"], "sampled": t["sampled"]} for t in obs["targets"]],
            "samples": obs["samples"],
            "events": events or [],
        }
        if path:
            msg["path"] = [[round(x, 1), round(y, 1)] for x, y in path[:60]]
        az = obs["sun"]["az_deg"]
        if self._last_az is None or abs((az - self._last_az + 180.0) % 360.0 - 180.0) >= self.lit_step_deg:
            lit = self.env.world.lit_map(obs["t_s"])
            msg["lit_bits_b64"] = _b64(np.packbits(lit.astype(np.uint8).ravel()))
            self._last_az = az
        return msg
