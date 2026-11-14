"""Navigator data layer: finds the light files and site info. Reads only files in the contracts' formats."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from contracts.light import PointSeries, load_points
from contracts.paths import data_root, sites_path, tile_path
from contracts.tiles import Tile, load_tile

_NAME = re.compile(r"^(?P<region>.+)_(?P<date>\d{4}-\d{2}-\d{2})_points\.npz$")
_PAREN = re.compile(r"\(([^)]+)\)")


@dataclass(frozen=True)
class Entry:
    region: str
    date: str
    path: Path

    @property
    def key(self) -> str:
        return f"{self.region} | {self.date}"


def list_entries(light_dir: str | Path | None = None) -> list[Entry]:
    """Every <region>_<date>_points.npz found, sorted by region then date."""
    d = Path(light_dir) if light_dir else data_root() / "light"
    out = []
    for p in sorted(d.glob("*_points.npz")) if d.exists() else []:
        m = _NAME.match(p.name)
        if m:
            out.append(Entry(m["region"], m["date"], p))
    return out


def load_entry(entry: Entry) -> PointSeries:
    return load_points(entry.path)


def load_tile_or_none(region: str) -> Tile | None:
    p = tile_path(region)
    return load_tile(p) if p.exists() else None


def site_names() -> dict[str, str]:
    """region -> display name from sites/sites.json when it exists (matches `region` or `id`)."""
    p = sites_path()
    if not p.exists():
        return {}
    names = {}
    for s in json.loads(p.read_text(encoding="utf-8")).get("sites", []):
        names[s.get("region") or s["id"]] = s["name"]
        names.setdefault(s["id"], s["name"])
    return names


def display_name(region: str, tile: Tile | None = None, names: dict[str, str] | None = None) -> str:
    names = site_names() if names is None else names
    if region in names:
        return names[region]
    if tile is not None:
        m = _PAREN.search(tile.meta.source)
        site = tile.extra.get("site")
        if m:
            return f"{m.group(1)} ({site})" if site else m.group(1)
    return region


def latlon(tile: Tile | None) -> str:
    if tile is None:
        return "location unknown"
    return f"{abs(tile.center_lat_deg):.2f}°{'S' if tile.center_lat_deg < 0 else 'N'}, {tile.center_lon_deg:.1f}°E"
