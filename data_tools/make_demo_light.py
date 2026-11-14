"""GENERATED stand-in light data (point series) so the Navigator can run before KAN-23 delivers real files.

    python -m data_tools.make_demo_light                       # every tile in data/tiles named lola5m_*, 2 dates each
    python -m data_tools.make_demo_light --regions lola5m_site23 --dates 2027-03-01 2027-06-01

Writes data/light/<region>_<date>_points.npz in the light-contract v2 format (contracts/light.py).
Labelled GENERATED — NOT OBSERVED. It is NOT SPICE and NOT validated against JPL Horizons:

* Sun / Earth directions are analytic: real constants (29.53 d synodic month, 1.54 deg axial tilt,
  Earth libration amplitudes 6.7 deg / 7.9 deg and periods) but ARBITRARY phases. Expect phase errors of
  hours to days and wrong season. Fine for building the app, NOT for any claim.
* No parallax (Earth is treated as a direction at infinity); no refraction (the Moon has no atmosphere).
* The horizon profile IS computed from the real LOLA height window of the tile, but only out to the
  window edge (~2.5 km), so far-away mountains are missing and the horizon is biased low.
* Azimuth is in the tile frame (row 0 = +y). Convention x = r sin(lon), y = r cos(lon) (LOLA) is NOT yet
  verified (KAN-21), so tile-frame azimuth = true azimuth + east longitude.
"""

from __future__ import annotations

import argparse
import math
from datetime import UTC, datetime, timedelta

import numpy as np
from scipy.ndimage import map_coordinates

from contracts.light import CADENCE_S, SYNODIC_SAMPLES, PointSeries, save_points
from contracts.mission import load_mission
from contracts.paths import data_root, points_path, tile_path
from contracts.provenance import Meta, Provenance
from contracts.tiles import Tile, load_tile

# --- physical constants (sources in comments) -------------------------------------------------------
SYNODIC_MONTH_D = 29.530588861        # mean synodic month
NEW_MOON_REF = datetime(2000, 1, 6, 18, 14, tzinfo=UTC)  # a real new moon; later ones drift by up to ~14 h
AXIAL_TILT_DEG = 1.5424               # lunar equator vs ecliptic -> amplitude of sub-solar latitude
ECLIPSE_YEAR_D = 346.620              # period of the sub-solar latitude cycle
LIB_LAT_DEG, LIB_LAT_PERIOD_D = 6.68, 27.2122    # optical libration in latitude, draconic month
LIB_LON_DEG, LIB_LON_PERIOD_D = 7.9, 27.5546     # optical libration in longitude, anomalistic month
SUN_ANGULAR_RADIUS_DEG = 0.2666       # mean solar angular radius (959.6 arcsec)
J2000 = datetime(2000, 1, 1, 12, 0, tzinfo=UTC)
TT_MINUS_UTC_S = 69.184               # TT-UTC around 2017+ (ET ~ TT; real kernels give the exact value)
N_AZ = 360
N_RING = 1 + 8                        # candidate cell + 8 neighbours
RING_STEP_PX = 20                     # neighbours sit 20 px (100 m at 5 m/px) around the candidate
DATES = ("2027-03-01", "2027-06-01")  # window starts (UTC) for the STAND-IN; chosen so every demo site has some Sun and some dark


def parse_date(date: str) -> datetime:
    return datetime.fromisoformat(date).replace(tzinfo=UTC)


def time_axis(date: str, n: int = SYNODIC_SAMPLES) -> tuple[list[str], np.ndarray]:
    t0 = parse_date(date)
    times = [t0 + timedelta(seconds=CADENCE_S * i) for i in range(n)]
    et = np.array([(t - J2000).total_seconds() + TT_MINUS_UTC_S for t in times])
    return [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in times], et


