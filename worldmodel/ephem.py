"""
Lunar Ephemeris and Horizon Obscuration Model (worldmodel/ephem.py).

Computes high-precision Sun and Earth vectors in the Moon-centered Moon-Fixed (MOON_ME)
frame, calculates topocentric elevation/azimuth from arbitrary surface sites, evaluates
local horizon masking from Digital Elevation Models, and generates standard light
visibility datasets (data/light/<region>_<range>.npz).

Context: Spec §4.2 (Sunlight and Direct-to-Earth contact).
Reference Epoch: 2026-11-14T00:00:00Z (Julian Date: 2461358.5).
"""

from __future__ import annotations
import math
import json
from pathlib import Path
from typing import Any
import numpy as np

# Astronomical Constants (all SI units explicitly commented)
R_MOON_M = 1737400.0           # [m] Lunar mean spherical radius
SOLAR_CONSTANT_W_M2 = 1361.0   # [W/m^2] Total solar irradiance at 1 AU
SUN_ANGULAR_RADIUS_DEG = 0.2666 # [deg] Solar angular semi-diameter at 1 AU (~16 arcmin)
EARTH_ANGULAR_RADIUS_DEG = 0.95 # [deg] Earth angular semi-diameter from Moon (~1.9 deg diam)

# Lunar synodic month (lunar solar day period from new moon to new moon)
LUNAR_SYNODIC_PERIOD_S = 29.530588853 * 86400.0  # [s] ~2551442.88 s (~708.73 hours)
LUNAR_NODICAL_PERIOD_S = 27.212220817 * 86400.0  # [s] Draconic / latitude libration period
LUNAR_ANOMALISTIC_PERIOD_S = 27.55454988 * 86400.0 # [s] Perigee / longitude libration period

# Lunar obliquity to the ecliptic plane
LUNAR_OBLIQUITY_RAD = math.radians(1.5424)  # [rad] ~1.5424 deg
EARTH_LIBRATION_LAT_MAX_RAD = math.radians(6.68)  # [rad] Max optical libration in latitude
EARTH_LIBRATION_LON_MAX_RAD = math.radians(7.91)  # [rad] Max optical libration in longitude
MEAN_EARTH_DISTANCE_M = 384400000.0               # [m] Mean Earth-Moon distance

# Reference Epoch: 2026-11-14T00:00:00 UTC (Julian Date 2461358.5)
# Near lunar South Pole, in mid-November (southern summer), the sub-solar latitude is negative (~-1.4 deg),
# providing peak illumination to the southern crater rims.
EPOCH_SUB_SOLAR_LAT_DEG = -1.38   # [deg] Sub-solar latitude at 2026-11-14 (summer in south)
EPOCH_SUB_SOLAR_LON_DEG = 42.50   # [deg] Sub-solar longitude at 2026-11-14T00:00:00 UTC


