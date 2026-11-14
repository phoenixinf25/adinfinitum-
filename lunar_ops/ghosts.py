#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Ghost-run files: validation and safe storage.

A ghost file holds recorded, simulated attempts ("runs") of a rover or a lander. Mission control only replays what
the file contains; nothing is invented, tuned or repaired here. A file that does not match the format is rejected
with a list of what is wrong, so the producer can fix it.

Format (see ``lunar_ops/PROTOCOL.md``, section "Ghost files")::

    {"kind": "rover" | "lander", "region": "lola5m_site23", "frame": "tile ENU metres, origin = tile centre, z up",
     "dt_s": 3600.0, "terrain_obj": "<path>", "models": {"rover": "...", "lander": "..."},
     "runs": [{"id": "...", "policy": "...", "outcome": "...", "best": true, "fail_t_s": null,
               "t_s": [...], "xyz_m": [[x, y, z], ...], "heading_deg": [...]}]}
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

GHOST_DIR = Path(__file__).resolve().parents[1] / "runs" / "ghosts"
ALLOWED_SUFFIXES = {".json", ".obj", ".mtl", ".glb", ".png", ".jpg"}
MAX_FILE_BYTES = 50 * 1024 * 1024  # [B] largest accepted upload
MAX_RUN_SAMPLES = 2_000_000  # [-] most samples accepted in one run
KINDS = ("rover", "lander")
KNOWN_OUTCOMES = {
    "returned", "reached_ice_only", "died_battery", "blocked", "timeout",
    "ok", "hard_vertical", "hard_horizontal", "steep_slope", "hazard_cell", "out_of_fuel", "out_of_bounds",
}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,100}$")