def body_directions(date: str, n: int = SYNODIC_SAMPLES) -> dict[str, np.ndarray]:
    """Sub-solar and sub-Earth selenographic points (lat, east-lon, degrees) for each time sample."""
    t0 = parse_date(date)
    days = np.array([(t0 - NEW_MOON_REF).total_seconds() / 86400.0 + i * CADENCE_S / 86400.0 for i in range(n)])
    sun_lon = (180.0 - 360.0 * days / SYNODIC_MONTH_D + 180.0) % 360.0 - 180.0   # new moon: far side
    sun_lat = AXIAL_TILT_DEG * np.sin(2 * np.pi * days / ECLIPSE_YEAR_D)
    earth_lat = LIB_LAT_DEG * np.sin(2 * np.pi * days / LIB_LAT_PERIOD_D)
    earth_lon = LIB_LON_DEG * np.sin(2 * np.pi * days / LIB_LON_PERIOD_D)
    return {"sun_lat": sun_lat, "sun_lon": sun_lon, "earth_lat": earth_lat, "earth_lon": earth_lon}


def _unit(lat_deg: np.ndarray | float, lon_deg: np.ndarray | float) -> np.ndarray:
    la, lo = np.radians(lat_deg), np.radians(lon_deg)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la) * np.ones_like(lo)], axis=-1)


