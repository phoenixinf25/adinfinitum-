#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Live backend: simulator, UI streaming and the AI-agent socket.

Run with::

    python -m lunar_ops.server                       # built-in baseline policy
    python -m lunar_ops.server --policy pkg.mod:MyPolicy   # your in-process model
    # or connect a remote model to ws://localhost:8600/ws/agent (see PROTOCOL.md)

Control priority: operator override, then a connected AI agent, then the
configured policy. The UI never needs to know which one is active.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from lunar_ops.config import MissionConfig
from lunar_ops import ghosts
from lunar_ops.env import RoverEnv
from lunar_ops.policies import HeuristicPolicy, Policy
import copy

from lunar_ops.protocol import DEFAULT_MODELS, PROTOCOL_VERSION, FrameBuilder, world_message
from lunar_ops.rover import Action

UI_DIR = Path(__file__).parent / "ui"
RUNS_DIR = Path(__file__).resolve().parents[1] / "runs" / "ops"
TRAIN_LOG = Path(__file__).resolve().parents[1] / "runs" / "rover" / "train_log.jsonl"
TRAIN_LOG_MAX_ROWS = 2000  # [-] most recent rows returned by /api/training
TICK_S = 0.1  # [s] wall-clock period of the streaming loop
AGENT_TIMEOUT_S = 2.0  # [s] wall-clock limit for an agent to answer one observation
MAX_STEPS_PER_TICK = 60  # [-] decisions simulated per tick at most
MANUAL_HOLD_S = 1.0  # [s] manual command validity after the last drive message


def load_policy(spec: str | None) -> Policy:
    """Load ``module:Class`` or return the baseline policy."""
    if not spec:
        return HeuristicPolicy()
    mod, _, cls = spec.partition(":")
    return getattr(importlib.import_module(mod), cls)()


