"""Terrain tile contract: data/tiles/<region>.npz

Grid convention (all arrays shape [H, W], float32 unless noted):
  row 0 = northmost (+y), col 0 = westmost (-x); local ENU-like metres in a polar
  stereographic projection centred on the region (see meta.projection).
  x = (col - (W-1)/2) * mpp,   y = ((H-1)/2 - row) * mpp   (tile centre = origin)

Arrays:
  height       m      LOLA elevation relative to 1737.4 km sphere
  slope        deg    local slope
  hazard       0..1   probability the cell is unsafe to land on
  uncertainty  m      1-sigma height uncertainty (LDEM_ERR or model)
  psr_mask     bool   permanently shadowed region
  real_mask    bool   (optional) True where laser spots exist (not interpolated)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from contracts.provenance import Meta, Provenance

REQUIRED = ("height", "slope", "hazard", "uncertainty", "psr_mask")
OPTIONAL = ("real_mask",)
UNITS = {"height": "m", "slope": "deg", "hazard": "probability 0..1",
         "uncertainty": "m (1-sigma)", "psr_mask": "bool", "real_mask": "bool"}


@dataclass
class Tile:
    region: str
    meters_per_pixel: float
    height: np.ndarray
    slope: np.ndarray
    hazard: np.ndarray
    uncertainty: np.ndarray
    psr_mask: np.ndarray
    meta: Meta
    center_lat_deg: float = -90.0
    center_lon_deg: float = 0.0
    real_mask: np.ndarray | None = None
    extra: dict = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return self.height.shape  # type: ignore[return-value]

    def validate(self) -> None:
        h, w = self.height.shape
        if h < 2 or w < 2:
            raise ValueError("tile must be at least 2x2")
        for name in REQUIRED + OPTIONAL:
            arr = getattr(self, name)
            if arr is None:
                continue
            if arr.shape != (h, w):
                raise ValueError(f"{name} has shape {arr.shape}, expected {(h, w)}")
            if name not in ("psr_mask", "real_mask") and not np.all(np.isfinite(arr)):
                raise ValueError(f"{name} contains NaN/inf")
        if self.meters_per_pixel <= 0:
            raise ValueError("meters_per_pixel must be > 0")
        if np.any((self.hazard < 0) | (self.hazard > 1)):
            raise ValueError("hazard must be in [0, 1]")
        if np.any((self.slope < 0) | (self.slope > 90)):
            raise ValueError("slope must be in [0, 90] deg")

    def xy_extent_m(self) -> tuple[float, float]:
        h, w = self.shape
        return (w - 1) * self.meters_per_pixel, (h - 1) * self.meters_per_pixel


def save_tile(tile: Tile, path: str | Path) -> Path:
    tile.validate()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = tile.meta.model_copy(update={"units": {**UNITS, **tile.meta.units}})
    header = {
        "region": tile.region,
        "meters_per_pixel": tile.meters_per_pixel,
        "center_lat_deg": tile.center_lat_deg,
        "center_lon_deg": tile.center_lon_deg,
        "meta": json.loads(meta.model_dump_json()),
        "extra": tile.extra,
    }
    arrays = {n: getattr(tile, n) for n in REQUIRED}
    arrays["height"] = arrays["height"].astype(np.float32)
    arrays["slope"] = arrays["slope"].astype(np.float32)
    arrays["hazard"] = arrays["hazard"].astype(np.float32)
    arrays["uncertainty"] = arrays["uncertainty"].astype(np.float32)
    arrays["psr_mask"] = arrays["psr_mask"].astype(bool)
    if tile.real_mask is not None:
        arrays["real_mask"] = tile.real_mask.astype(bool)
    np.savez_compressed(p, header=np.array(json.dumps(header)), **arrays)
    return p


def load_tile(path: str | Path) -> Tile:
    with np.load(Path(path), allow_pickle=True) as z:
        if "header" in z.files:
            header = json.loads(str(z["header"]))
            region = header["region"]
            mpp = float(header["meters_per_pixel"])
            center_lat = float(header.get("center_lat_deg", -90.0))
            center_lon = float(header.get("center_lon_deg", 0.0))
            meta = Meta.model_validate(header["meta"])
            extra = header.get("extra", {})
        else:
            region = str(z["region"]) if "region" in z.files else Path(path).stem
            mpp = float(z["meters_per_pixel"]) if "meters_per_pixel" in z.files else 5.0
            center_lat = float(z["center_lat_deg"]) if "center_lat_deg" in z.files else -90.0
            center_lon = float(z["center_lon_deg"]) if "center_lon_deg" in z.files else 0.0
            meta = Meta(provenance=Provenance.GENERATED, source=f"LOLA DEM {region}")
            extra = {}
        tile = Tile(
            region=region,
            meters_per_pixel=mpp,
            center_lat_deg=center_lat,
            center_lon_deg=center_lon,
            meta=meta,
            extra=extra,
            real_mask=z["real_mask"] if "real_mask" in z.files else None,
            **{n: z[n] for n in REQUIRED},
        )
    tile.validate()
    return tile


def slope_from_height(height: np.ndarray, mpp: float) -> np.ndarray:
    """Slope in degrees from a height grid (central differences)."""
    dzdy, dzdx = np.gradient(height.astype(np.float64), mpp)
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy))).astype(np.float32)


def hazard_from_slope(slope_deg: np.ndarray, limit_deg: float = 12.0) -> np.ndarray:
    """Physics backup hazard map: 1 where slope >= limit (KAN-25 backup)."""
    return (slope_deg >= limit_deg).astype(np.float32)


__all__ = [
    "Provenance",
    "Tile",
    "hazard_from_slope",
    "load_tile",
    "save_tile",
    "slope_from_height",
]
