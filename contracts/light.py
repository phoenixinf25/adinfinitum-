"""Light-field contract (v2): data/light/<region>_<date>.npz  and  <region>_<date>_points.npz

Decisions: docs/team/LIGHT_CONTRACT_V2.md. v1 files (no azimuth) still load.

Field file, same grid as the matching tile, T time samples:
  times_utc     [T]        ISO-8601 strings (UTC)
  et_s          [T]        float64 SPICE ephemeris time (TDB seconds past J2000)
  sun_fraction  [T, H, W]  0..1 visible fraction of the solar disk (finite disk)
  sun_elev_deg  [T, H, W]  Sun elevation above the LOCAL horizon (terrain + curvature, no refraction)
  earth_elev_deg[T, H, W]  Earth-centre elevation above the local horizon
  sun_az_deg    [T]        OPTIONAL (v2). Compass azimuth at the tile centre: 0 = north, clockwise,
  earth_az_deg  [T]        0..360, in the tile ENU frame (row 0 = north). Per tile, not per cell: across a
                           2 km tile the azimuth differs by ~0.07 deg.

ELEVATION CONVENTION (decided 2026-11-14, answers a Navigator question): `sun_elev_deg` / `earth_elev_deg` are measured
from the TERRAIN HORIZON, not from the horizontal plane: elev = geometric elevation of the body centre - horizon elevation
at that azimuth (terrain + curvature, no refraction). So elev > 0 <=> the body centre is above the skyline (that is what
earth_visible() and the Earth-link rule rely on). To DRAW the body use the absolute elevation
elev + horizon_elev_deg[k, round(az) % 360]  (PointSeries.absolute_elev_deg()). "Sun up" for planning = sun_fraction > 0
(finite disk: the centre can be below the skyline while part of the disk is still visible).

Time axis: `date` = window start, UTC, YYYY-MM-DD (00:00:00Z), NOT a lunar-day id. Standard cadence 1 h and
one synodic month = 709 samples (708 h, both ends inclusive); see is_standard_axis().

Point series (small file for the Navigator and Vizard), one candidate cell + up to 8 neighbours:
  cells [K,2] (row, col), K <= 9 · times_utc [T] · et_s [T] · sun_fraction/sun_elev_deg/earth_elev_deg [T,K]
  sun_az_deg, earth_az_deg [T] · horizon_elev_deg [K,360] (index = azimuth degree, 0 = north, clockwise)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from contracts.provenance import Meta

UNITS = {"sun_fraction": "fraction 0..1", "sun_elev_deg": "deg", "earth_elev_deg": "deg",
         "sun_az_deg": "deg, compass, clockwise from north", "earth_az_deg": "deg, compass, clockwise from north",
         "horizon_elev_deg": "deg above the local horizontal, index = azimuth degree",
         "et_s": "s TDB past J2000", "times_utc": "ISO-8601 UTC"}

SYNODIC_SAMPLES = 709     # 708 h at 1 h cadence, both ends inclusive (one synodic month, 29.5 d)
CADENCE_S = 3600.0
MAX_POINT_CELLS = 9       # candidate cell + 8 neighbours
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_standard_axis(et_s: np.ndarray, tol_s: float = 1.0) -> bool:
    """True for the agreed window: 709 samples, 1 h apart."""
    et = np.asarray(et_s, dtype=np.float64)
    return et.shape == (SYNODIC_SAMPLES,) and bool(np.allclose(np.diff(et), CADENCE_S, atol=tol_s))


def _check_az(name: str, a: np.ndarray, t: int) -> None:
    if a.shape != (t,):
        raise ValueError(f"{name} must have shape [T]")
    if not np.all(np.isfinite(a)) or np.any((a < 0) | (a > 360)):
        raise ValueError(f"{name} must be finite and in 0..360 (compass degrees)")


def _check_date(date: str) -> None:
    if not _DATE.match(date):
        raise ValueError(f"date must be the window start as YYYY-MM-DD, got {date!r}")


@dataclass
class LightField:
    region: str
    date: str
    times_utc: list[str]
    et_s: np.ndarray
    sun_fraction: np.ndarray
    sun_elev_deg: np.ndarray
    earth_elev_deg: np.ndarray
    meta: Meta
    sun_az_deg: np.ndarray | None = None      # v2, optional [T]
    earth_az_deg: np.ndarray | None = None    # v2, optional [T]

    def validate(self) -> None:
        _check_date(self.date)
        t = len(self.times_utc)
        if self.et_s.shape != (t,):
            raise ValueError("et_s must have shape [T]")
        if self.sun_fraction.ndim != 3 or self.sun_fraction.shape[0] != t:
            raise ValueError("sun_fraction must be [T, H, W]")
        for name in ("sun_elev_deg", "earth_elev_deg"):
            if getattr(self, name).shape != self.sun_fraction.shape:
                raise ValueError(f"{name} shape mismatch")
        if np.any((self.sun_fraction < 0) | (self.sun_fraction > 1)):
            raise ValueError("sun_fraction must be in [0, 1]")
        if np.any(np.diff(self.et_s) <= 0):
            raise ValueError("et_s must be strictly increasing")
        for name in ("sun_az_deg", "earth_az_deg"):
            a = getattr(self, name)
            if a is not None:
                _check_az(name, np.asarray(a), t)

    def earth_visible(self) -> np.ndarray:
        return self.earth_elev_deg > 0.0


def save_light(lf: LightField, path: str | Path) -> Path:
    lf.validate()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = lf.meta.model_copy(update={"units": {**UNITS, **lf.meta.units}})
    header = {"region": lf.region, "date": lf.date, "times_utc": lf.times_utc,
              "meta": json.loads(meta.model_dump_json())}
    arrays = {
        "et_s": lf.et_s.astype(np.float64),
        "sun_fraction": lf.sun_fraction.astype(np.float32),
        "sun_elev_deg": lf.sun_elev_deg.astype(np.float32),
        "earth_elev_deg": lf.earth_elev_deg.astype(np.float32),
    }
    for name in ("sun_az_deg", "earth_az_deg"):
        if getattr(lf, name) is not None:
            arrays[name] = np.asarray(getattr(lf, name)).astype(np.float32)
    np.savez_compressed(p, header=np.array(json.dumps(header)), **arrays)
    return p


def load_light(path: str | Path) -> LightField:
    with np.load(Path(path), allow_pickle=False) as z:
        h = json.loads(str(z["header"]))
        lf = LightField(region=h["region"], date=h["date"], times_utc=list(h["times_utc"]),
                        et_s=z["et_s"], sun_fraction=z["sun_fraction"],
                        sun_elev_deg=z["sun_elev_deg"], earth_elev_deg=z["earth_elev_deg"],
                        meta=Meta.model_validate(h["meta"]),
                        sun_az_deg=z["sun_az_deg"] if "sun_az_deg" in z.files else None,
                        earth_az_deg=z["earth_az_deg"] if "earth_az_deg" in z.files else None)
    lf.validate()
    return lf


@dataclass
class PointSeries:
    """data/light/<region>_<date>_points.npz — small per-site series for the Navigator + Vizard."""

    region: str
    date: str
    cells: np.ndarray             # [K, 2] int (row, col) on the matching tile; cells[0] = candidate cell
    times_utc: list[str]
    et_s: np.ndarray              # [T]
    sun_fraction: np.ndarray      # [T, K]
    sun_elev_deg: np.ndarray      # [T, K]
    earth_elev_deg: np.ndarray    # [T, K]
    sun_az_deg: np.ndarray        # [T]
    earth_az_deg: np.ndarray      # [T]
    horizon_elev_deg: np.ndarray  # [K, 360]
    meta: Meta

    def validate(self) -> None:
        _check_date(self.date)
        t = len(self.times_utc)
        k = self.cells.shape[0] if self.cells.ndim == 2 else -1
        if self.cells.ndim != 2 or self.cells.shape[1] != 2 or not 1 <= k <= MAX_POINT_CELLS:
            raise ValueError(f"cells must be [K,2] with 1 <= K <= {MAX_POINT_CELLS}")
        if not np.issubdtype(self.cells.dtype, np.integer) or np.any(self.cells < 0):
            raise ValueError("cells must be non-negative integer (row, col) indices")
        if self.et_s.shape != (t,) or np.any(np.diff(self.et_s) <= 0):
            raise ValueError("et_s must have shape [T] and be strictly increasing")
        for name in ("sun_fraction", "sun_elev_deg", "earth_elev_deg"):
            if getattr(self, name).shape != (t, k):
                raise ValueError(f"{name} must have shape [T, K] = {(t, k)}")
        if np.any((self.sun_fraction < 0) | (self.sun_fraction > 1)):
            raise ValueError("sun_fraction must be in [0, 1]")
        _check_az("sun_az_deg", self.sun_az_deg, t)
        _check_az("earth_az_deg", self.earth_az_deg, t)
        if self.horizon_elev_deg.shape != (k, 360):
            raise ValueError(f"horizon_elev_deg must have shape [K, 360] = {(k, 360)}")
        if not np.all(np.isfinite(self.horizon_elev_deg)) or np.any(np.abs(self.horizon_elev_deg) > 90):
            raise ValueError("horizon_elev_deg must be finite and within +-90 deg")

    def earth_visible(self) -> np.ndarray:
        return self.earth_elev_deg > 0.0

    def absolute_elev_deg(self, body: str) -> np.ndarray:
        """[T, K] elevation above the horizontal plane (for drawing): horizon-relative elev + skyline at the body's azimuth."""
        if body not in ("sun", "earth"):
            raise ValueError("body must be 'sun' or 'earth'")
        elev = self.sun_elev_deg if body == "sun" else self.earth_elev_deg
        az = self.sun_az_deg if body == "sun" else self.earth_az_deg
        idx = np.round(az).astype(int) % 360                      # [T]
        return elev + self.horizon_elev_deg[:, idx].T              # [K,T] -> [T,K]

    @classmethod
    def from_field(cls, lf: LightField, cells: np.ndarray, horizon_elev_deg: np.ndarray,
                   meta: Meta | None = None) -> PointSeries:
        """Cut the point series out of a full field (needs the v2 azimuths)."""
        if lf.sun_az_deg is None or lf.earth_az_deg is None:
            raise ValueError("this light field is v1 (no azimuth); cannot build a point series")
        cells = np.asarray(cells, dtype=np.int64)
        r, c = cells[:, 0], cells[:, 1]
        return cls(region=lf.region, date=lf.date, cells=cells, times_utc=list(lf.times_utc), et_s=lf.et_s,
                   sun_fraction=lf.sun_fraction[:, r, c], sun_elev_deg=lf.sun_elev_deg[:, r, c],
                   earth_elev_deg=lf.earth_elev_deg[:, r, c], sun_az_deg=lf.sun_az_deg,
                   earth_az_deg=lf.earth_az_deg, horizon_elev_deg=np.asarray(horizon_elev_deg),
                   meta=meta or lf.meta)