class Session:
    """One running mission shared by all connected UIs."""

    def __init__(self, policy_spec: str | None = None, seed: int = 0, record: bool = True) -> None:
        self.policy_spec = policy_spec
        self.env = RoverEnv(MissionConfig(), seed=seed)
        self.policy: Policy = load_policy(policy_spec)
        self.fb = FrameBuilder(self.env)
        self.clients: set[WebSocket] = set()
        self.agent: WebSocket | None = None
        self.ingest: WebSocket | None = None  # external telemetry producer (e.g. a Basilisk bridge)
        self.ingest_world: dict[str, Any] | None = None
        self.ingest_frame: dict[str, Any] | None = None
        self.agent_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.playing = True
        self.speed = 600.0  # [x] simulated seconds per wall second
        self.override = False
        self.manual = Action(mode="hold", phase="MANUAL")
        self.manual_at = 0.0
        self.record = record
        self._rec = None
        self.pending: list[dict[str, Any]] = []
        self.last_frame: dict[str, Any] | None = None
        self.step_no = 0
        self._last_reason = ""
        self._agent_warned = 0.0
        self.models: list[dict[str, Any]] = copy.deepcopy(DEFAULT_MODELS)
        self.reset()

    # ----------------------------------------------------------------- control
    def reset(self) -> None:
        """Start a fresh episode."""
        obs = self.env.reset()
        self.policy.reset(self.env.prior(), self.env.cfg)
        self.fb.reset()
        self.obs = obs
        self.action = Action(phase="DEPLOY", reason="Mission start")
        self.pending = [{"t_s": 0.0, "kind": "event", "msg": "Mission start: rover deployed at landing point"}]
        self.step_no = 0
        self.last_frame = self.fb.frame(obs, self.action, "baseline", self.pending)
        if self.record:
            self._open_record()

    def _open_record(self) -> None:
        if self._rec:
            self._rec.close()
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._rec = open(RUNS_DIR / f"session-{time.strftime('%Y%m%d-%H%M%S')}.jsonl", "w", encoding="utf-8")

    def models_message(self) -> dict[str, Any]:
        """Return the current AI-stack registry as a ``models`` message."""
        return {"type": "models", "models": self.models}

    def update_models(self, updates: list[dict[str, Any]]) -> None:
        """Merge model status updates (matched by ``id``) from a backend."""
        for u in updates:
            for m in self.models:
                if m["id"] == u.get("id"):
                    m.update({k: v for k, v in u.items() if k in ("status", "params", "name", "kind", "role", "version")})

    def control_source(self) -> str:
        """Return which controller currently commands the rover."""
        if self.override:
            return "operator"
        if self.agent is not None:
            return "agent"
        return "baseline"

    # ------------------------------------------------------------- decision step
    async def decide(self) -> tuple[Action, str]:
        """Pick the next action from the highest-priority controller."""
        if self.env.rover.state.aborted:
            return Action(mode="sleep", phase="SAFE", reason="Safe mode: abort latched"), "baseline"
        if self.override:
            fresh = time.monotonic() - self.manual_at < MANUAL_HOLD_S
            return (self.manual if fresh else Action(mode="hold", phase="MANUAL", reason="Operator override: no command")), "operator"
        if self.agent is not None:
            try:
                await self.agent.send_json({"type": "observation", "step": self.step_no, "obs": self.obs})
                while True:
                    msg = await asyncio.wait_for(self.agent_q.get(), AGENT_TIMEOUT_S)
                    if msg.get("type") == "log":
                        self.pending.append({"t_s": self.obs["t_s"], "kind": "agent", "msg": str(msg.get("text", ""))[:240]})
                    elif msg.get("type") == "action" and msg.get("step", self.step_no) == self.step_no:
                        return Action.from_dict(msg), "agent"
            except (asyncio.TimeoutError, RuntimeError, WebSocketDisconnect):
                now = time.monotonic()
                if now - self._agent_warned > 5.0:
                    self._agent_warned = now
                    self.pending.append({"t_s": self.obs["t_s"], "kind": "event",
                                         "msg": "Agent did not answer in time: baseline policy used for this step"})
        return self.policy.act(self.obs), "baseline"

    async def step_once(self) -> None:
        """Advance one decision period."""
        act, source = await self.decide()
        self.action = act
        self.obs, events, _ = self.env.step(act)
        self.step_no += 1
        self.pending.extend(events)
        if hasattr(self.policy, "drain_notes") and source == "baseline":
            for n in self.policy.drain_notes():
                self.pending.append({"t_s": self.obs["t_s"], "kind": "decision", "msg": n})
        key = f"{source}:{act.phase}:{act.reason}"
        if act.reason and key != self._last_reason:
            self._last_reason = key
            kind = "agent" if source == "agent" else "decision"
            self.pending.append({"t_s": self.obs["t_s"], "kind": kind, "msg": act.reason})
        self.last_frame = self.fb.frame(self.obs, act, source, self.pending,
                                        path=getattr(self.policy, "path", None) if source == "baseline" else None)
        self.last_frame["aborted"] = self.env.rover.state.aborted
        self.pending = []

    # ------------------------------------------------------------------- loop
    async def run(self) -> None:
        """Stream the simulation to every connected UI."""
        while True:
            await asyncio.sleep(TICK_S)
            if not self.clients or not self.playing or self.env.done or self.ingest is not None:
                continue
            n = int(min(MAX_STEPS_PER_TICK, max(1, round(self.speed * TICK_S / self.env.cfg.decision_dt_s))))
            sent_events: list[dict[str, Any]] = []
            for _ in range(n):
                await self.step_once()
                sent_events.extend(self.last_frame["events"])
                if self.env.done:
                    break
            self.last_frame["events"] = sent_events
            await self.broadcast(self.last_frame)

    async def broadcast(self, msg: dict[str, Any]) -> None:
        """Send ``msg`` to all UIs and write it to the recording."""
        text = json.dumps(msg)
        if self._rec:
            self._rec.write(text + "\n")
        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001 - a dead client must not stop the loop
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


