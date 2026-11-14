#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Lunar surface world: terrain tile, ice-evidence layers, Sun and Earth visibility.

Coordinates use the tile frame: ``x`` east and ``y`` north in metres from the
tile centre, row 0 of every raster is the northern edge. Azimuths are measured
clockwise from grid ``+y``.

Provenance (see ``data/ice/README.md``): the bundled demo tiles are
**GENERATED** terrain and the ice layers are **MODELLED** evidence. They are
never observations, and every consumer must keep those labels visible.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from scipy.ndimage import distance_transform_edt, map_coordinates

from lunar_ops.config import MissionConfig
from lunar_ops.demo_tile import REGION, make_rover_tile

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_tools.ice_layers import compute_ice_layers, load_tile  # noqa: E402


class World:
    """Terrain, evidence layers and illumination for one region.

    :param cfg: mission configuration.
    :param seed: seed used to pick candidate sites and the landing point.
    """

    def __init__(self, cfg: MissionConfig | None = None, seed: int = 0) -> None:
        self.cfg = cfg or MissionConfig()
        self.region = self.cfg.region
        tile_file = REPO_ROOT / "data" / "tiles" / f"{self.region}.npz"
        if self.region != REGION and not tile_file.exists():
            print(f"[lunar_ops] tile {tile_file.name} not found: using the generated '{REGION}' tile")
            self.region = REGION
        if self.region == REGION:
            tile = make_rover_tile()
        else:
            tile = load_tile(tile_file)
        self.real = self.region != REGION and self.region.startswith("lola5m_")
        self.context: dict[str, Any] | None = None
        site_key = self.region.replace("lola5m_", "")
        photo_dir = REPO_ROOT / "lunar_ops" / "ui" / "assets" / site_key
        self.photo: dict[str, str] | None = None
        if self.real and (photo_dir / "photo_1m.jpg").exists():
            self.photo = {"tile": f"assets/{site_key}/photo_1m.jpg",
                          "context": f"assets/{site_key}/photo_ctx_2m.jpg" if (photo_dir / "photo_ctx_2m.jpg").exists() else "",
                          "provenance": "LROC NAC controlled south-pole average mosaic, 1 m/px (observed; averaged "
                                        "lighting), Archinal et al. 2023"}
        if self.real:
            with np.load(tile_file) as z:
                if "context_height" in z:
                    self.context = {"height": z["context_height"].astype(np.float32), "mpp": float(z["context_mpp"]),
                                    "offset_m": [float(v) for v in z["context_offset_m"]]}
        self.site: dict[str, float] = {"lat_deg": float(tile["center_lat_deg"]), "lon_deg": float(tile["center_lon_deg"])}
        # No PSR polygon CSV is passed: the PSR mask then comes from the tile itself.
        layers = compute_ice_layers(self.region, tile, csv_psr_path=None)

        self.height: np.ndarray = tile["height"].astype(np.float32)
        self.slope: np.ndarray = tile["slope"].astype(np.float32)
        self.hazard: np.ndarray = tile["hazard"].astype(np.float32)
        self.mpp: float = float(tile["meters_per_pixel"])  # [m/px]
        self.rows, self.cols = self.height.shape
        self.half_x: float = (self.cols - 1) / 2.0 * self.mpp  # [m]
        self.half_y: float = (self.rows - 1) / 2.0 * self.mpp  # [m]

        self.psr: np.ndarray = layers["psr"].astype(bool)
        self.cold_trap: np.ndarray = layers["cold_trap"].astype(bool)
        self.tmax: np.ndarray = layers["tmax"].astype(np.float32)
        self.ice_score: np.ndarray = layers["ice_score"].astype(np.float32)
        self.candidate_mask: np.ndarray = layers["candidate_targets"].astype(bool)

        self._horizons: np.ndarray | None = None
        self._lit_cache: dict[int, np.ndarray] = {}
        rng = np.random.default_rng(seed)
        self.targets: list[dict[str, Any]] = self._pick_targets(rng)
        self.start: dict[str, float] = self._pick_start(rng)

    # ------------------------------------------------------------------ geometry
    def to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """Convert tile metres to fractional (row, col)."""
        return (self.half_y - y) / self.mpp, (x + self.half_x) / self.mpp

    def to_xy(self, row: float, col: float) -> tuple[float, float]:
        """Convert fractional (row, col) to tile metres."""
        return col * self.mpp - self.half_x, self.half_y - row * self.mpp

    def inside(self, x: float, y: float) -> bool:
        """Return True if the point lies inside the tile."""
        return abs(x) <= self.half_x and abs(y) <= self.half_y

    def sample(self, field: np.ndarray, x: float, y: float) -> float:
        """Bilinear sample of a raster at tile metres (clamped at the edges)."""
        r, c = self.to_pixel(x, y)
        return float(map_coordinates(field.astype(np.float32), [[r], [c]], order=1, mode="nearest")[0])

    def psr_at(self, x: float, y: float) -> bool:
        """Return True if the nearest cell is a permanently shadowed region."""
        r, c = self.to_pixel(x, y)
        r = min(max(int(round(r)), 0), self.rows - 1)
        c = min(max(int(round(c)), 0), self.cols - 1)
        return bool(self.psr[r, c])

    # --------------------------------------------------------------- sun / earth
    def sun_azimuth_deg(self, t_s: float) -> float:
        """Sun azimuth [deg] at mission time ``t_s`` [s]."""
        sky = self.cfg.sky
        return (sky.sun_azimuth_start_deg + 360.0 * t_s / sky.synodic_period_s) % 360.0

    def sun_elevation_deg(self) -> float:
        """Sun elevation [deg] (constant in this simplified model)."""
        return self.cfg.sky.sun_elevation_deg

    def earth_elevation_deg(self, t_s: float) -> float:
        """Earth elevation [deg] above a flat horizon at mission time ``t_s`` [s]."""
        sky = self.cfg.sky
        return sky.earth_libration_amp_deg * math.sin(2.0 * math.pi * t_s / sky.earth_libration_period_s)

    @property
    def horizons(self) -> np.ndarray:
        """Horizon elevation [deg] per azimuth bin, shape (bins, rows, cols)."""
        if self._horizons is None:
            self._horizons = self._compute_horizons()
        return self._horizons

    def _compute_horizons(self) -> np.ndarray:
        sky = self.cfg.sky
        nbin = sky.horizon_bins
        rows, cols = np.indices(self.height.shape).astype(np.float32)
        eye = self.height + np.float32(self.cfg.rover.mast_height_m)
        distances = []
        d = self.mpp
        while d <= sky.horizon_range_m:
            distances.append(d)
            d *= 1.3
        out = np.full((nbin, self.rows, self.cols), -90.0, dtype=np.float32)
        for b in range(nbin):
            az = math.radians(b * 360.0 / nbin)
            dcol = math.sin(az) / self.mpp  # [px/m]
            drow = -math.cos(az) / self.mpp  # [px/m]
            best = out[b]
            for dist in distances:
                hs = map_coordinates(self.height, [rows + drow * dist, cols + dcol * dist],
                                     order=1, mode="nearest")
                ang = np.degrees(np.arctan2(hs - eye, dist)).astype(np.float32)
                np.maximum(best, ang, out=best)
        return out

    @property
    def illum_frac(self) -> np.ndarray:
        """Fraction of Sun azimuths (one lunar day) in which each cell is lit [-] (MODELLED)."""
        if getattr(self, "_illum", None) is None:
            self._illum = (self.horizons < self.sun_elevation_deg()).mean(axis=0).astype(np.float32)
        return self._illum

    def _horizon_field(self, az_deg: float) -> np.ndarray:
        nbin = self.cfg.sky.horizon_bins
        pos = (az_deg % 360.0) / 360.0 * nbin
        b0 = int(math.floor(pos)) % nbin
        b1 = (b0 + 1) % nbin
        w = pos - math.floor(pos)
        return (1.0 - w) * self.horizons[b0] + w * self.horizons[b1]

    def lit_map(self, t_s: float) -> np.ndarray:
        """Boolean map of cells where the Sun is above the local horizon."""
        az = self.sun_azimuth_deg(t_s)
        key = int(round(az * 2.0))  # half-degree cache key
        if key not in self._lit_cache:
            if len(self._lit_cache) > 64:
                self._lit_cache.clear()
            self._lit_cache[key] = self._horizon_field(az) < self.sun_elevation_deg()
        return self._lit_cache[key]

    def lit_at(self, x: float, y: float, t_s: float) -> bool:
        """Return True if the Sun is visible at tile position (x, y)."""
        if not self.inside(x, y):
            return False
        r, c = self.to_pixel(x, y)
        r = min(max(int(round(r)), 0), self.rows - 1)
        c = min(max(int(round(c)), 0), self.cols - 1)
        return bool(self.lit_map(t_s)[r, c])

    def earth_visible_at(self, x: float, y: float, t_s: float) -> bool:
        """Return True if Earth is above the local horizon at (x, y)."""
        if not self.inside(x, y):
            return False
        r, c = self.to_pixel(x, y)
        r = min(max(int(round(r)), 0), self.rows - 1)
        c = min(max(int(round(c)), 0), self.cols - 1)
        hor = self._horizon_field(self.cfg.sky.earth_azimuth_deg)[r, c]
        return bool(self.earth_elevation_deg(t_s) > hor)

    # ------------------------------------------------------------------- planning
    def patch(self, x: float, y: float, t_s: float) -> dict[str, Any]:
        """Return an north-up observation patch centred on (x, y)."""
        n = self.cfg.patch_size
        sp = self.cfg.patch_spacing_m
        offs = (np.arange(n) - (n - 1) / 2.0) * sp
        xs = x + offs[None, :] * np.ones((n, 1))
        ys = y - offs[:, None] * np.ones((1, n))  # row 0 is north
        rr = (self.half_y - ys) / self.mpp
        cc = (xs + self.half_x) / self.mpp

        def grab(field: np.ndarray) -> list[list[float]]:
            v = map_coordinates(field.astype(np.float32), [rr, cc], order=1, mode="nearest")
            return np.round(v, 3).tolist()

        lit = self.lit_map(t_s)
        ri = np.clip(np.rint(rr).astype(int), 0, self.rows - 1)
        ci = np.clip(np.rint(cc).astype(int), 0, self.cols - 1)
        h0 = self.sample(self.height, x, y)
        return {
            "size": n,
            "spacing_m": sp,
            "height_rel_m": (np.array(grab(self.height)) - h0).round(2).tolist(),
            "slope_deg": grab(self.slope),
            "hazard": grab(self.hazard),
            "ice_score": grab(self.ice_score),
            "lit": lit[ri, ci].astype(int).tolist(),
            "psr": self.psr[ri, ci].astype(int).tolist(),
        }

    def prior(self) -> dict[str, Any]:
        """Orbital-map prior given to planners (arrays are views, do not modify)."""
        return {
            "mpp": self.mpp,
            "height": self.height,
            "slope": self.slope,
            "hazard": self.hazard,
            "psr": self.psr,
            "ice_score": self.ice_score,
            "half_x": self.half_x,
            "half_y": self.half_y,
            "targets": self.targets,
            "start": self.start,
            "illum_frac": self.illum_frac,
        }

    # ------------------------------------------------------------ site selection
    def _pick_targets(self, rng: np.random.Generator) -> list[dict[str, Any]]:
        rr, cc = np.nonzero(self.candidate_mask)
        if len(rr) == 0:
            return []
        depth_map = distance_transform_edt(self.psr) * self.mpp  # [m] distance inside the PSR edge
        scores = self.ice_score[rr, cc]
        depth = depth_map[rr, cc]
        order = np.lexsort((rng.random(len(rr)), -np.round(scores, 2)))
        shallow_limit = 120.0  # [m] sites shallower than this are cheap to reach
        pools = [
            [i for i in order if depth[i] <= shallow_limit],
            [i for i in order if depth[i] > shallow_limit],
        ]
        spacing = self.cfg.min_target_spacing_m
        chosen: list[tuple[float, float, float, float]] = []
        turn = 0
        while len(chosen) < self.cfg.n_targets and (pools[0] or pools[1]):
            pool = pools[turn % 2] or pools[(turn + 1) % 2]
            turn += 1
            while pool:
                i = pool.pop(0)
                x, y = self.to_xy(float(rr[i]), float(cc[i]))
                if all(math.hypot(x - cx, y - cy) >= spacing for cx, cy, _, _ in chosen):
                    chosen.append((x, y, float(scores[i]), float(depth[i])))
                    break
        return [
            {"id": f"T{i + 1}", "x_m": round(x, 2), "y_m": round(y, 2),
             "ice_score": round(s, 3), "depth_m": round(d, 1)}
            for i, (x, y, s, d) in enumerate(chosen)
        ]

    def _pick_start(self, rng: np.random.Generator) -> dict[str, float]:
        ok = (~self.psr) & (self.slope < 10.0) & (self.hazard < 0.3)  # landing-safe ground
        # Survivable ground: Sun visible at touchdown and for most of the lunar day (the Navigator's question).
        frac = self.illum_frac
        bright = ok & self.lit_map(0.0) & (frac >= max(0.5, float(np.percentile(frac[ok], 75)) if ok.any() else 0.5))
        if bright.any():
            ok = bright
        margin = int(100.0 / self.mpp)  # [px] keep the landing point 100 m inside the tile
        ok[:margin, :] = ok[-margin:, :] = False
        ok[:, :margin] = ok[:, -margin:] = False
        rr, cc = np.nonzero(ok)
        if len(rr) == 0 or not self.targets:
            return {"x_m": 0.0, "y_m": 0.0, "heading_deg": 0.0}
        xs = cc * self.mpp - self.half_x
        ys = self.half_y - rr * self.mpp
        tx = np.array([t["x_m"] for t in self.targets])
        ty = np.array([t["y_m"] for t in self.targets])
        dmin = np.hypot(xs[:, None] - tx[None, :], ys[:, None] - ty[None, :]).min(axis=1)
        order = np.argsort(dmin)[:40]  # landing cells closest to any site
        i = int(rng.choice(order))
        return {"x_m": round(float(xs[i]), 2), "y_m": round(float(ys[i]), 2), "heading_deg": 0.0}