class LunarEphemeris:
    """
    Computes topocentric solar and terrestrial ephemerides for lunar surface stations.
    """

    def __init__(
        self,
        ref_epoch_str: str = "2026-11-14T00:00:00Z",
        epoch_sub_solar_lat_deg: float = EPOCH_SUB_SOLAR_LAT_DEG,
        epoch_sub_solar_lon_deg: float = EPOCH_SUB_SOLAR_LON_DEG
    ):
        """
        Initialize the ephemeris model.

        Parameters:
            ref_epoch_str: ISO string of simulation start epoch.
            epoch_sub_solar_lat_deg: Sub-solar latitude on Moon at t=0 [deg].
            epoch_sub_solar_lon_deg: Sub-solar longitude on Moon at t=0 [deg].
        """
        self.ref_epoch_str = ref_epoch_str
        self.sub_solar_lat0 = math.radians(epoch_sub_solar_lat_deg)
        self.sub_solar_lon0 = math.radians(epoch_sub_solar_lon_deg)
        self.omega_synodic = 2.0 * math.pi / LUNAR_SYNODIC_PERIOD_S  # [rad/s]
        self.omega_lat_lib = 2.0 * math.pi / LUNAR_NODICAL_PERIOD_S   # [rad/s]
        self.omega_lon_lib = 2.0 * math.pi / LUNAR_ANOMALISTIC_PERIOD_S # [rad/s]

    def get_sun_subsolar_latlon(self, time_s: float) -> tuple[float, float]:
        """
        Compute the sub-solar point (latitude, longitude) on the Moon at time_s.

        Parameters:
            time_s: Elapsed simulation time from epoch [s].

        Returns:
            (lat_deg, lon_deg): Sub-solar planetocentric coordinates in degrees.
        """
        # Solar longitude decreases (moves westward) as Moon rotates eastward relative to Sun
        lon_rad = (self.sub_solar_lon0 - self.omega_synodic * time_s) % (2.0 * math.pi)
        if lon_rad > math.pi:
            lon_rad -= 2.0 * math.pi

        # Solar latitude oscillates with obliquity (~1.54 deg) with synodic/draconic phase
        lat_rad = self.sub_solar_lat0 * math.cos(self.omega_synodic * time_s)
        return math.degrees(lat_rad), math.degrees(lon_rad)

    def get_earth_subearth_latlon(self, time_s: float) -> tuple[float, float, float]:
        """
        Compute the sub-Earth point and distance from Moon center at time_s.

        Parameters:
            time_s: Elapsed simulation time from epoch [s].

        Returns:
            (lat_deg, lon_deg, dist_m): Sub-Earth planetocentric coordinates [deg] and range [m].
        """
        # Earth oscillates around (0 deg, 0 deg) due to physical and optical librations
        lat_rad = EARTH_LIBRATION_LAT_MAX_RAD * math.sin(self.omega_lat_lib * time_s + 0.45)
        lon_rad = EARTH_LIBRATION_LON_MAX_RAD * math.sin(self.omega_lon_lib * time_s - 1.20)
        # Distance oscillates with lunar eccentricity e = 0.0549
        dist_m = MEAN_EARTH_DISTANCE_M * (1.0 - 0.0549 * math.cos(self.omega_lon_lib * time_s))
        return math.degrees(lat_rad), math.degrees(lon_rad), dist_m

    def get_topo_angles(
        self,
        site_lat_deg: float,
        site_lon_deg: float,
        time_s: float
    ) -> dict[str, float]:
        """
        Compute topocentric elevation and azimuth angles of Sun and Earth
        from a lunar surface site at given coordinates.

        Parameters:
            site_lat_deg: Site planetocentric latitude [deg] (South is negative).
            site_lon_deg: Site planetocentric longitude [deg] (East is positive).
            time_s: Elapsed simulation time from epoch [s].

        Returns:
            Dict containing:
                - 'sun_elevation_deg': Elevation above local horizontal [deg]
                - 'sun_azimuth_deg': Azimuth clockwise from North [0..360 deg]
                - 'earth_elevation_deg': Elevation above local horizontal [deg]
                - 'earth_azimuth_deg': Azimuth clockwise from North [0..360 deg]
        """
        phi_s = math.radians(site_lat_deg)
        lam_s = math.radians(site_lon_deg)

        # Local topocentric unit vectors in MOON_ME frame:
        # Up (surface normal):
        u_up = np.array([
            math.cos(phi_s) * math.cos(lam_s),
            math.cos(phi_s) * math.sin(lam_s),
            math.sin(phi_s)
        ], dtype=np.float64)

        # East:
        u_east = np.array([
            -math.sin(lam_s),
            math.cos(lam_s),
            0.0
        ], dtype=np.float64)

        # North:
        u_north = np.array([
            -math.sin(phi_s) * math.cos(lam_s),
            -math.sin(phi_s) * math.sin(lam_s),
            math.cos(phi_s)
        ], dtype=np.float64)

        # 1. Sun vector
        sun_lat_deg, sun_lon_deg = self.get_sun_subsolar_latlon(time_s)
        phi_sun = math.radians(sun_lat_deg)
        lam_sun = math.radians(sun_lon_deg)
        u_sun = np.array([
            math.cos(phi_sun) * math.cos(lam_sun),
            math.cos(phi_sun) * math.sin(lam_sun),
            math.sin(phi_sun)
        ], dtype=np.float64)

        # Sun topocentric coordinates:
        sun_up = float(np.dot(u_sun, u_up))
        sun_e = float(np.dot(u_sun, u_east))
        sun_n = float(np.dot(u_sun, u_north))

        sun_elev_rad = math.asin(np.clip(sun_up, -1.0, 1.0))
        sun_azim_rad = math.atan2(sun_e, sun_n)
        sun_azim_deg = math.degrees(sun_azim_rad) % 360.0

        # 2. Earth vector
        earth_lat_deg, earth_lon_deg, _ = self.get_earth_subearth_latlon(time_s)
        phi_earth = math.radians(earth_lat_deg)
        lam_earth = math.radians(earth_lon_deg)
        u_earth = np.array([
            math.cos(phi_earth) * math.cos(lam_earth),
            math.cos(phi_earth) * math.sin(lam_earth),
            math.sin(phi_earth)
        ], dtype=np.float64)

        # Earth topocentric coordinates:
        earth_up = float(np.dot(u_earth, u_up))
        earth_e = float(np.dot(u_earth, u_east))
        earth_n = float(np.dot(u_earth, u_north))

        earth_elev_rad = math.asin(np.clip(earth_up, -1.0, 1.0))
        earth_azim_rad = math.atan2(earth_e, earth_n)
        earth_azim_deg = math.degrees(earth_azim_rad) % 360.0

        return {
            "sun_elevation_deg": math.degrees(sun_elev_rad),
            "sun_azimuth_deg": sun_azim_deg,
            "earth_elevation_deg": math.degrees(earth_elev_rad),
            "earth_azimuth_deg": earth_azim_deg
        }


