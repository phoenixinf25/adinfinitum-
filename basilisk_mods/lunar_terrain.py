"""
basilisk_mods/lunar_terrain.py
==============================
Lunar terrain elevation and surface slope helper for Basilisk simulation scenarios.

Provides:
- Conversion between Moon-Centred, Moon-Fixed (MOON_ME) cartesian position (metres)
  and South Polar-Stereographic projection (x, y) coordinates (metres) + altitude
  above the reference sphere (radius 1,737,400.0 m / 1737.4 km).
- Fast bilinear interpolation of terrain ground elevation (metres) and surface slope
  (degrees) from polar-stereographic DEM tiles (data/tiles/<region>.npz).
- Spacecraft altitude above real terrain ground (metres).
- Spacecraft touchdown detection and landing hazard evaluation for descent scenarios.
- Wavefront OBJ mesh export for Basilisk Vizard 3D visualization.

UNITS CONVENTION (Strictly Enforced):
- Distances, positions, elevations, and altitudes: METRES [m]
- Angles, latitudes, longitudes, and slopes: DEGREES [deg]
- Velocities: METRES PER SECOND [m/s]
- Reference Moon sphere radius: 1,737,400.0 METRES (1737.4 km)

Context: Spec §7.2 Lunar Landing Simulation Architecture.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

# Canonical lunar mean spherical radius constants
R_MOON_M: float = 1737400.0   # Reference lunar radius in METRES [m]
R_MOON_KM: float = 1737.4      # Reference lunar radius in KILOMETRES [km]


class TouchdownReport(NamedTuple):
    """
    Touchdown inspection outcome.
    All distance units are in metres [m], angles in degrees [deg], velocities in m/s.
    """
    contact: bool                       # True if spacecraft ground clearance <= touchdown threshold
    altitude_above_ground_m: float      # Distance from ground to spacecraft center in metres [m]
    altitude_above_sphere_m: float      # Distance from lunar sphere (R=1737.4km) in metres [m]
    ground_height_m: float              # Local ground elevation above reference sphere in metres [m]
    terrain_slope_deg: float            # Local ground slope angle in degrees [deg]
    polar_stereographic_x_m: float      # Polar-stereographic Easting coordinate in metres [m]
    polar_stereographic_y_m: float      # Polar-stereographic Northing coordinate in metres [m]
    vertical_velocity_mps: float | None # Radial velocity towards lunar center (negative = descending) [m/s]
    horizontal_speed_mps: float | None  # Horizontal ground velocity magnitude [m/s]
    is_safe: bool                       # True if contact is True, velocity <= limit, and slope <= limit
    status: str                         # Summary message code (e.g. TOUCHDOWN_SUCCESS)


# ==============================================================================
# 1. Coordinate Frame Transformations (MOON_ME <-> Polar Stereographic)
# ==============================================================================

def ps_from_moon_fixed(
    r_moon_fixed: np.ndarray | list[float] | tuple[float, float, float],
    r_moon_radius_m: float = R_MOON_M
) -> tuple[float, float, float]:
    """
    Convert spacecraft position vector from Moon-Centred, Moon-Fixed (MOON_ME)
    cartesian frame to South Polar-Stereographic (x, y) coordinates and altitude
    above the lunar reference sphere.

    Frame Definitions:
    - MOON_ME (IAU Moon Mean Earth / Polar Axis frame):
        Origin: Moon center of mass.
        +Z axis: Lunar rotational North Pole (latitude = +90 deg).
        +X axis: Sub-Earth prime meridian intersection (lat = 0 deg, lon = 0 deg).
        +Y axis: Completes right-handed system (lat = 0 deg, lon = +90 deg East).
        Units: METRES [m].
    - South Polar Stereographic:
        Standard conformal azimuthal projection tangent/secant at South Pole.
        Origin (0, 0): Lunar South Pole (lat = -90.0 deg).
        +X axis: Points towards East longitude = +90.0 deg.
        +Y axis: Points towards longitude = 180.0 deg (lunar farside / North on map).
        -Y axis: Points towards longitude = 0.0 deg (sub-Earth / South on map).
        Units: METRES [m].

    Parameters:
        r_moon_fixed: 3-element cartesian vector [r_x, r_y, r_z] in METRES [m].
        r_moon_radius_m: Mean spherical Moon radius in METRES [m] (default: 1,737,400.0 m).

    Returns:
        tuple[float, float, float]:
            x_m: Polar-stereographic Easting coordinate in METRES [m].
            y_m: Polar-stereographic Northing coordinate in METRES [m].
            alt_sphere_m: Altitude above lunar reference sphere in METRES [m].
    """
    rx = float(r_moon_fixed[0])
    ry = float(r_moon_fixed[1])
    rz = float(r_moon_fixed[2])

    # Distance from Moon center of mass in metres [m]
    r = math.sqrt(rx * rx + ry * ry + rz * rz)
    if r < 1e-3:
        raise ValueError("Spacecraft position cannot be at the lunar center of mass.")

    # Altitude above the lunar reference sphere in metres [m]
    alt_sphere_m = r - r_moon_radius_m

    # Unit direction vector in MOON_ME frame
    ux = rx / r
    uy = ry / r
    uz = rz / r

    # At exact North Pole (uz = 1), stereographic projection from South Pole approaches infinity
    denom = 1.0 - uz
    if denom < 1e-12:
        raise ValueError("Position is at or near the lunar North Pole; South Polar Stereographic is undefined.")

    # Polar stereographic planar coordinates in metres [m]:
    # rho = 2 * R * tan(colat / 2) = 2 * R * sqrt(ux^2 + uy^2) / (1 - uz)
    # x = rho * sin(lon) = 2 * R * uy / (1 - uz)
    # y = -rho * cos(lon) = -2 * R * ux / (1 - uz)
    scale = 2.0 * r_moon_radius_m / denom
    x_m = scale * uy
    y_m = -scale * ux

    return x_m, y_m, alt_sphere_m


def moon_fixed_from_ps(
    x_m: float,
    y_m: float,
    alt_sphere_m: float = 0.0,
    r_moon_radius_m: float = R_MOON_M
) -> np.ndarray:
    """
    Convert South Polar-Stereographic coordinates (x, y) and altitude above the
    lunar reference sphere back to Moon-Centred, Moon-Fixed (MOON_ME) cartesian
    coordinates [r_x, r_y, r_z].

    Parameters:
        x_m: Polar-stereographic Easting coordinate in METRES [m].
        y_m: Polar-stereographic Northing coordinate in METRES [m].
        alt_sphere_m: Altitude above the reference sphere in METRES [m] (default: 0.0 m).
        r_moon_radius_m: Mean spherical Moon radius in METRES [m] (default: 1,737,400.0 m).

    Returns:
        np.ndarray: [r_x_m, r_y_m, r_z_m] in METRES [m].
    """
    rho = math.hypot(x_m, y_m)
    r_total_m = r_moon_radius_m + alt_sphere_m

    if rho < 1e-9:
        # Exactly at South Pole (lat = -90 deg, lon undefined -> 0 deg)
        return np.array([0.0, 0.0, -r_total_m], dtype=np.float64)

    # Colatitude angle chi from South Pole
    chi = 2.0 * math.atan(rho / (2.0 * r_moon_radius_m))
    lat_rad = chi - (math.pi / 2.0)   # Latitude in radians [-pi/2, pi/2]
    lon_rad = math.atan2(x_m, -y_m)   # Longitude in radians [-pi, pi]

    cos_lat = math.cos(lat_rad)
    sin_lat = math.sin(lat_rad)
    cos_lon = math.cos(lon_rad)
    sin_lon = math.sin(lon_rad)

    rx_m = r_total_m * cos_lat * cos_lon
    ry_m = r_total_m * cos_lat * sin_lon
    rz_m = r_total_m * sin_lat

    return np.array([rx_m, ry_m, rz_m], dtype=np.float64)


def latlon_from_moon_fixed(
    r_moon_fixed: np.ndarray | list[float]
) -> tuple[float, float, float]:
    """
    Convert MOON_ME position vector in METRES [m] to planetocentric latitude
    (degrees), longitude (degrees), and altitude above reference sphere (metres).

    Parameters:
        r_moon_fixed: [r_x, r_y, r_z] in METRES [m].

    Returns:
        tuple[float, float, float]:
            lat_deg: Latitude in DEGREES [-90.0, 90.0] (South = negative).
            lon_deg: Longitude in DEGREES [-180.0, 180.0] (East = positive).
            alt_sphere_m: Altitude above reference sphere in METRES [m].
    """
    rx = float(r_moon_fixed[0])
    ry = float(r_moon_fixed[1])
    rz = float(r_moon_fixed[2])
    r = math.sqrt(rx * rx + ry * ry + rz * rz)
    alt_sphere_m = r - R_MOON_M
    lat_deg = math.degrees(math.asin(max(-1.0, min(1.0, rz / r))))
    lon_deg = math.degrees(math.atan2(ry, rx))
    return lat_deg, lon_deg, alt_sphere_m


def moon_fixed_from_latlon(
    lat_deg: float,
    lon_deg: float,
    alt_sphere_m: float = 0.0,
    r_moon_radius_m: float = R_MOON_M
) -> np.ndarray:
    """
    Convert planetocentric latitude (degrees), longitude (degrees), and altitude
    above reference sphere (metres) to MOON_ME cartesian position [r_x, r_y, r_z] (metres).

    Parameters:
        lat_deg: Latitude in DEGREES [-90.0, 90.0] (South = negative).
        lon_deg: Longitude in DEGREES [-180.0, 180.0] (East = positive).
        alt_sphere_m: Altitude above reference sphere in METRES [m] (default: 0.0 m).
        r_moon_radius_m: Lunar spherical radius in METRES [m] (default: 1,737,400.0 m).

    Returns:
        np.ndarray: [r_x_m, r_y_m, r_z_m] in METRES [m].
    """
    r_total_m = r_moon_radius_m + alt_sphere_m
    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg)
    rx = r_total_m * math.cos(lat_rad) * math.cos(lon_rad)
    ry = r_total_m * math.cos(lat_rad) * math.sin(lon_rad)
    rz = r_total_m * math.sin(lat_rad)
    return np.array([rx, ry, rz], dtype=np.float64)


# ==============================================================================
# 2. LunarTerrain Class (Bilinear Interpolation of Elevation & Slope)
# ==============================================================================

class LunarTerrain:
    """
    Digital Elevation and Slope Model interpolator for lunar surface tiles.

    Loads polar-stereographic DEM tiles (.npz) conforming to spec §7.2 / FORMATS.md.
    Provides fast, continuous bilinear interpolation of ground height (metres)
    and surface slope (degrees) under arbitrary spacecraft positions.
    """

    def __init__(
        self,
        tile_path_or_region: str | Path,
        tiles_dir: str | Path = "data/tiles",
        moon_radius_m: float = R_MOON_M
    ) -> None:
        """
        Initialize the lunar terrain interpolator from a region name or tile .npz file.

        Parameters:
            tile_path_or_region: Path to .npz tile, or region name (e.g. 'demo_craters').
            tiles_dir: Directory containing tile files (default: 'data/tiles').
            moon_radius_m: Reference Moon spherical radius in METRES [m] (default: 1,737,400.0 m).
        """
        self.moon_radius_m: float = float(moon_radius_m)
        self.tile_path: Path = self._resolve_tile_path(tile_path_or_region, tiles_dir)
        self._load_tile_data()

    @staticmethod
    def _resolve_tile_path(tile_path_or_region: str | Path, tiles_dir: str | Path) -> Path:
        p = Path(tile_path_or_region)
        if p.exists() and p.is_file():
            return p
        if not str(p).endswith(".npz"):
            p_with_ext = Path(tiles_dir) / f"{p.name}.npz"
            if p_with_ext.exists():
                return p_with_ext
        fallback = Path(tiles_dir) / p.name
        if fallback.exists():
            return fallback
        raise FileNotFoundError(f"Terrain tile not found: {tile_path_or_region} (searched in {tiles_dir})")

    def _load_tile_data(self) -> None:
        """Parse array layers, resolution, and coordinate grids from the tile file."""
        data = np.load(self.tile_path, allow_pickle=True)

        # Parse height array in METRES [m]
        if "height_m" in data:
            self.height_m: np.ndarray = np.asarray(data["height_m"], dtype=np.float32)
        elif "height" in data:
            self.height_m = np.asarray(data["height"], dtype=np.float32)
        else:
            raise KeyError(f"Tile {self.tile_path} missing 'height_m' or 'height' array.")

        # Parse slope array in DEGREES [deg]
        if "slope_deg" in data:
            self.slope_deg: np.ndarray = np.asarray(data["slope_deg"], dtype=np.float32)
        elif "slope" in data:
            self.slope_deg = np.asarray(data["slope"], dtype=np.float32)
        else:
            # Fallback: calculate slope in degrees from height gradients
            mpp = float(data.get("meters_per_pixel", 5.0))
            gy, gx = np.gradient(self.height_m, mpp)
            self.slope_deg = np.rad2deg(np.arctan(np.hypot(gx, gy))).astype(np.float32)

        self.H, self.W = self.height_m.shape
        self.mpp: float = float(data.get("meters_per_pixel", 5.0))
        self.center_lat_deg: float = float(data.get("center_lat_deg", -89.9))
        self.center_lon_deg: float = float(data.get("center_lon_deg", 0.0))
        self.region: str = str(data.get("region", self.tile_path.stem))

        # Parse optional hazard and PSR masks
        self.hazard: np.ndarray | None = data.get("hazard", None)
        self.psr_mask: np.ndarray | None = data.get("psr_mask", None)
        self.meta: dict[str, Any] = {}
        if "meta" in data:
            raw_meta = data["meta"].item() if hasattr(data["meta"], "item") else str(data["meta"])
            try:
                self.meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
            except Exception:
                self.meta = {}

        # Resolve tile center in global polar stereographic coordinates (metres)
        colat_rad = math.radians(90.0 + self.center_lat_deg)
        r_polar = 2.0 * self.moon_radius_m * math.tan(colat_rad / 2.0)
        lon_rad = math.radians(self.center_lon_deg)
        self.center_x_m: float = float(r_polar * math.sin(lon_rad))
        self.center_y_m: float = float(-r_polar * math.cos(lon_rad))

        # Resolve x_m and y_m grid vectors
        half_w = (self.W - 1) / 2.0 * self.mpp
        half_h = (self.H - 1) / 2.0 * self.mpp

        if "x_m" in data and np.asarray(data["x_m"]).ndim == 1:
            self.x_coords_m: np.ndarray = np.asarray(data["x_m"], dtype=np.float64)
        else:
            xs_local = np.linspace(-half_w, half_w, self.W, dtype=np.float64)
            self.x_coords_m = self.center_x_m + xs_local

        if "y_m" in data and np.asarray(data["y_m"]).ndim == 1:
            self.y_coords_m: np.ndarray = np.asarray(data["y_m"], dtype=np.float64)
        else:
            ys_local = np.linspace(half_h, -half_h, self.H, dtype=np.float64)  # row 0 = north (+y)
            self.y_coords_m = self.center_y_m + ys_local

        # Cache coordinate boundaries in metres [m]
        self.min_x_m: float = float(np.min(self.x_coords_m))
        self.max_x_m: float = float(np.max(self.x_coords_m))
        self.min_y_m: float = float(np.min(self.y_coords_m))
        self.max_y_m: float = float(np.max(self.y_coords_m))

        # Check if local coordinates (centered at 0) were loaded
        self.is_local_frame: bool = abs(self.min_x_m + self.max_x_m) < 1.0 and abs(self.center_x_m) > 100.0

    def _interpolate_layer(
        self,
        grid: np.ndarray,
        x_m: float | np.ndarray,
        y_m: float | np.ndarray
    ) -> float | np.ndarray:
        """
        Fast, continuous bilinear interpolation over the uniform grid.
        Handles both scalar and array inputs. Coordinates in METRES [m].
        """
        x_arr = np.asarray(x_m, dtype=np.float64)
        y_arr = np.asarray(y_m, dtype=np.float64)
        is_scalar = (x_arr.ndim == 0 and y_arr.ndim == 0)
        x_arr = np.atleast_1d(x_arr)
        y_arr = np.atleast_1d(y_arr)

        # Coordinate alignment: handle both global polar-stereographic and local relative coordinates
        if self.is_local_frame and np.any(np.abs(x_arr - self.center_x_m) < (self.max_x_m - self.min_x_m)):
            x_eval = x_arr - self.center_x_m
            y_eval = y_arr - self.center_y_m
        elif not self.is_local_frame and np.any(np.abs(x_arr) < (self.max_x_m - self.min_x_m) / 2.0) and abs(self.center_x_m) > 100.0:
            # Query supplied in local coordinates relative to tile center
            x_eval = x_arr + self.center_x_m
            y_eval = y_arr + self.center_y_m
        else:
            x_eval = x_arr
            y_eval = y_arr

        # Continuous fractional index coordinates
        dx = (self.max_x_m - self.min_x_m) / max(1, self.W - 1)
        dy = (self.max_y_m - self.min_y_m) / max(1, self.H - 1)

        # Col index increases with x
        c_float = (x_eval - self.min_x_m) / dx

        # Row index 0 is at max_y (North), so r increases as y decreases
        if self.y_coords_m[0] > self.y_coords_m[-1]:
            r_float = (self.max_y_m - y_eval) / dy
        else:
            r_float = (y_eval - self.min_y_m) / dy

        # Clamp index floats to grid bounds
        c_clamped = np.clip(c_float, 0.0, float(self.W - 1))
        r_clamped = np.clip(r_float, 0.0, float(self.H - 1))

        # Grid cell corners
        c0 = np.clip(np.floor(c_clamped).astype(np.int64), 0, self.W - 2)
        c1 = c0 + 1
        r0 = np.clip(np.floor(r_clamped).astype(np.int64), 0, self.H - 2)
        r1 = r0 + 1

        # Interpolation weights in [0, 1]
        wx = c_clamped - c0
        wy = r_clamped - r0

        # Bilinear combination
        top = (1.0 - wx) * grid[r0, c0] + wx * grid[r0, c1]
        bottom = (1.0 - wx) * grid[r1, c0] + wx * grid[r1, c1]
        result = (1.0 - wy) * top + wy * bottom

        return float(result[0]) if is_scalar else result

    def ground_height(
        self,
        x_m: float | np.ndarray,
        y_m: float | np.ndarray
    ) -> float | np.ndarray:
        """
        Return the terrain surface ground height in METRES [m] above the lunar
        reference sphere (radius 1,737,400.0 m) at polar-stereographic (x, y).

        Parameters:
            x_m: Polar-stereographic Easting in METRES [m].
            y_m: Polar-stereographic Northing in METRES [m].

        Returns:
            float | np.ndarray: Ground elevation in METRES [m].
        """
        return self._interpolate_layer(self.height_m, x_m, y_m)

    def slope(
        self,
        x_m: float | np.ndarray,
        y_m: float | np.ndarray
    ) -> float | np.ndarray:
        """
        Return the terrain surface slope angle in DEGREES [deg] at polar-stereographic (x, y).

        Parameters:
            x_m: Polar-stereographic Easting in METRES [m].
            y_m: Polar-stereographic Northing in METRES [m].

        Returns:
            float | np.ndarray: Terrain surface slope in DEGREES [deg].
        """
        return self._interpolate_layer(self.slope_deg, x_m, y_m)

    def altitude_above_ground(
        self,
        r_moon_fixed: np.ndarray | list[float] | tuple[float, float, float]
    ) -> float:
        """
        Calculate true altitude of the spacecraft above local ground terrain in METRES [m].

        Formula:
            h_clearance = altitude_above_sphere - ground_height(x, y) [m]

        When the spacecraft makes ground contact, clearance is <= 0.0 m.

        Parameters:
            r_moon_fixed: Spacecraft position in MOON_ME frame [r_x, r_y, r_z] in METRES [m].

        Returns:
            float: True altitude above ground surface in METRES [m].
        """
        x_m, y_m, alt_sphere_m = ps_from_moon_fixed(r_moon_fixed, self.moon_radius_m)
        h_ground_m = float(self.ground_height(x_m, y_m))
        return alt_sphere_m - h_ground_m

    def check_touchdown(
        self,
        r_moon_fixed: np.ndarray | list[float],
        v_moon_fixed: np.ndarray | list[float] | None = None,
        touchdown_threshold_m: float = 0.0,
        max_touchdown_v_mps: float = 2.0,
        max_slope_deg: float = 15.0
    ) -> TouchdownReport:
        """
        Tanush's Touchdown Check Evaluator.

        Evaluates whether the spacecraft has made contact with the lunar terrain,
        and verifies if touchdown dynamics meet landing gear structural limits.

        Parameters:
            r_moon_fixed: Position in MOON_ME frame [r_x, r_y, r_z] in METRES [m].
            v_moon_fixed: Velocity in MOON_ME frame [v_x, v_y, v_z] in METRES PER SECOND [m/s] (optional).
            touchdown_threshold_m: Clearance threshold for contact detection in METRES [m] (default: 0.0 m).
            max_touchdown_v_mps: Maximum allowable vertical descent velocity magnitude in METRES/SECOND [m/s] (default: 2.0 m/s).
            max_slope_deg: Maximum allowable terrain slope for tip-over prevention in DEGREES [deg] (default: 15.0 deg).

        Returns:
            TouchdownReport: Full status report with units documented in docstrings.
        """
        x_m, y_m, alt_sphere_m = ps_from_moon_fixed(r_moon_fixed, self.moon_radius_m)
        h_ground_m = float(self.ground_height(x_m, y_m))
        h_clearance_m = alt_sphere_m - h_ground_m
        t_slope_deg = float(self.slope(x_m, y_m))

        # Allow 0.01 mm numerical tolerance for exact contact
        has_contact = (h_clearance_m <= touchdown_threshold_m + 1e-5)

        v_vert_mps: float | None = None
        v_horiz_mps: float | None = None

        if v_moon_fixed is not None:
            r_vec = np.asarray(r_moon_fixed, dtype=np.float64)
            v_vec = np.asarray(v_moon_fixed, dtype=np.float64)
            r_norm = np.linalg.norm(r_vec)
            if r_norm > 1e-3:
                r_hat = r_vec / r_norm
                # Radial velocity: positive = ascending, negative = descending towards ground
                v_vert_mps = float(np.dot(v_vec, r_hat))
                v_horiz_vec = v_vec - v_vert_mps * r_hat
                v_horiz_mps = float(np.linalg.norm(v_horiz_vec))

        # Assess touchdown safety
        if not has_contact:
            status = "AIRBORNE_DESCENT"
            is_safe = False
        else:
            safe = True
            reasons = []

            if t_slope_deg > max_slope_deg:
                safe = False
                reasons.append(f"HAZARDOUS_SLOPE ({t_slope_deg:.1f} deg > {max_slope_deg:.1f} deg)")

            if v_vert_mps is not None and abs(v_vert_mps) > max_touchdown_v_mps:
                safe = False
                reasons.append(f"EXCESSIVE_VERTICAL_VELOCITY ({abs(v_vert_mps):.2f} m/s > {max_touchdown_v_mps:.2f} m/s)")

            if v_horiz_mps is not None and v_horiz_mps > 0.5:
                safe = False
                reasons.append(f"EXCESSIVE_HORIZONTAL_DRIFT ({v_horiz_mps:.2f} m/s > 0.50 m/s)")

            if safe:
                status = "TOUCHDOWN_NOMINAL"
                is_safe = True
            else:
                status = "TOUCHDOWN_FAILED: " + "; ".join(reasons)
                is_safe = False

        return TouchdownReport(
            contact=has_contact,
            altitude_above_ground_m=h_clearance_m,
            altitude_above_sphere_m=alt_sphere_m,
            ground_height_m=h_ground_m,
            terrain_slope_deg=t_slope_deg,
            polar_stereographic_x_m=x_m,
            polar_stereographic_y_m=y_m,
            vertical_velocity_mps=v_vert_mps,
            horizontal_speed_mps=v_horiz_mps,
            is_safe=is_safe,
            status=status
        )

    def export_to_obj(
        self,
        output_obj_path: str | Path,
        vertical_exaggeration: float = 1.0,
        step: int = 1
    ) -> Path:
        """
        Export terrain tile as a Wavefront OBJ 3D mesh for Basilisk Vizard visualization.

        Geometry units:
        - X: Polar-stereographic Easting in METRES [m]
        - Y: Polar-stereographic Northing in METRES [m]
        - Z: Ground elevation in METRES [m] multiplied by vertical exaggeration.

        Parameters:
            output_obj_path: Path to target .obj file (e.g. 'vizard/terrain_shackleton.obj').
            vertical_exaggeration: Elevation scale multiplier (default: 1.0 = true scale).
            step: Grid subsampling step (default: 1 = full resolution).

        Returns:
            Path: Absolute path to written OBJ file.
        """
        out_path = Path(output_obj_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        rows = range(0, self.H, max(1, step))
        cols = range(0, self.W, max(1, step))
        n_rows = len(rows)
        n_cols = len(cols)

        # Precompute vertices
        sub_h = self.height_m[np.ix_(rows, cols)] * float(vertical_exaggeration)
        sub_x = self.x_coords_m[list(cols)]
        sub_y = self.y_coords_m[list(rows)]

        # Precompute approximate vertex normals
        gy, gx = np.gradient(sub_h, self.mpp * max(1, step))
        normals = np.zeros((n_rows, n_cols, 3), dtype=np.float32)
        normals[:, :, 0] = -gx
        normals[:, :, 1] = -gy
        normals[:, :, 2] = 1.0
        norm_mag = np.linalg.norm(normals, axis=2, keepdims=True)
        normals /= np.maximum(norm_mag, 1e-6)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# Wavefront OBJ export for Basilisk Vizard 3D Visualization\n")
            f.write(f"# Region: {self.region}\n")
            f.write(f"# Dimensions: {self.H} x {self.W} pixels (sampled {n_rows} x {n_cols})\n")
            f.write(f"# Resolution: {self.mpp * step:.2f} m/pixel\n")
            f.write(f"# Vertical Exaggeration: {vertical_exaggeration:.2f}x (Heights in METRES)\n")
            f.write(f"# Extents X [m]: [{self.min_x_m:.2f}, {self.max_x_m:.2f}]\n")
            f.write(f"# Extents Y [m]: [{self.min_y_m:.2f}, {self.max_y_m:.2f}]\n")
            f.write(f"# Elevation range [m]: [{np.min(self.height_m):.2f}, {np.max(self.height_m):.2f}]\n\n")

            # Vertices 'v'
            for r_idx in range(n_rows):
                y_val = sub_y[r_idx]
                for c_idx in range(n_cols):
                    x_val = sub_x[c_idx]
                    z_val = sub_h[r_idx, c_idx]
                    f.write(f"v {x_val:.3f} {y_val:.3f} {z_val:.3f}\n")

            # Texture coordinates 'vt'
            for r_idx in range(n_rows):
                v_uv = 1.0 - (r_idx / max(1, n_rows - 1))
                for c_idx in range(n_cols):
                    u_uv = c_idx / max(1, n_cols - 1)
                    f.write(f"vt {u_uv:.4f} {v_uv:.4f}\n")

            # Vertex normals 'vn'
            for r_idx in range(n_rows):
                for c_idx in range(n_cols):
                    nx, ny, nz = normals[r_idx, c_idx]
                    f.write(f"vn {nx:.4f} {ny:.4f} {nz:.4f}\n")

            # Faces 'f' (1-indexed: v/vt/vn)
            f.write("\ng terrain_mesh\n")
            for r in range(n_rows - 1):
                for c in range(n_cols - 1):
                    # Indices for quad corners
                    # top-left: (r, c), top-right: (r, c+1)
                    # bottom-left: (r+1, c), bottom-right: (r+1, c+1)
                    v_tl = r * n_cols + c + 1
                    v_tr = r * n_cols + (c + 1) + 1
                    v_bl = (r + 1) * n_cols + c + 1
                    v_br = (r + 1) * n_cols + (c + 1) + 1

                    # Write two counter-clockwise triangles
                    f.write(f"f {v_tl}/{v_tl}/{v_tl} {v_bl}/{v_bl}/{v_bl} {v_tr}/{v_tr}/{v_tr}\n")
                    f.write(f"f {v_tr}/{v_tr}/{v_tr} {v_bl}/{v_bl}/{v_bl} {v_br}/{v_br}/{v_br}\n")

        print(f"[OBJ] Exported terrain mesh to {out_path} ({n_rows * n_cols} vertices, vertical exaggeration {vertical_exaggeration}x)")
        return out_path


# ==============================================================================
# 3. Global / Module-Level Functional API
# ==============================================================================

# Module-level default active terrain instance
_ACTIVE_TERRAIN: LunarTerrain | None = None

def load_tile(tile_path_or_region: str | Path, tiles_dir: str | Path = "data/tiles") -> LunarTerrain:
    """
    Load a terrain tile into the active module context.

    Parameters:
        tile_path_or_region: Path to .npz file or region name.
        tiles_dir: Directory containing tile files (default: 'data/tiles').

    Returns:
        LunarTerrain: Loaded terrain model.
    """
    global _ACTIVE_TERRAIN
    _ACTIVE_TERRAIN = LunarTerrain(tile_path_or_region, tiles_dir=tiles_dir)
    return _ACTIVE_TERRAIN

def _ensure_active_terrain() -> LunarTerrain:
    global _ACTIVE_TERRAIN
    if _ACTIVE_TERRAIN is None:
        # Default load demo_craters or shackleton tile
        for candidate in ["data/tiles/demo_craters.npz", "data/tiles/shackleton.npz"]:
            if Path(candidate).exists():
                _ACTIVE_TERRAIN = LunarTerrain(candidate)
                break
        if _ACTIVE_TERRAIN is None:
            raise RuntimeError("No active terrain loaded. Call basilisk_mods.lunar_terrain.load_tile('<region>') first.")
    return _ACTIVE_TERRAIN

def ground_height(x_m: float | np.ndarray, y_m: float | np.ndarray) -> float | np.ndarray:
    """
    Return local terrain elevation in METRES [m] above the reference lunar sphere
    (radius 1,737,400.0 m) at polar-stereographic (x, y).

    Parameters:
        x_m: Polar-stereographic Easting in METRES [m].
        y_m: Polar-stereographic Northing in METRES [m].

    Returns:
        float | np.ndarray: Ground height in METRES [m].
    """
    return _ensure_active_terrain().ground_height(x_m, y_m)

def slope(x_m: float | np.ndarray, y_m: float | np.ndarray) -> float | np.ndarray:
    """
    Return local terrain slope angle in DEGREES [deg] at polar-stereographic (x, y).

    Parameters:
        x_m: Polar-stereographic Easting in METRES [m].
        y_m: Polar-stereographic Northing in METRES [m].

    Returns:
        float | np.ndarray: Terrain slope in DEGREES [deg].
    """
    return _ensure_active_terrain().slope(x_m, y_m)

def altitude_above_ground(r_moon_fixed: np.ndarray | list[float]) -> float:
    """
    Return true spacecraft altitude above local ground terrain in METRES [m].
    Computed as: altitude_above_sphere - ground_height(x, y).

    Parameters:
        r_moon_fixed: Cartesian position in MOON_ME frame [r_x, r_y, r_z] in METRES [m].

    Returns:
        float: True altitude above ground surface in METRES [m].
    """
    return _ensure_active_terrain().altitude_above_ground(r_moon_fixed)

def check_touchdown(
    r_moon_fixed: np.ndarray | list[float],
    v_moon_fixed: np.ndarray | list[float] | None = None,
    touchdown_threshold_m: float = 0.0,
    max_touchdown_v_mps: float = 2.0,
    max_slope_deg: float = 15.0
) -> TouchdownReport:
    """
    Tanush's Touchdown Check Evaluator (Agreed interface).

    Parameters:
        r_moon_fixed: Spacecraft position in MOON_ME frame [r_x, r_y, r_z] in METRES [m].
        v_moon_fixed: Spacecraft velocity in MOON_ME frame [v_x, v_y, v_z] in METRES/SECOND [m/s].
        touchdown_threshold_m: Contact clearance threshold in METRES [m] (default: 0.0 m).
        max_touchdown_v_mps: Maximum safe vertical velocity magnitude in METRES/SECOND [m/s] (default: 2.0 m/s).
        max_slope_deg: Maximum safe slope in DEGREES [deg] (default: 15.0 deg).

    Returns:
        TouchdownReport: NamedTuple containing contact flag, clearance, slope, velocity, and safety.
    """
    return _ensure_active_terrain().check_touchdown(
        r_moon_fixed=r_moon_fixed,
        v_moon_fixed=v_moon_fixed,
        touchdown_threshold_m=touchdown_threshold_m,
        max_touchdown_v_mps=max_touchdown_v_mps,
        max_slope_deg=max_slope_deg
    )

# Tanush's touchdown check alias
touchdown_check = check_touchdown

def export_to_obj(
    tile_path_or_terrain: str | Path | LunarTerrain,
    output_obj_path: str | Path,
    vertical_exaggeration: float = 1.0,
    step: int = 1
) -> Path:
    """
    Export a terrain tile to Wavefront OBJ format for Basilisk Vizard.

    Parameters:
        tile_path_or_terrain: Terrain tile file path, region name, or LunarTerrain instance.
        output_obj_path: Destination path for OBJ file (e.g. 'vizard/terrain_demo_craters.obj').
        vertical_exaggeration: Elevation vertical scaling factor (default: 1.0 = heights x 1).
        step: Subsampling stride (default: 1 = full resolution).

    Returns:
        Path: Path to saved OBJ file.
    """
    if isinstance(tile_path_or_terrain, LunarTerrain):
        terrain = tile_path_or_terrain
    else:
        terrain = LunarTerrain(tile_path_or_terrain)
    return terrain.export_to_obj(
        output_obj_path=output_obj_path,
        vertical_exaggeration=vertical_exaggeration,
        step=step
    )


# ==============================================================================
# 4. Command Line Interface (CLI)
# ==============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lunar Terrain Helper & OBJ Exporter for Basilisk Scenarios")
    parser.add_argument("--tile", default="demo_craters", help="Tile name or path (default: demo_craters)")
    parser.add_argument("--export", default=None, help="Output path for Wavefront OBJ export")
    parser.add_argument("--vertical-exaggeration", type=float, default=1.0, help="Vertical exaggeration multiplier (default: 1.0)")
    parser.add_argument("--step", type=int, default=1, help="Mesh subsampling stride (default: 1)")
    args = parser.parse_args()

    terrain = LunarTerrain(args.tile)
    print(f"Loaded terrain '{terrain.region}': shape={terrain.H}x{terrain.W}, mpp={terrain.mpp} m/px")
    print(f"Height range: [{np.min(terrain.height_m):.2f} m, {np.max(terrain.height_m):.2f} m]")
    print(f"Slope range: [{np.min(terrain.slope_deg):.2f} deg, {np.max(terrain.slope_deg):.2f} deg]")

    if args.export:
        terrain.export_to_obj(args.export, vertical_exaggeration=args.vertical_exaggeration, step=args.step)
