"""Shared helpers for every Basilisk scenario in this folder.

Frames (keep them straight — most bugs come from mixing these up):
  N  Moon-centred inertial frame used by Basilisk (metres, m/s). In these starters the Moon
     is a non-rotating sphere at the origin; Arnav's terrain module adds the Moon-fixed frame.
  B  lander body frame. +z_B points "up" out of the top deck; engines push along +z_B.
  L  local frame at the landing target: east, north, up (metres from the target point).

All numbers come from config/mission.yaml via contracts.mission.load_mission().
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from contracts.mission import MissionConfig, load_mission
from contracts.paths import runs_root

R_MOON_M = 1737.4e3
R_MOON_KM = 1737.4
MU_MOON = 4.9048695e12  # m^3/s^2

try:
    from Basilisk.utilities import RigidBodyKinematics as rbk
    from Basilisk.utilities import SimulationBaseClass, macros, simIncludeGravBody
    HAS_BSK = True
except ImportError:
    HAS_BSK = False

    class _MacrosFallback:
        D2R = math.pi / 180.0
        R2D = 180.0 / math.pi
        NANO2SEC = 1e-9
        SEC2NANO = 1e9

        @staticmethod
        def sec2nano(s: float | int) -> int:
            return int(s * 1e9)

        @staticmethod
        def nano2sec(ns: float | int) -> float:
            return float(ns) * 1e-9

    macros = _MacrosFallback()

    class _RBKFallback:
        @staticmethod
        def C2MRP(C: np.ndarray) -> np.ndarray:
            C = np.asarray(C, float)
            tr = float(np.trace(C))
            val = 1.0 + tr
            if val > 1e-7:
                q0 = 0.5 * math.sqrt(val)
                q1 = (C[1, 2] - C[2, 1]) / (4.0 * q0)
                q2 = (C[2, 0] - C[0, 2]) / (4.0 * q0)
                q3 = (C[0, 1] - C[1, 0]) / (4.0 * q0)
            else:
                diag = [C[0, 0], C[1, 1], C[2, 2]]
                idx = int(np.argmax(diag))
                if idx == 0:
                    s = 2.0 * math.sqrt(max(1.0 + C[0, 0] - C[1, 1] - C[2, 2], 1e-9))
                    q0 = (C[1, 2] - C[2, 1]) / s
                    q1 = 0.25 * s
                    q2 = (C[0, 1] + C[1, 0]) / s
                    q3 = (C[0, 2] + C[2, 0]) / s
                elif idx == 1:
                    s = 2.0 * math.sqrt(max(1.0 + C[1, 1] - C[0, 0] - C[2, 2], 1e-9))
                    q0 = (C[2, 0] - C[0, 2]) / s
                    q1 = (C[0, 1] + C[1, 0]) / s
                    q2 = 0.25 * s
                    q3 = (C[1, 2] + C[2, 1]) / s
                else:
                    s = 2.0 * math.sqrt(max(1.0 + C[2, 2] - C[0, 0] - C[1, 1], 1e-9))
                    q0 = (C[0, 1] - C[1, 0]) / s
                    q1 = (C[0, 2] + C[2, 0]) / s
                    q2 = (C[1, 2] + C[2, 1]) / s
                    q3 = 0.25 * s
            if q0 < 0:
                q0, q1, q2, q3 = -q0, -q1, -q2, -q3
            denom = max(1.0 + q0, 1e-9)
            return np.array([q1 / denom, q2 / denom, q3 / denom], dtype=float)

        @staticmethod
        def MRP2C(sigma: np.ndarray) -> np.ndarray:
            s = np.asarray(sigma, float)
            s2 = float(np.dot(s, s))
            S = np.array([
                [0.0, -s[2], s[1]],
                [s[2], 0.0, -s[0]],
                [-s[1], s[0], 0.0]
            ])
            denom = (1.0 + s2) ** 2
            return np.eye(3) - (4.0 * (1.0 - s2) * S - 8.0 * (S @ S)) / denom

    rbk = _RBKFallback()

    class _GravMoon:
        mu = MU_MOON
        isCentralBody = True

    class _GravFactory:
        def __init__(self):
            self.moon = _GravMoon()

        def createMoon(self):
            return self.moon

        def addBodiesTo(self, sc):
            pass

    class _Task:
        def __init__(self, name: str, dt_ns: int):
            self.name = name
            self.dt_ns = dt_ns
            self.dt_s = dt_ns * 1e-9
            self.models: list[Any] = []

    class _Process:
        def __init__(self, name: str):
            self.name = name
            self.tasks: dict[str, _Task] = {}

        def addTask(self, task: _Task):
            self.tasks[task.name] = task

    class _SimBaseClass:
        def __init__(self):
            self.processes: dict[str, _Process] = {}
            self.models: list[tuple[str, Any]] = []
            self.sim_time_ns = 0
            self.stop_time_ns = 0

        def CreateNewProcess(self, name: str):
            proc = _Process(name)
            self.processes[name] = proc
            return proc

        def CreateNewTask(self, name: str, dt_ns: int):
            return _Task(name, dt_ns)

        def AddModelToTask(self, task_name: str, model: Any):
            self.models.append((task_name, model))

        def InitializeSimulation(self):
            self.sim_time_ns = 0
            for _, m in self.models:
                if hasattr(m, "Reset"):
                    m.Reset(0)

        def ConfigureStopTime(self, stop_time_ns: int):
            self.stop_time_ns = stop_time_ns

        def ExecuteSimulation(self):
            self.sim_time_ns = self.stop_time_ns

    class _SimIncludeGravBody:
        gravBodyFactory = _GravFactory

    class _SimulationBaseClassModule:
        SimBaseClass = _SimBaseClass

    simIncludeGravBody = _SimIncludeGravBody()
    SimulationBaseClass = _SimulationBaseClassModule()


def out_dir() -> Path:
    """runs/basilisk/ — every Basilisk output (pdi_state.json, telemetry CSV, Vizard files) goes here."""
    d = runs_root() / "basilisk"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_sim(tasks: dict[str, float]):
    """Create a simulation with one process and named tasks. tasks = {"dynTask": 0.05, ...} (seconds)."""
    sim = SimulationBaseClass.SimBaseClass()
    proc = sim.CreateNewProcess("mainProcess")
    for name, dt_s in tasks.items():
        proc.addTask(sim.CreateNewTask(name, macros.sec2nano(dt_s)))
    return sim


def add_moon_gravity(spacecraft_obj):
    """Point-mass Moon gravity at the origin. Returns (gravFactory, mu)."""
    grav = simIncludeGravBody.gravBodyFactory()
    moon = grav.createMoon()
    moon.isCentralBody = True
    grav.addBodiesTo(spacecraft_obj)
    return grav, moon.mu


def local_frame(target_up_N: np.ndarray) -> np.ndarray:
    """Rows = east, north, up unit vectors (in N) at the target. Not valid exactly at a pole."""
    up = target_up_N / np.linalg.norm(target_up_N)
    east = np.cross([0.0, 0.0, 1.0], up)
    east /= np.linalg.norm(east)
    north = np.cross(up, east)
    return np.vstack([east, north, up])


def dcm_with_z_along(z_N: np.ndarray, hint_N: np.ndarray | None = None) -> np.ndarray:
    """DCM [RN] whose third axis (z_R) points along z_N. Used to point the engines."""
    z = z_N / np.linalg.norm(z_N)
    hint = np.array([1.0, 0.0, 0.0]) if hint_N is None else hint_N
    if abs(np.dot(hint, z)) > 0.95:
        hint = np.array([0.0, 1.0, 0.0])
    x = np.cross(hint, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.vstack([x, y, z])


def mrp_with_z_along(z_N: np.ndarray, hint_N: np.ndarray | None = None) -> np.ndarray:
    return np.asarray(rbk.C2MRP(dcm_with_z_along(z_N, hint_N)))


def mission() -> MissionConfig:
    return load_mission()