def create_app(policy_spec: str | None = None, seed: int = 0, record: bool = True,
               ghost_dir: Path | None = None) -> FastAPI:
    """Build the FastAPI application.

    :param ghost_dir: folder for uploaded ghost files (default ``runs/ghosts``).
    """
    sess = Session(policy_spec, seed, record)
    gdir = ghost_dir or ghosts.GHOST_DIR

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(sess.run())
        yield
        task.cancel()

    app = FastAPI(title="Adinfinitium lunar_ops", lifespan=lifespan)
    app.state.session = sess

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return {"protocol": PROTOCOL_VERSION, "control": sess.control_source(), "playing": sess.playing,
                "speed": sess.speed, "t_s": sess.obs["t_s"], "outcome": sess.obs["outcome"],
                "policy": sess.policy_spec or "baseline-heuristic", "agent_connected": sess.agent is not None}

    @app.get("/api/world")
    def world() -> JSONResponse:
        return JSONResponse(world_message(sess.env))

    @app.get("/api/lit")
    def lit(t_s: float) -> dict[str, Any]:
        mask = sess.env.world.lit_map(t_s)
        import base64
        return {"t_s": t_s, "rows": int(mask.shape[0]), "cols": int(mask.shape[1]),
                "bits_b64": base64.b64encode(np.packbits(mask.astype(np.uint8).ravel()).tobytes()).decode()}

    @app.websocket("/ws/ui")
    async def ws_ui(ws: WebSocket) -> None:
        await ws.accept()
        if sess.ingest is not None and sess.ingest_world is not None:
            await ws.send_text(json.dumps(sess.ingest_world))
            if sess.ingest_frame is not None:
                await ws.send_text(json.dumps(sess.ingest_frame))
        else:
            await ws.send_text(json.dumps(world_message(sess.env)))
            sess.fb.reset()
            first = dict(sess.last_frame or {})
            first["lit_bits_b64"] = sess.fb.frame(sess.obs, sess.action, sess.control_source())["lit_bits_b64"]
            await ws.send_text(json.dumps(first))
        await ws.send_text(json.dumps({"type": "state", "playing": sess.playing}))
        await ws.send_text(json.dumps(sess.models_message()))
        sess.clients.add(ws)
        try:
            while True:
                m = json.loads(await ws.receive_text())
                if m.get("type") != "cmd":
                    continue
                c = m.get("cmd")
                if c == "play":
                    sess.playing = True
                elif c == "pause":
                    sess.playing = False
                elif c == "speed":
                    sess.speed = float(min(max(float(m.get("value", 600)), 1.0), 50000.0))
                elif c == "reset":
                    sess.reset()
                    await ws.send_text(json.dumps(world_message(sess.env)))
                    await sess.broadcast(sess.last_frame)
                elif c == "abort":
                    sess.env.rover.abort("operator abort")
                    sess.pending.extend(sess.env.rover.pop_events())
                elif c == "override":
                    sess.override = bool(m.get("on"))
                    sess.pending.append({"t_s": sess.obs["t_s"], "kind": "event",
                                         "msg": "Operator override " + ("ENGAGED" if sess.override else "released")})
                elif c == "drive":
                    sess.manual = Action(v=float(m.get("v", 0)), omega=float(m.get("omega", 0)),
                                         mode="drive", phase="MANUAL", reason="Operator command")
                    sess.manual_at = time.monotonic()
        except WebSocketDisconnect:
            pass
        finally:
            sess.clients.discard(ws)

    @app.get("/api/training")
    def training() -> dict[str, Any]:
        """Return the tail of the rover training log, if one exists."""
        rows: list[dict[str, Any]] = []
        if TRAIN_LOG.is_file():
            for line in TRAIN_LOG.read_text(encoding="utf-8").splitlines()[-TRAIN_LOG_MAX_ROWS:]:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a partially written last line is expected while training runs
        return {"path": "runs/rover/train_log.jsonl", "rows": rows}

    @app.get("/api/ghosts")
    def ghost_list() -> list[dict[str, Any]]:
        """List stored ghost files and assets."""
        return ghosts.list_files(gdir)

    @app.post("/api/ghosts/{name}")
    async def ghost_upload(name: str, request: Request) -> JSONResponse:
        """Validate and store an uploaded ghost file (raw request body). Malformed ghost files are rejected."""
        try:
            result = ghosts.save_file(gdir, name, await request.body())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result, status_code=200 if result["saved"] else 422)

    @app.get("/api/ghosts/{name}")
    def ghost_get(name: str) -> FileResponse:
        """Return one stored ghost file."""
        try:
            path = gdir / ghosts.safe_name(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="no such file")
        return FileResponse(path)

    @app.websocket("/ws/ingest")
    async def ws_ingest(ws: WebSocket) -> None:
        """Accept ``world`` / ``frame`` / ``models`` messages from an external producer and relay them to the UIs.

        While a producer is connected the built-in simulator pauses; when it disconnects the simulator restarts.
        """
        await ws.accept()
        if sess.ingest is not None:
            await ws.send_json({"type": "error", "msg": "a telemetry producer is already connected"})
            await ws.close()
            return
        sess.ingest = ws
        sess.ingest_world = None
        sess.ingest_frame = None
        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type")
                if kind == "world":
                    sess.ingest_world = msg
                    await sess.broadcast(msg)
                elif kind == "frame":
                    sess.ingest_frame = msg
                    await sess.broadcast(msg)
                elif kind == "models":
                    sess.update_models(list(msg.get("models", [])))
                    await sess.broadcast(sess.models_message())
        except WebSocketDisconnect:
            pass
        finally:
            sess.ingest = None
            sess.ingest_world = None
            sess.ingest_frame = None
            sess.reset()
            await sess.broadcast(world_message(sess.env))
            await sess.broadcast(sess.last_frame)

    @app.websocket("/ws/agent")
    async def ws_agent(ws: WebSocket) -> None:
        await ws.accept()
        if sess.agent is not None:
            await ws.send_json({"type": "error", "msg": "an agent is already connected"})
            await ws.close()
            return
        sess.agent = ws
        sess.update_models([{"id": "rover", "status": "attached"}])
        await sess.broadcast(sess.models_message())
        while not sess.agent_q.empty():
            sess.agent_q.get_nowait()
        await ws.send_json({
            "type": "hello", "protocol": PROTOCOL_VERSION, "decision_dt_s": sess.env.cfg.decision_dt_s,
            "action_schema": {"v": "0..1 forward speed fraction", "omega": "-1..1 turn (+ clockwise)",
                              "mode": "drive | hold | sleep | drill", "phase": "short label", "reason": "facts only"},
            "world_url": "/api/world", "agent_timeout_s": AGENT_TIMEOUT_S,
        })
        sess.pending.append({"t_s": sess.obs["t_s"], "kind": "agent", "msg": "AI agent connected: taking control"})
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "models":
                    sess.update_models(list(msg.get("models", [])))
                    await sess.broadcast(sess.models_message())
                else:
                    await sess.agent_q.put(msg)
        except WebSocketDisconnect:
            pass
        finally:
            sess.agent = None
            sess.update_models([{"id": "rover", "status": "fallback"}])
            await sess.broadcast(sess.models_message())
            sess.pending.append({"t_s": sess.obs["t_s"], "kind": "agent", "msg": "AI agent disconnected: baseline policy resumes"})

    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
    return app


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8600)
    ap.add_argument("--policy", default=None, help="module:Class of an in-process Policy")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--ghost-dir", default=None, help="folder for uploaded ghost files (default runs/ghosts)")
    a = ap.parse_args()
    uvicorn.run(create_app(a.policy, a.seed, not a.no_record, Path(a.ghost_dir) if a.ghost_dir else None), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
