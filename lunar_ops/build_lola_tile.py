#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Build a rover-scale tile from real NASA LOLA 5 m terrain (observed data).

Input is a band of rows of ``<Site>_final_adj_5mpp_surf.tif`` (uncompressed
float32 GeoTIFF from https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/, Barker et al.
2021). Rows are stored contiguously, so a row band can be fetched with HTTP
range requests; see ``fetch_band`` usage in the project notes.

Outputs ``data/tiles/lola5m_<site>.npz`` in the standard tile format:

* ``height``      OBSERVED: LOLA surface height [m] (empty pixels are interpolated by LOLA)
* ``slope``       DERIVED from the height by finite differences [deg]
* ``psr_mask``    MODELLED: cells whose horizon is above the Sun's highest elevation in
                  every azimuth, computed from this DEM only (not NASA's LPSR polygons)
* ``hazard``      MODELLED from the slope

The 512 x 512 crop is chosen where the most shadowed ground is reachable from
gentle sunlit terrain over slopes the rover can drive.

Usage::

    python -m lunar_ops.build_lola_tile --band-dir DIR --header Site04_surf.tif
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path

import numpy as np
from scipy.ndimage import label, map_coordinates

SITE_COLS = 3200  # [px] width of the GeoTIFF
SITE_ROWS = 3200  # [px] height of the GeoTIFF
WINDOW = 1024  # [px] central analysis window
CROP = 512  # [px] output tile width and height (2.56 km at 5 m/px)
MPP = 5.0  # [m/px] LOLA product resolution
SUN_MAX_ELEV_DEG = 1.54 + 0.27  # [deg] maximum solar obliquity plus the solar disc radius
DRIVE_SLOPE_DEG = 18.0  # [deg] selection margin below the rover limit of 20 deg
R_MOON_M = 1737400.0  # [m]


def read_geo(header_file: Path) -> tuple[float, float, float]:
    """Return (tie point x, tie point y, pixel size) [m] from the GeoTIFF tags."""
    d = header_file.read_bytes()[:200000]
    ifd = struct.unpack("<I", d[4:8])[0]
    n = struct.unpack("<H", d[ifd:ifd + 2])[0]
    tags = {}
    for i in range(n):
        e = d[ifd + 2 + 12 * i: ifd + 14 + 12 * i]
        tag, typ, cnt = struct.unpack("<HHI", e[:8])
        if typ == 12 and tag in (33550, 33922):
            off = struct.unpack("<I", e[8:12])[0]
            tags[tag] = struct.unpack("<" + "d" * cnt, d[off: off + 8 * cnt])
    scale, tie = tags[33550], tags[33922]
    return tie[3], tie[4], scale[0]


def horizons(h: np.ndarray, spacing: float, n_az: int = 48, max_range: float = 3000.0) -> np.ndarray:
    """Minimum horizon elevation [deg] over all azimuths for every cell of ``h``."""
    rows, cols = np.indices(h.shape).astype(np.float32)
    dists = []
    d = spacing
    while d <= max_range:
        dists.append(d)
        d *= 1.3
    hmin = np.full(h.shape, 90.0, dtype=np.float32)
    for b in range(n_az):
        az = 2.0 * math.pi * b / n_az
        dcol, drow = math.sin(az) / spacing, -math.cos(az) / spacing
        best = np.full(h.shape, -90.0, dtype=np.float32)
        for dist in dists:
            hs = map_coordinates(h, [rows + drow * dist, cols + dcol * dist], order=1, mode="nearest")
            np.maximum(best, np.degrees(np.arctan2(hs - h, dist)).astype(np.float32), out=best)
        np.minimum(hmin, best, out=hmin)
    return hmin


def build(band_dir: Path, header: Path, out: Path, site: str = "Site04") -> dict:
    """Assemble the window, derive slope and PSR, choose the crop and write the tile."""
    prefix = "band_" if site == "Site04" else f"band_{site}_"
    raw = b"".join(p.read_bytes() for p in sorted(band_dir.glob(f"{prefix}[0-9]*.bin"), key=lambda p: int(p.stem.split("_")[-1])))
    band = np.frombuffer(raw, dtype="<f4").reshape(-1, SITE_COLS)
    c0 = (SITE_COLS - WINDOW) // 2
    r0 = (SITE_ROWS - WINDOW) // 2
    h = band[:, c0:c0 + WINDOW].astype(np.float32)
    bad = ~np.isfinite(h) | (np.abs(h) > 1e5)
    if bad.any():
        h[bad] = np.median(h[~bad])
    print("window", h.shape, "height", float(h.min()), float(h.max()), "bad px", int(bad.sum()))

    gy, gx = np.gradient(h, MPP)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)

    h10 = h.reshape(WINDOW // 2, 2, WINDOW // 2, 2).mean(axis=(1, 3))
    hz = horizons(h10, 2 * MPP)
    psr10 = hz > SUN_MAX_ELEV_DEG
    psr = np.repeat(np.repeat(psr10, 2, axis=0), 2, axis=1)
    print("PSR fraction of window", float(psr.mean()))

    free = slope < DRIVE_SLOPE_DEG
    lab, _ = label(free)
    best, best_score = (0, 0), -1.0
    for r in range(0, WINDOW - CROP + 1, 32):
        for c in range(0, WINDOW - CROP + 1, 32):
            sl = np.s_[r:r + CROP, c:c + CROP]
            L, P = lab[sl], psr[sl]
            if P.mean() < 0.02:
                continue
            ids, counts = np.unique(L[(L > 0) & ~P], return_counts=True)
            big = ids[counts > 4000]  # components with a large sunlit drivable area
            reach = np.isin(L, big) & P
            score = min(reach.mean(), 0.12) + 0.1 * (1.0 - abs(float(P.mean()) - 0.12))
            if score > best_score:
                best, best_score = (r, c), score
    r, c = best
    print("crop origin", best, "score", round(best_score, 3))
    hh, ss, pp = h[r:r + CROP, c:c + CROP], slope[r:r + CROP, c:c + CROP], psr[r:r + CROP, c:c + CROP]

    tx, ty, px = read_geo(header)
    cx = tx + (c0 + c + CROP / 2.0) * px
    cy = ty - (r0 + r + CROP / 2.0) * px
    rho = math.hypot(cx, cy)
    lat = -90.0 + math.degrees(2.0 * math.atan(rho / (2.0 * R_MOON_M)))
    # LOLA PGDA south-polar grid: x = rho sin(lon), y = rho cos(lon). Verified: Site01 maps onto the published
    # Connecting Ridge coordinates (89.47 S, 137.4 W) and onto LROC mosaic tile P892S2250 (centre 225 E).
    lon = math.degrees(math.atan2(cx, cy))
    print("centre xy", cx, cy, "lat", lat, "lon", lon)

    region = f"lola5m_{site.lower()}"
    meta = {"region": region, "provenance": "observed (height); modelled (psr, hazard)",
            "source": f"NASA LRO LOLA 5 m south-pole DEM, {site}, PGDA (Barker et al. 2021)",
            "psr_method": "DEM horizon test, Sun max elevation %.2f deg, range 3 km; NASA LPSR polygons not used" % SUN_MAX_ELEV_DEG,
            "lat_lon_note": "x = rho sin(lon), y = rho cos(lon); checked against the published Connecting Ridge coordinates"}
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out, height=hh.astype(np.float32), slope=ss.astype(np.float32),
        hazard=np.clip((ss - 14.0) / 10.0, 0.0, 1.0).astype(np.float32),
        uncertainty=np.full(hh.shape, np.nan, dtype=np.float32), psr_mask=pp.astype(bool),
        region=np.array(region), meters_per_pixel=np.array(MPP, dtype=np.float32),
        center_lat_deg=np.array(lat, dtype=np.float32), center_lon_deg=np.array(lon, dtype=np.float32), meta=json.dumps(meta),
        # Surrounding landscape for display: the whole analysis window at 20 m/px, and where the crop sits in it.
        context_height=h.reshape(WINDOW // 4, 4, WINDOW // 4, 4).mean(axis=(1, 3)).astype(np.float32),
        context_mpp=np.array(4 * MPP, dtype=np.float32),
        context_offset_m=np.array([(WINDOW / 2 - (c + CROP / 2)) * MPP, -(WINDOW / 2 - (r + CROP / 2)) * MPP], dtype=np.float32))
    return {"psr_fraction_crop": float(pp.mean()), "lat": lat, "lon": lon, "bytes": out.stat().st_size}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--band-dir", required=True)
    ap.add_argument("--header", required=True)
    ap.add_argument("--site", default="Site04")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = Path(a.out or f"data/tiles/lola5m_{a.site.lower()}.npz")
    print(build(Path(a.band_dir), Path(a.header), out, a.site))
