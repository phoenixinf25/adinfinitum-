"""Where things live. Override with env vars on the 4090 (see docs/plan/02_4090_SETUP_AND_PENDRIVE.md).

ADI_DATA  default: <repo>/data      (4090: ~/adi-data)
ADI_RUNS  default: <repo>/runs      (4090: ~/adi-runs)
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    return Path(os.environ.get("ADI_DATA", repo_root() / "data")).expanduser()


def runs_root() -> Path:
    return Path(os.environ.get("ADI_RUNS", repo_root() / "runs")).expanduser()


def tile_path(region: str) -> Path:
    return data_root() / "tiles" / f"{region}.npz"


def light_path(region: str, date: str) -> Path:
    return data_root() / "light" / f"{region}_{date}.npz"


def points_path(region: str, date: str) -> Path:
    return data_root() / "light" / f"{region}_{date}_points.npz"


def model_path(name: str) -> Path:
    """Trained checkpoints live in <data>/models/ (never in git)."""
    return data_root() / "models" / f"{name}.pt"


def run_dir(run: str) -> Path:
    return runs_root() / run


def sites_path() -> Path:
    return repo_root() / "sites" / "sites.json"


def mission_config_path() -> Path:
    return repo_root() / "config" / "mission.yaml"
