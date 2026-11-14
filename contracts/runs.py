"""Swarm run contracts: runs/<run>/

  generation_XXX.json  — one per generation (brain window reads these)
  champion_XXX.json    — best mission of a generation, re-flown in Basilisk (KAN-34 -> KAN-43)
  telemetry_XXX.csv    — per-timestep flight log (mission-control window reads these)

XXX is a zero-padded 3-digit generation number (use gen_name()).
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from contracts.provenance import Meta

# Failure reasons — shared vocabulary for the failure heatmap and decision log.
FAILURE_REASONS = (
    "ok",
    "hard_vertical",      # vertical speed over limit at touchdown
    "hard_horizontal",    # horizontal speed over limit
    "steep_slope",        # local slope over limit
    "hazard_cell",        # landed on a hazard cell
    "out_of_fuel",
    "timeout",            # still flying at max_time
    "out_of_bounds",      # left the tile
    "night_death",        # surface phase: battery empty during night
    "no_comms",           # surface phase: never reached Earth
)


def gen_name(prefix: str, gen: int, ext: str) -> str:
    return f"{prefix}_{gen:03d}.{ext}"


class _M(BaseModel):
    model_config = ConfigDict(extra="allow")


class FailureCount(_M):
    reason: str
    count: int


class GenerationLog(_M):
    run: str
    generation: int = Field(ge=0)
    population: int
    best_score: float
    mean_score: float
    success_rate: float = Field(ge=0, le=1)
    classic_success_rate: float | None = Field(default=None, description="baseline on same missions")
    exam_success_rate: float | None = None
    failures: list[FailureCount] = Field(default_factory=list)
    champion_id: str | None = None
    champion_genome: dict | None = None
    strategy: dict = Field(default_factory=dict, description="evolution params used (Dream-RSI layer)")
    wall_time_s: float | None = None
    meta: Meta


class MissionGenes(_M):
    site: str
    target_x_m: float
    target_y_m: float
    landing_time_utc: str | None = None
    battery_wh: float | None = None
    heater_w: float | None = None


class ControlStep(_M):
    t_s: float
    thrust_n: list[float] = Field(min_length=3, max_length=3, description="thrust vector, tile ENU, N")


class Champion(_M):
    run: str
    generation: int
    champion_id: str
    score: float
    genes: MissionGenes
    initial_state: dict = Field(description="pos_m [3], vel_m_s [3], mass_kg")
    controls: list[ControlStep]
    outcome: str
    meta: Meta


TELEMETRY_COLUMNS = (
    "t_s", "phase", "x_m", "y_m", "alt_m", "vx_m_s", "vy_m_s", "vz_m_s",
    "mass_kg", "fuel_kg", "thrust_n", "engines_ok", "battery_wh", "solar_w",
    "earth_visible", "decision",
)


def write_json(model: BaseModel, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return p


def read_generation(path: str | Path) -> GenerationLog:
    return GenerationLog.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def read_champion(path: str | Path) -> Champion:
    return Champion.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def write_telemetry(rows: Iterable[dict], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TELEMETRY_COLUMNS, extrasaction="raise")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in TELEMETRY_COLUMNS})
    return p


def read_telemetry(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if tuple(r.fieldnames or ()) != TELEMETRY_COLUMNS:
            raise ValueError(f"telemetry columns {r.fieldnames} != {TELEMETRY_COLUMNS}")
        return list(r)