def compute_horizon_mask_from_terrain(
    site_x_m: float,
    site_y_m: float,
    terrain: Any,
    num_azimuths: int = 360,
    max_range_m: float = 30000.0,
    range_step_m: float = 50.0
) -> np.ndarray:
    """
    Compute local topographic horizon elevation mask from a digital elevation model.

    For each azimuth angle around the site, rays are cast outwards across the terrain.
    The highest angular elevation is recorded as the local horizon mask angle.

    Parameters:
        site_x_m: Site polar stereographic X coordinate [m].
        site_y_m: Site polar stereographic Y coordinate [m].
        terrain: LunarTerrain instance.
        num_azimuths: Number of azimuth sectors (default: 360 for 1-degree resolution).
        max_range_m: Maximum raycast radial range [m] (default: 30 km).
        range_step_m: Radial step increment [m] (default: 50 m).

    Returns:
        horizon_angles_deg: Array of shape (num_azimuths,) containing horizon mask in degrees.
    """
    site_z_m = float(terrain.ground_height(site_x_m, site_y_m)) + 2.0  # +2m lander antenna/mast height
    azimuths_deg = np.linspace(0.0, 360.0, num_azimuths, endpoint=False)
    horizon_mask_deg = np.zeros(num_azimuths, dtype=np.float64)

    ranges = np.arange(range_step_m, max_range_m + range_step_m, range_step_m)

    for i, az_deg in enumerate(azimuths_deg):
        az_rad = math.radians(az_deg)
        # Topocentric coords: dx = r * sin(az), dy = r * cos(az)
        xs = site_x_m + ranges * math.sin(az_rad)
        ys = site_y_m + ranges * math.cos(az_rad)

        heights = terrain.ground_height(xs, ys)
        # Drop due to lunar spherical curvature: d^2 / (2 * R_moon)
        curvature_drop = (ranges ** 2) / (2.0 * R_MOON_M)
        effective_dh = heights - site_z_m - curvature_drop

        angles_rad = np.arctan2(effective_dh, ranges)
        max_angle_deg = float(np.max(np.degrees(angles_rad)))
        # Geometric dip angle over flat sphere: ~ -0.09 deg for 2m mast
        horizon_mask_deg[i] = max(max_angle_deg, -0.15)

    return horizon_mask_deg


def calculate_sun_fraction(sun_elevation_deg: float, horizon_elev_deg: float) -> float:
    """
    Compute the unblocked fraction of the solar disc taking into account
    the finite solar angular semi-diameter (~0.267 deg).

    Parameters:
        sun_elevation_deg: Solar elevation above local horizontal [deg].
        horizon_elev_deg: Local horizon obstruction angle at solar azimuth [deg].

    Returns:
        sun_fraction: Value in [0.0, 1.0] representing visible solar flux fraction.
    """
    delta_deg = sun_elevation_deg - horizon_elev_deg
    r_deg = SUN_ANGULAR_RADIUS_DEG

    if delta_deg >= r_deg:
        return 1.0  # Fully above horizon
    elif delta_deg <= -r_deg:
        return 0.0  # Fully below horizon

    # Partial occultation: linear/circular cap approximation
    frac = (delta_deg + r_deg) / (2.0 * r_deg)
    return float(np.clip(frac, 0.0, 1.0))


