#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Traversable synthetic terrain for rover demonstrations (GENERATED, not observed).

``data_tools/make_demo_tile.py`` builds one deep bowl whose walls are steeper
than any rover can climb, so a rover can never enter the shadowed floor. This
generator builds several *degraded* craters (depth-to-radius ratio about 0.1,
wall slopes about 12 degrees) so shadowed floors exist that a rover can reach.
The output follows the same tile format as ``make_demo_tile``.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

REGION = "rover_demo"


def make_rover_tile(size: int = 400, mpp: float = 5.0, seed: int = 7) -> dict[str, Any]:
    """Return an in-memory tile dictionary compatible with ``load_tile``.

    :param size: tile width and height [px].
    :param mpp: ground sampling distance [m/px].
    :param seed: random seed for the crater layout.
    """
    rng = np.random.default_rng(seed)
    half = (size - 1) / 2.0 * mpp  # [m]
    xs = np.linspace(-half, half, size)
    X, Y = np.meshgrid(xs, xs[::-1])  # row 0 = north (+y)

    height = 0.01 * X - 0.006 * Y + 4.0 * np.sin(X / 300.0) * np.cos(Y / 380.0)
    psr = np.zeros((size, size), dtype=bool)

    # Large degraded craters: shadowed floors that the rover can reach.
    placed: list[tuple[float, float, float]] = []
    for _ in range(400):
        if len(placed) >= 6:
            break
        rad = rng.uniform(130.0, 230.0)  # [m]
        cx, cy = rng.uniform(-half * 0.8, half * 0.8, 2)
        if all(np.hypot(cx - px, cy - py) > 0.9 * (rad + pr) for px, py, pr in placed):
            placed.append((cx, cy, rad))
    for cx, cy, rad in placed:
        depth = rng.uniform(0.09, 0.11) * rad  # [m] depth-to-radius ratio ~0.1
        r = np.hypot(X - cx, Y - cy)
        bowl = np.where(r < rad, -depth * (1.0 - (r / rad) ** 2), 0.0)
        rim = 0.12 * depth * np.exp(-((r - rad) / (0.25 * rad)) ** 2)
        height += bowl + rim
        psr |= r < 0.75 * rad  # shadowed floor (GENERATED assumption)

    # Small craters: local obstacles.
    for _ in range(40):
        cx, cy = rng.uniform(-half * 0.95, half * 0.95, 2)
        rad = rng.uniform(8.0, 40.0)  # [m]
        depth = rng.uniform(0.12, 0.2) * rad  # [m]
        r = np.hypot(X - cx, Y - cy)
        height += np.where(r < rad, -depth * (1.0 - (r / rad) ** 2), 0.0)
        height += 0.14 * depth * np.exp(-((r - rad) / (0.25 * rad)) ** 2)

    gy, gx = np.gradient(height, mpp)
    slope = np.rad2deg(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    hazard = np.clip((slope - 14.0) / 10.0, 0.0, 1.0).astype(np.float32)  # [-] 0 below 14 deg

    meta = {
        "region": REGION,
        "provenance": "generated",
        "source": "lunar_ops.demo_tile (synthetic degraded craters, not observed)",
    }
    return {
        "height": height.astype(np.float32),
        "slope": slope,
        "hazard": hazard,
        "uncertainty": np.full_like(height, 0.75, dtype=np.float32),
        "psr_mask": psr,
        "meters_per_pixel": float(mpp),
        "center_lat_deg": -89.9,
        "center_lon_deg": 0.0,
        "meta": json.loads(json.dumps(meta)),
    }
