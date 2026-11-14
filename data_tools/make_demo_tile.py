"""
Terrain tile generator in the official tile format.
Generates polar-stereographic DEM tiles with slope, hazard, and basic PSR.

Usage:
    python data_tools/make_demo_tile.py --region demo_craters --size 400 --mpp 5.0
    python data_tools/make_demo_tile.py --region shackleton --size 500 --mpp 20.0
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np

def make_crater_tile(region: str = "demo_craters", size: int = 400, mpp: float = 5.0,
                     center_lat_deg: float = -89.9, center_lon_deg: float = 0.0,
                     seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    half = (size - 1) / 2.0 * mpp
    xs = np.linspace(-half, half, size)
    X, Y = np.meshgrid(xs, xs[::-1])  # row 0 = north (+y), col 0 = west (-x)

    # Base elevation undulations
    height = 0.015 * X - 0.01 * Y + 10.0 * np.sin(X / 400.0) * np.cos(Y / 500.0)

    # Primary deep crater feature (e.g. Shackleton-like or major impact structure)
    r_main = np.hypot(X - 30.0, Y + 60.0)
    rad_main = 0.35 * size * mpp
    depth_main = 0.28 * rad_main
    bowl_main = np.where(r_main < rad_main, -depth_main * (1.0 - (r_main / rad_main) ** 2), 0.0)
    rim_main = 0.16 * depth_main * np.exp(-((r_main - rad_main) / (0.22 * rad_main)) ** 2)
    height += (bowl_main + rim_main)

    # Populate secondary craters across the terrain
    n_craters = 45
    for _ in range(n_craters):
        cx, cy = rng.uniform(-half * 0.9, half * 0.9, 2)
        r = np.hypot(X - cx, Y - cy)
        rad = rng.uniform(15.0, 90.0)
        depth = rng.uniform(0.18, 0.25) * rad
        bowl = np.where(r < rad, -depth * (1.0 - (r / rad) ** 2), 0.0)
        rim = 0.14 * depth * np.exp(-((r - rad) / (0.25 * rad)) ** 2)
        height += (bowl + rim)

    # Slope in degrees from finite differences
    gy, gx = np.gradient(height, mpp)
    slope = np.rad2deg(np.arctan(np.hypot(gx, gy))).astype(np.float32)

    # Hazard probability: slopes > 15 deg are dangerous for lunar landing/driving
    hazard = np.clip((slope - 8.0) / 10.0, 0.0, 1.0).astype(np.float32)
    uncertainty = np.full_like(height, 0.75, dtype=np.float32)

    # Baseline PSR mask: deep depressions shadowed by steep rims in polar geometry
    psr_mask = (height < -25.0) & (r_main < rad_main * 0.85)

    meta = {
        "region": region,
        "meters_per_pixel": float(mpp),
        "center_lat_deg": float(center_lat_deg),
        "center_lon_deg": float(center_lon_deg),
        "projection": "Polar Stereographic (Moon 2000, lat_ts=-90.0, lon_0=0.0)",
        "provenance": "generated",
        "source": "LOLA Polar Stereographic Terrain Model (synthetic demo tile)",
        "units": {
            "height": "m",
            "slope": "deg",
            "hazard": "probability 0..1",
            "uncertainty": "m (1-sigma)",
            "psr_mask": "bool"
        }
    }

    out_dir = Path("data/tiles")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{region}.npz"
    np.savez_compressed(
        out_path,
        height=height.astype(np.float32),
        slope=slope.astype(np.float32),
        hazard=hazard.astype(np.float32),
        uncertainty=uncertainty.astype(np.float32),
        psr_mask=psr_mask.astype(bool),
        region=np.array(region),
        meters_per_pixel=np.array(mpp, dtype=np.float32),
        center_lat_deg=np.array(center_lat_deg, dtype=np.float32),
        center_lon_deg=np.array(center_lon_deg, dtype=np.float32),
        meta=json.dumps(meta)
    )
    print(f"[Tile] Created {out_path} (shape: {height.shape}, mpp: {mpp}m)")
    return out_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create demo terrain tiles")
    parser.add_argument("--region", default="demo_craters")
    parser.add_argument("--size", type=int, default=400)
    parser.add_argument("--mpp", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    make_crater_tile(args.region, args.size, args.mpp, seed=args.seed)
    if args.region == "demo_craters":
        make_crater_tile("shackleton", size=500, mpp=20.0, center_lat_deg=-89.9, center_lon_deg=0.0, seed=12)
