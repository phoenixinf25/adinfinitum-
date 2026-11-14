#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Record a full mission as a replay the user interface can play offline.

The recording chains four segments:

1. ORBIT and DEORBIT: analytic Keplerian model (MODELLED), see ``mission_timeline``.
2. DESCENT: real Basilisk telemetry from ``ui/sample/descent_basilisk.csv``.
3. LANDED: rover deployment and checkout (first 10 minutes of the rover run).
4. ROVER OPS: the baseline policy flying the rover simulation.

Usage::

    python -m lunar_ops.export_sample --days 14 --out lunar_ops/ui/sample

Writes ``world.json`` and ``run.jsonl`` (one ``frame`` message per line).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lunar_ops.config import MissionConfig
from lunar_ops.env import RoverEnv
from lunar_ops.mission_timeline import descent_frames, orbit_frames
from lunar_ops.policies import HeuristicPolicy
from lunar_ops.protocol import FrameBuilder, world_message
from lunar_ops.rover import Action

DEPLOY_S = 600.0  # [s] rover deployment and checkout labelled LANDED
GAP_S = 120.0  # [s] pause between touchdown and the first rover frame


def rover_frames(env: RoverEnv, days: float, every: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the baseline policy and return thinned frames plus the mission summary."""
    policy = HeuristicPolicy()
    policy.reset(env.prior(), env.cfg)
    fb = FrameBuilder(env)
    obs = env.observe()
    act = Action()
    pending: list[dict[str, Any]] = [{"t_s": 0.0, "kind": "event", "msg": "Rover deployed at the landing point"}]
    frames: list[dict[str, Any]] = []
    last_reason = ""
    n = int(days * 86400.0 / env.cfg.decision_dt_s)
    for i in range(n):
        act = policy.act(obs)
        obs, events, done = env.step(act)
        pending.extend(events)
        for note in policy.drain_notes():
            pending.append({"t_s": obs["t_s"], "kind": "decision", "msg": note})
        if act.reason and act.reason != last_reason:
            pending.append({"t_s": obs["t_s"], "kind": "decision", "msg": act.reason})
            last_reason = act.reason
        if i % every == 0 or done or pending:
            frames.append(fb.frame(obs, act, "baseline", pending, path=policy.path))
            pending = []
        if done:
            break
    return frames, env.summary()


def record(out_dir: Path, days: float, seed: int, every: int, descent_csv: Path) -> dict[str, Any]:
    """Build the full-mission replay.

    :param out_dir: output directory.
    :param days: maximum simulated rover days to record [day].
    :param seed: world seed.
    :param every: keep one rover frame per this many decisions.
    :param descent_csv: Basilisk descent telemetry in the contract format.
    """
    env = RoverEnv(MissionConfig(), seed=seed)
    w = env.world
    sun = {"az_deg": round(w.sun_azimuth_deg(0.0), 2), "elev_deg": w.sun_elevation_deg()}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "world.json").write_text(json.dumps(world_message(env)), encoding="utf-8")

    frames = orbit_frames(w.site["lat_deg"], w.site["lon_deg"], sun)
    t_pdi = frames[-1]["t_s"]
    desc = descent_frames(descent_csv, t_pdi + 30.0, (w.start["x_m"], w.start["y_m"]), sun)
    frames += desc
    t_land = desc[-1]["t_s"]

    rv, summary = rover_frames(env, days, every)
    t0 = t_land + GAP_S
    for f in rv:
        f["t_s"] = round(f["t_s"] + t0, 1)
        for e in f["events"]:
            e["t_s"] = round(e["t_s"] + t0, 1)
        f["mission_phase"] = "LANDED" if f["t_s"] - t0 < DEPLOY_S else "ROVER OPS"
    frames += rv

    with open(out_dir / "run.jsonl", "w", encoding="utf-8") as fh:
        for f in frames:
            fh.write(json.dumps(f) + "\n")
    return {**summary, "frames": len(frames), "t_land_s": t_land, "t_end_s": frames[-1]["t_s"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=float, default=14.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--every", type=int, default=40)
    ap.add_argument("--out", default="lunar_ops/ui/sample")
    ap.add_argument("--descent", default="lunar_ops/ui/sample/descent_basilisk.csv")
    a = ap.parse_args()
    print(record(Path(a.out), a.days, a.seed, a.every, Path(a.descent)))