def elevation_azimuth(site_lat: float, site_lon: float, body_lat: np.ndarray,
                      body_lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Elevation above the local horizontal plane and TRUE azimuth (0 = north, clockwise) of a body at
    infinity whose sub-point is (body_lat, body_lon)."""
    p = _unit(site_lat, site_lon)
    d = _unit(body_lat, body_lon)
    la, lo = math.radians(site_lat), math.radians(site_lon)
    east = np.array([-math.sin(lo), math.cos(lo), 0.0])
    north = np.array([-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)])
    elev = np.degrees(np.arcsin(np.clip(d @ p, -1, 1)))
    az = np.degrees(np.arctan2(d @ east, d @ north)) % 360.0
    return elev, az


def tile_frame_azimuth(true_az_deg: np.ndarray, site_lon_deg: float) -> np.ndarray:
    """South-polar-stereographic tile frame: +y points at the 0 deg meridian, so the tile's 'north' is rotated
    from true north by -lon. Tile-frame azimuth = true azimuth + east longitude."""
    return (true_az_deg + site_lon_deg) % 360.0


def sun_visible_fraction(sun_elev_deg: np.ndarray, horizon_deg: np.ndarray) -> np.ndarray:
    """Fraction of the solar disk above a straight horizon line at `horizon_deg` (finite disk, no refraction)."""
    x = np.clip((sun_elev_deg - horizon_deg) / SUN_ANGULAR_RADIUS_DEG, -1.0, 1.0)
    return 1.0 - (np.arccos(x) - x * np.sqrt(1.0 - x * x)) / np.pi


def horizon_profile(height: np.ndarray, mpp: float, row: float, col: float, moon_radius_m: float,
                    max_px: int = 512) -> np.ndarray:
    """Horizon elevation [360] (index = tile-frame azimuth degree, 0 = +y/up, clockwise) by ray-casting the
    height grid from one cell. Only sees terrain inside the tile; includes the curvature drop d^2/2R."""
    h0 = float(map_coordinates(height, [[row], [col]], order=1, mode="nearest")[0])
    az = np.radians(np.arange(N_AZ))
    k = np.arange(1, max_px + 1)
    rr = row - np.cos(az)[:, None] * k[None, :]
    cc = col + np.sin(az)[:, None] * k[None, :]
    inside = (rr >= 0) & (rr <= height.shape[0] - 1) & (cc >= 0) & (cc <= height.shape[1] - 1)
    hh = map_coordinates(height, [rr.ravel(), cc.ravel()], order=1, mode="nearest").reshape(rr.shape)
    d = k[None, :] * mpp
    ang = np.degrees(np.arctan2(hh - h0 - d * d / (2 * moon_radius_m), d))
    ang = np.where(inside, ang, -np.inf)
    out = ang.max(axis=1)
    return np.where(np.isfinite(out), out, 0.0)


def ring_cells(tile: Tile) -> np.ndarray:
    """Candidate = tile centre; then 8 neighbours at +-RING_STEP_PX."""
    h, w = tile.shape
    r0, c0 = (h - 1) // 2, (w - 1) // 2
    step = min(RING_STEP_PX, (min(h, w) - 1) // 4)
    cells = [(r0, c0)] + [(r0 + dr * step, c0 + dc * step) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)]
    return np.array(cells, dtype=np.int64)


def make_points(tile: Tile, date: str) -> PointSeries:
    cfg = load_mission()
    lat, lon_e = tile.center_lat_deg, tile.center_lon_deg
    lon_pm = (lon_e + 180.0) % 360.0 - 180.0
    times, et = time_axis(date)
    b = body_directions(date)
    cells = ring_cells(tile)
    horizon = np.stack([horizon_profile(tile.height, tile.meters_per_pixel, r, c, cfg.moon.radius_m)
                        for r, c in cells])                                   # [K,360]
    sun_el, sun_az_true = elevation_azimuth(lat, lon_pm, b["sun_lat"], b["sun_lon"])
    ea_el, ea_az_true = elevation_azimuth(lat, lon_pm, b["earth_lat"], b["earth_lon"])
    sun_az, ea_az = tile_frame_azimuth(sun_az_true, lon_pm), tile_frame_azimuth(ea_az_true, lon_pm)

    def horizon_at(az_deg: np.ndarray) -> np.ndarray:        # [T,K] linear interpolation between 1 deg bins
        i0 = np.floor(az_deg).astype(int) % N_AZ
        f = az_deg - np.floor(az_deg)
        return (1 - f)[:, None] * horizon[:, i0].T + f[:, None] * horizon[:, (i0 + 1) % N_AZ].T

    sun_fraction = sun_visible_fraction(sun_el[:, None], horizon_at(sun_az))
    meta = Meta(
        provenance=Provenance.GENERATED,
        source=("data_tools.make_demo_light: ANALYTIC Sun/Earth stand-in (arbitrary phases, NOT SPICE, not validated "
                f"vs JPL Horizons); horizon ray-cast from {tile.meta.source}, only out to the tile edge"),
        frame="local tile ENU (south polar stereographic, row 0 = +y); azimuth = true azimuth + east longitude",
        created_by="data_tools.make_demo_light",
        units={"sun_elev_deg": "deg above local horizontal plane (not terrain)", "earth_elev_deg": "same"},
    )
    ps = PointSeries(region=tile.region, date=date, cells=cells, times_utc=times, et_s=et,
                     sun_fraction=sun_fraction.astype(np.float32),
                     sun_elev_deg=np.repeat(sun_el[:, None], len(cells), axis=1).astype(np.float32),
                     earth_elev_deg=np.repeat(ea_el[:, None], len(cells), axis=1).astype(np.float32),
                     sun_az_deg=sun_az.astype(np.float32), earth_az_deg=ea_az.astype(np.float32),
                     horizon_elev_deg=horizon.astype(np.float32), meta=meta)
    ps.validate()
    return ps


def default_regions() -> list[str]:
    d = data_root() / "tiles"
    return sorted(p.stem for p in d.glob("lola5m_*.npz")) if d.exists() else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regions", nargs="+", default=None)
    ap.add_argument("--dates", nargs="+", default=list(DATES))
    a = ap.parse_args(argv)
    regions = a.regions or default_regions()
    if not regions:
        ap.error("no tiles found: run  python -I -m worldmodel.hazard.lola all  or pass --regions")
    for region in regions:
        tile = load_tile(tile_path(region))
        for date in a.dates:
            ps = make_points(tile, date)
            p = save_points(ps, points_path(region, date))
            up = float((ps.sun_fraction[:, 0] > 0).mean())
            print(f"wrote {p.name}: K={len(ps.cells)} T={len(ps.times_utc)} sun up {up:.0%} of the window "
                  f"[{ps.meta.provenance.banner}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