def save_points(ps: PointSeries, path: str | Path) -> Path:
    ps.validate()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = ps.meta.model_copy(update={"units": {**UNITS, **ps.meta.units}})
    header = {"region": ps.region, "date": ps.date, "times_utc": ps.times_utc,
              "meta": json.loads(meta.model_dump_json())}
    np.savez_compressed(
        p, header=np.array(json.dumps(header)), cells=ps.cells.astype(np.int32),
        et_s=ps.et_s.astype(np.float64), sun_fraction=ps.sun_fraction.astype(np.float32),
        sun_elev_deg=ps.sun_elev_deg.astype(np.float32), earth_elev_deg=ps.earth_elev_deg.astype(np.float32),
        sun_az_deg=ps.sun_az_deg.astype(np.float32), earth_az_deg=ps.earth_az_deg.astype(np.float32),
        horizon_elev_deg=ps.horizon_elev_deg.astype(np.float32),
    )
    return p


def load_points(path: str | Path) -> PointSeries:
    with np.load(Path(path), allow_pickle=False) as z:
        h = json.loads(str(z["header"]))
        ps = PointSeries(region=h["region"], date=h["date"], cells=z["cells"], times_utc=list(h["times_utc"]),
                         et_s=z["et_s"], sun_fraction=z["sun_fraction"], sun_elev_deg=z["sun_elev_deg"],
                         earth_elev_deg=z["earth_elev_deg"], sun_az_deg=z["sun_az_deg"],
                         earth_az_deg=z["earth_az_deg"], horizon_elev_deg=z["horizon_elev_deg"],
                         meta=Meta.model_validate(h["meta"]))
    ps.validate()
    return ps