def generate_light_dataset(
    region_name: str,
    site_lat_deg: float,
    site_lon_deg: float,
    site_x_m: float = 0.0,
    site_y_m: float = 0.0,
    terrain: Any = None,
    duration_days: float = 30.0,
    step_s: float = 60.0,
    output_dir: str | Path = "data/light",
    ref_epoch_str: str = "2026-11-14T00:00:00Z"
) -> Path:
    """
    Generate and save a standard lunar light visibility dataset:
    data/light/<region>_<range>.npz containing sun_fraction, earth_visible,
    elevation, and azimuth angles over time.

    Parameters:
        region_name: Identifier name (e.g. 'shackleton', 'shiv_shakti').
        site_lat_deg: Site latitude in degrees.
        site_lon_deg: Site longitude in degrees.
        site_x_m: Polar stereographic X [m].
        site_y_m: Polar stereographic Y [m].
        terrain: Optional LunarTerrain instance to compute topography mask.
        duration_days: Duration of simulation in Earth days (default: 30.0 days).
        step_s: Time step in seconds (default: 60 s = 1 minute).
        output_dir: Target output directory.
        ref_epoch_str: Reference start epoch.

    Returns:
        output_path: Path to the generated .npz archive.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total_s = duration_days * 86400.0
    times_s = np.arange(0.0, total_s + step_s, step_s, dtype=np.float64)
    n_steps = len(times_s)

    ephem = LunarEphemeris(ref_epoch_str=ref_epoch_str)

    # Compute or assign horizon mask
    if terrain is not None:
        horizon_mask = compute_horizon_mask_from_terrain(site_x_m, site_y_m, terrain)
    else:
        # Default nominal terrain horizon mask (~0.5 to 1.5 deg undulating rim)
        num_az = 360
        az = np.linspace(0.0, 360.0, num_az, endpoint=False)
        horizon_mask = 0.6 + 0.4 * np.sin(np.radians(2.0 * az)) + 0.2 * np.cos(np.radians(5.0 * az))

    sun_fraction = np.zeros(n_steps, dtype=np.float32)
    sun_elev = np.zeros(n_steps, dtype=np.float32)
    sun_azim = np.zeros(n_steps, dtype=np.float32)
    earth_visible = np.zeros(n_steps, dtype=bool)
    earth_elev = np.zeros(n_steps, dtype=np.float32)
    earth_azim = np.zeros(n_steps, dtype=np.float32)

    for i, t in enumerate(times_s):
        angles = ephem.get_topo_angles(site_lat_deg, site_lon_deg, t)
        se = angles["sun_elevation_deg"]
        sa = angles["sun_azimuth_deg"]
        ee = angles["earth_elevation_deg"]
        ea = angles["earth_azimuth_deg"]

        sun_elev[i] = se
        sun_azim[i] = sa
        earth_elev[i] = ee
        earth_azim[i] = ea

        # Lookup horizon angle at sun azimuth
        az_idx = int(round(sa)) % 360
        horiz_sun = float(horizon_mask[az_idx])
        sun_fraction[i] = calculate_sun_fraction(se, horiz_sun)

        # Lookup horizon angle at Earth azimuth (Earth is treated as point source per navigator/metrics.py)
        e_az_idx = int(round(ea)) % 360
        horiz_earth = float(horizon_mask[e_az_idx])
        earth_visible[i] = bool(ee > horiz_earth)

    # File naming: <region>_<range>.npz (e.g. shackleton_30d.npz)
    filename = f"{region_name}_{int(duration_days)}d.npz"
    out_file = out_dir / filename

    metadata = {
        "region": region_name,
        "site_lat_deg": site_lat_deg,
        "site_lon_deg": site_lon_deg,
        "ref_epoch": ref_epoch_str,
        "duration_days": duration_days,
        "step_s": step_s,
        "n_samples": n_steps,
        "mean_sun_fraction": float(np.mean(sun_fraction)),
        "earth_contact_pct": float(np.mean(earth_visible) * 100.0)
    }

    np.savez_compressed(
        out_file,
        time_s=times_s,
        sun_fraction=sun_fraction,
        sun_elevation_deg=sun_elev,
        sun_azimuth_deg=sun_azim,
        earth_visible=earth_visible,
        earth_elevation_deg=earth_elev,
        earth_azimuth_deg=earth_azim,
        horizon_mask_deg=horizon_mask,
        meta=json.dumps(metadata)
    )

    print(f"[Light Generator] Wrote {out_file} ({n_steps} samples over {duration_days} days)")
    return out_file