def safe_name(name: str) -> str:
    """Return ``name`` if it is a plain, allowed file name, otherwise raise ``ValueError``.

    :param name: file name proposed by a client.
    :raises ValueError: if the name has path parts, odd characters or a disallowed suffix.
    """
    if not isinstance(name, str) or not _NAME_RE.match(name) or ".." in name:
        raise ValueError("file name must be 1-101 plain characters (letters, digits, _ . -) with no path")
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"file type not allowed; use one of {sorted(ALLOWED_SUFFIXES)}")
    return name


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_ghost(obj: Any) -> dict[str, Any]:
    """Check a parsed ghost file and summarise it.

    :param obj: parsed JSON value.
    :returns: ``{"ok", "errors", "warnings", "summary"}``. ``ok`` is true when there are no errors.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(obj, dict):
        return {"ok": False, "errors": ["top level must be an object"], "warnings": [], "summary": {}}
    if obj.get("kind") not in KINDS:
        errors.append(f"'kind' must be one of {list(KINDS)}")
    if not isinstance(obj.get("region"), str) or not obj.get("region"):
        errors.append("'region' must be a non-empty string")
    if not isinstance(obj.get("frame"), str):
        warnings.append("'frame' is missing; assuming tile ENU metres, origin = tile centre, z up")
    if not (_is_num(obj.get("dt_s")) and obj["dt_s"] > 0):
        errors.append("'dt_s' must be a positive number")
    runs = obj.get("runs")
    if not isinstance(runs, list) or not runs:
        errors.append("'runs' must be a non-empty list")
        runs = []
    seen: set[str] = set()
    outcomes: dict[str, int] = {}
    best_ids: list[str] = []
    duration = 0.0
    for i, r in enumerate(runs):
        tag = f"runs[{i}]"
        if not isinstance(r, dict):
            errors.append(f"{tag} must be an object")
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            errors.append(f"{tag}: 'id' must be a non-empty string")
            rid = f"#{i}"
        elif rid in seen:
            errors.append(f"{tag}: duplicate id '{rid}'")
        seen.add(rid)
        tag = f"run '{rid}'"
        for key in ("policy", "outcome"):
            if not isinstance(r.get(key), str) or not r[key]:
                errors.append(f"{tag}: '{key}' must be a non-empty string")
        outcome = r.get("outcome")
        if isinstance(outcome, str):
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if outcome not in KNOWN_OUTCOMES:
                warnings.append(f"{tag}: unknown outcome '{outcome}' (it will be drawn as a failure)")
        if not isinstance(r.get("best"), bool):
            errors.append(f"{tag}: 'best' must be true or false")
        elif r["best"]:
            best_ids.append(rid)
        fail = r.get("fail_t_s")
        if fail is not None and not _is_num(fail):
            errors.append(f"{tag}: 'fail_t_s' must be a number or null")
        t, xyz, hd = r.get("t_s"), r.get("xyz_m"), r.get("heading_deg")
        if not isinstance(t, list) or not t or not all(_is_num(v) for v in t):
            errors.append(f"{tag}: 't_s' must be a non-empty list of numbers")
            continue
        if len(t) > MAX_RUN_SAMPLES:
            errors.append(f"{tag}: more than {MAX_RUN_SAMPLES} samples")
            continue
        if any(b < a for a, b in zip(t, t[1:])):
            errors.append(f"{tag}: 't_s' must not decrease")
        if not isinstance(xyz, list) or len(xyz) != len(t) or not all(
                isinstance(p, list) and len(p) == 3 and all(_is_num(v) for v in p) for p in xyz):
            errors.append(f"{tag}: 'xyz_m' must be a list of [x, y, z] numbers, one per 't_s' entry")
        if hd is None:
            warnings.append(f"{tag}: 'heading_deg' is missing; vehicles will not be rotated")
        elif not isinstance(hd, list) or len(hd) != len(t) or not all(_is_num(v) for v in hd):
            errors.append(f"{tag}: 'heading_deg' must be one number per 't_s' entry")
        if _is_num(fail) and not (t[0] <= fail <= t[-1] + 1e-9):
            warnings.append(f"{tag}: 'fail_t_s' lies outside the recorded time range")
        duration = max(duration, float(t[-1]))
    if runs and len(best_ids) != 1:
        warnings.append(f"expected exactly one best run, found {len(best_ids)}")
    summary = {"kind": obj.get("kind"), "region": obj.get("region"), "n_runs": len(runs), "outcomes": outcomes,
               "best": best_ids[0] if len(best_ids) == 1 else None, "duration_s": duration}
    return {"ok": not errors, "errors": errors, "warnings": warnings, "summary": summary}


def save_file(directory: Path, name: str, data: bytes) -> dict[str, Any]:
    """Validate and store an uploaded file.

    JSON files must be valid ghost files. Other allowed files (models, textures) are stored as they are.

    :param directory: target folder (created if needed).
    :param name: plain file name, see :func:`safe_name`.
    :param data: file content.
    :returns: ``{"saved": bool, "name", "errors", "warnings", "summary"}``.
    :raises ValueError: if the name is not allowed or the file is too large.
    """
    name = safe_name(name)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("file is larger than 50 MB")
    result: dict[str, Any] = {"saved": False, "name": name, "errors": [], "warnings": [], "summary": {}}
    if name.lower().endswith(".json"):
        try:
            report = validate_ghost(json.loads(data.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            result["errors"] = [f"not valid JSON: {exc}"]
            return result
        result.update({k: report[k] for k in ("errors", "warnings", "summary")})
        if not report["ok"]:
            return result
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(data)
    result["saved"] = True
    return result


def list_files(directory: Path) -> list[dict[str, Any]]:
    """List stored files; ghost files include their summary.

    :param directory: folder to list (may not exist).
    """
    out: list[dict[str, Any]] = []
    if not directory.is_dir():
        return out
    for p in sorted(directory.iterdir()):
        if not p.is_file() or p.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        item: dict[str, Any] = {"name": p.name, "size": p.stat().st_size}
        if p.suffix.lower() == ".json":
            try:
                item["summary"] = validate_ghost(json.loads(p.read_text(encoding="utf-8")))["summary"]
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                item["summary"] = {}
        out.append(item)
    return out
