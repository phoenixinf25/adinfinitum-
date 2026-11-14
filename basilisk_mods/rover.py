"""
basilisk_mods/rover.py
======================
Lunar Surface Rover Mobility, Power & Comms Kinematics Model.

Simulates a ~25 kg Pragyan / VIPER class lunar exploration rover operating from
a lander base station on real lunar DEM terrain (Spec §4.3).

Features:
- Kinematic surface motion at strictly 0.01 m/s (1 cm/s) across real DEM topography.
- Autonomous waypoint navigation through science/ice targets and return to lander.
- Slope hazard enforcement: stops vehicle if surface slope exceeds configured limit.
- Power subsystem: 50 W solar array with local sun illumination fraction, drive and
  standby power loads, and battery storage capable of traversing into and out of shadow.
- RF Communications Line-of-Sight (LOS): terrain ray-casting between rover mast antenna
  and lander base station antenna.
- Flight log generation conforming to runs/basilisk/rover_<id>.csv.
- Vizard trajectory export with playback time-acceleration support.

UNITS (Strictly Enforced):
- Distances, elevations, clearances: METRES [m]
- Angles, slopes, headings: DEGREES [deg] or RADIANS [rad] (explicitly indicated)
- Speeds, velocities: METRES PER SECOND [m/s]
- Power: WATTS [W]
- Energy: WATT-HOURS [Wh]
- Time: SECONDS [s]

Context: Spec §4.3 Rover Mobility & Science Prospecting Architecture (Arnav).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .lunar_terrain import LunarTerrain, R_MOON_M


@dataclass
class RoverConfig:
    """
    Configuration parameters for the 25 kg lunar exploration rover.
    All physical units are documented in parameter docstrings.
    """
    rover_id: str = "rover_01"
    mass_kg: float = 25.0                     # Vehicle total mass in KILOGRAMS [kg]
    speed_mps: float = 0.01                   # Nominal traverse speed in METRES/SECOND [m/s] (1 cm/s)
    max_slope_deg: float = 15.0               # Maximum safe climbable slope in DEGREES [deg]
    solar_rated_power_w: float = 50.0         # Solar array rated output at 100% illumination in WATTS [W]
    drive_power_w: float = 30.0               # Electrical power consumed while driving in WATTS [W]
    standby_power_w: float = 10.0             # Standby / payload baseline power consumed in WATTS [W]
    battery_capacity_wh: float = 120.0        # Total battery energy capacity in WATT-HOURS [Wh]
    initial_battery_wh: float = 120.0         # Starting battery charge in WATT-HOURS [Wh]
    min_battery_wh: float = 5.0               # Minimum emergency reserve in WATT-HOURS [Wh]
    rover_antenna_height_m: float = 0.8       # Rover comms antenna mast height in METRES [m]
    lander_antenna_height_m: float = 2.5      # Lander high-gain antenna mast height in METRES [m]
    waypoint_reach_radius_m: float = 1.0      # Proximity threshold to achieve waypoint in METRES [m]


@dataclass
class RoverState:
    """
    Instantaneous telemetry state of the lunar rover.
    All distance units are in metres [m], angles in degrees [deg], power in W, energy in Wh.
    """
    time_s: float                             # Mission elapsed time in SECONDS [s]
    x_m: float                                # Polar-stereographic Easting in METRES [m]
    y_m: float                                # Polar-stereographic Northing in METRES [m]
    z_m: float                                # Surface elevation above lunar reference sphere in METRES [m]
    heading_deg: float                        # Azimuth heading angle in DEGREES [deg] (0 = North/+Y, 90 = East/+X)
    speed_mps: float                          # Instantaneous drive speed in METRES/SECOND [m/s]
    slope_deg: float                          # Terrain slope angle at current position in DEGREES [deg]
    battery_wh: float                         # Battery stored energy in WATT-HOURS [Wh]
    battery_pct: float                        # Battery State of Charge in PERCENT [%]
    sun_fraction: float                       # Sunlight illumination fraction [0.0 = full shadow, 1.0 = direct sunlight]
    solar_power_w: float                      # Solar panel generated power in WATTS [W]
    power_draw_w: float                       # Current electrical power demand in WATTS [W]
    net_power_w: float                        # Net battery charge/discharge rate in WATTS [W]
    has_los_link: bool                        # Line-of-sight RF link to lander established (True/False)
    distance_to_lander_m: float               # Distance back to lander base station in METRES [m]
    waypoint_idx: int                         # Target waypoint index currently being pursued
    is_driving: bool                          # True if wheels are active and vehicle is moving
    is_stopped_slope: bool                    # True if halted due to excessive terrain slope
    is_returned: bool                         # True if completed all waypoints and back at lander
    status: str                               # High-level operational status string


class LunarRover:
    """
    Kinematic lunar rover simulator on real DEM topography.
    """

    def __init__(
        self,
        config: RoverConfig,
        terrain: LunarTerrain,
        lander_xy_m: tuple[float, float],
        waypoints_xy_m: list[tuple[float, float]],
        sun_fraction_fn: Callable[[float, float, float], float] | None = None
    ) -> None:
        """
        Initialize the rover at the lander position with an assigned waypoint route.

        Parameters:
            config: Rover physical and subsystem parameters.
            terrain: LunarTerrain instance providing ground height and slope queries.
            lander_xy_m: (x, y) location of the lander base station in METRES [m].
            waypoints_xy_m: List of (x, y) coordinate tuples in METRES [m] (the final waypoint should be the lander).
            sun_fraction_fn: Optional light-field query callback fn(x_m, y_m, time_s) -> float [0..1].
        """
        self.config: RoverConfig = config
        self.terrain: LunarTerrain = terrain
        self.lander_x_m: float = float(lander_xy_m[0])
        self.lander_y_m: float = float(lander_xy_m[1])
        self.lander_z_m: float = float(self.terrain.ground_height(self.lander_x_m, self.lander_y_m))

        self.waypoints: list[tuple[float, float]] = [
            (float(w[0]), float(w[1])) for w in waypoints_xy_m
        ]
        if not self.waypoints:
            # Default waypoint: stay at lander
            self.waypoints = [(self.lander_x_m, self.lander_y_m)]

        self.sun_fraction_fn = sun_fraction_fn

        # Initial state setup
        self.time_s: float = 0.0
        self.x_m: float = self.lander_x_m
        self.y_m: float = self.lander_y_m
        self.z_m: float = self.lander_z_m
        self.heading_deg: float = 0.0
        self.battery_wh: float = float(self.config.initial_battery_wh)
        self.waypoint_idx: int = 0
        self.is_driving: bool = True
        self.is_stopped_slope: bool = False
        self.is_returned: bool = False
        self.total_distance_m: float = 0.0

        # Log history
        self.telemetry_history: list[RoverState] = []
        self._record_telemetry(status="MISSION_START")

    @property
    def distance_to_lander_m(self) -> float:
        """Current distance from the rover back to the lander in METRES [m]."""
        return math.hypot(self.x_m - self.lander_x_m, self.y_m - self.lander_y_m)

    def query_sun_fraction(self, x_m: float, y_m: float, time_s: float) -> float:
        """
        Query local surface solar illumination fraction at (x, y) in range [0.0, 1.0].
        If a custom light-field callback is provided, evaluates it; otherwise uses the
        terrain tile permanently shadowed region (PSR) mask.
        """
        if self.sun_fraction_fn is not None:
            return float(np.clip(self.sun_fraction_fn(x_m, y_m, time_s), 0.0, 1.0))

        # Check tile's PSR mask if available
        if self.terrain.psr_mask is not None:
            # Check if (x, y) falls within a permanently shadowed crater floor
            is_psr = self.terrain._interpolate_layer(self.terrain.psr_mask.astype(np.float32), x_m, y_m) > 0.5
            return 0.0 if is_psr else 1.0

        # Default fallback: constant sunlit terrain
        return 1.0

    def check_line_of_sight(
        self,
        rover_x_m: float,
        rover_y_m: float,
        rover_z_m: float,
        num_samples: int = 40
    ) -> bool:
        """
        Determine if direct line-of-sight (LOS) RF communications exist between the
        rover antenna mast and the lander base station antenna over the intervening terrain.

        Parameters:
            rover_x_m: Rover Easting in METRES [m].
            rover_y_m: Rover Northing in METRES [m].
            rover_z_m: Rover ground elevation in METRES [m].
            num_samples: Number of terrain profile ray-cast evaluation steps.

        Returns:
            bool: True if RF sightline is clear, False if occluded by lunar terrain.
        """
        # Antenna apex coordinates in 3D
        p_lander = (self.lander_x_m, self.lander_y_m, self.lander_z_m + self.config.lander_antenna_height_m)
        p_rover = (rover_x_m, rover_y_m, rover_z_m + self.config.rover_antenna_height_m)

        dist_2d = math.hypot(rover_x_m - self.lander_x_m, rover_y_m - self.lander_y_m)
        if dist_2d < 2.0:
            # Proximity to lander always maintains direct communications
            return True

        # Interpolate ray line in 3D and test for terrain clearance
        s_vals = np.linspace(0.05, 0.95, max(10, num_samples))
        for s in s_vals:
            ray_x = p_lander[0] + s * (p_rover[0] - p_lander[0])
            ray_y = p_lander[1] + s * (p_rover[1] - p_lander[1])
            ray_z = p_lander[2] + s * (p_rover[2] - p_lander[2])

            terrain_z = float(self.terrain.ground_height(ray_x, ray_y))
            # Ray is occluded if it passes below the local ground surface
            if ray_z < terrain_z - 0.02:
                return False

        return True

    def step(self, dt_s: float) -> RoverState:
        """
        Advance the rover kinematics, power, and communications by dt_s seconds.

        Parameters:
            dt_s: Simulation integration timestep in SECONDS [s] (e.g. 10.0 to 60.0 s).

        Returns:
            RoverState: Telemetry state snapshot.
        """
        dt_s = max(1e-3, float(dt_s))
        self.time_s += dt_s

        # Determine target waypoint
        if self.waypoint_idx < len(self.waypoints):
            target_x, target_y = self.waypoints[self.waypoint_idx]
        else:
            target_x, target_y = (self.lander_x_m, self.lander_y_m)

        dist_to_target = math.hypot(target_x - self.x_m, target_y - self.y_m)

        # Check if current waypoint is reached
        if dist_to_target <= self.config.waypoint_reach_radius_m:
            if self.waypoint_idx < len(self.waypoints) - 1:
                self.waypoint_idx += 1
                target_x, target_y = self.waypoints[self.waypoint_idx]
                dist_to_target = math.hypot(target_x - self.x_m, target_y - self.y_m)
            elif self.waypoint_idx == len(self.waypoints) - 1:
                # Returned to final waypoint (lander)
                dist_to_lander = math.hypot(self.x_m - self.lander_x_m, self.y_m - self.lander_y_m)
                if dist_to_lander <= self.config.waypoint_reach_radius_m:
                    self.is_returned = True
                    self.is_driving = False

        # Current terrain slope at rover position
        current_slope_deg = float(self.terrain.slope(self.x_m, self.y_m))

        # Enforce slope hazard limit
        if current_slope_deg > self.config.max_slope_deg:
            self.is_stopped_slope = True
            self.is_driving = False
            status = f"HALTED_STEEP_SLOPE ({current_slope_deg:.1f} deg > {self.config.max_slope_deg:.1f} deg)"
        elif self.battery_wh <= self.config.min_battery_wh:
            self.is_driving = False
            status = "HALTED_LOW_BATTERY"
        elif self.is_returned:
            self.is_driving = False
            status = "MISSION_COMPLETE_RETURNED_TO_LANDER"
        else:
            self.is_stopped_slope = False
            self.is_driving = True
            status = f"DRIVING_TO_WP_{self.waypoint_idx + 1}"

        # Kinematic translation (strictly 0.01 m/s = 1 cm/s)
        actual_speed_mps = self.config.speed_mps if self.is_driving else 0.0
        if self.is_driving and dist_to_target > 1e-4:
            # Azimuth heading angle in radians
            heading_rad = math.atan2(target_x - self.x_m, target_y - self.y_m)
            self.heading_deg = (math.degrees(heading_rad) + 360.0) % 360.0

            step_dist_m = min(actual_speed_mps * dt_s, dist_to_target)
            dx = step_dist_m * math.sin(heading_rad)
            dy = step_dist_m * math.cos(heading_rad)

            self.x_m += dx
            self.y_m += dy
            self.total_distance_m += step_dist_m

        # Update elevation from real DEM terrain
        self.z_m = float(self.terrain.ground_height(self.x_m, self.y_m))

        # Power subsystem computation
        sun_fraction = self.query_sun_fraction(self.x_m, self.y_m, self.time_s)
        solar_power_w = self.config.solar_rated_power_w * sun_fraction

        power_draw_w = self.config.drive_power_w if self.is_driving else self.config.standby_power_w
        net_power_w = solar_power_w - power_draw_w

        # Update battery stored energy [Wh]
        delta_energy_wh = net_power_w * (dt_s / 3600.0)
        self.battery_wh = float(np.clip(
            self.battery_wh + delta_energy_wh,
            0.0,
            self.config.battery_capacity_wh
        ))

        # Check line-of-sight RF link
        has_link = self.check_line_of_sight(self.x_m, self.y_m, self.z_m)

        state = self._record_telemetry(
            speed_mps=actual_speed_mps,
            slope_deg=current_slope_deg,
            sun_fraction=sun_fraction,
            solar_power_w=solar_power_w,
            power_draw_w=power_draw_w,
            net_power_w=net_power_w,
            has_link=has_link,
            status=status
        )
        return state

    def _record_telemetry(
        self,
        speed_mps: float = 0.0,
        slope_deg: float = 0.0,
        sun_fraction: float = 1.0,
        solar_power_w: float = 0.0,
        power_draw_w: float = 0.0,
        net_power_w: float = 0.0,
        has_link: bool = True,
        status: str = "INIT"
    ) -> RoverState:
        dist_to_lander = math.hypot(self.x_m - self.lander_x_m, self.y_m - self.lander_y_m)
        bat_pct = (self.battery_wh / max(1e-3, self.config.battery_capacity_wh)) * 100.0

        state = RoverState(
            time_s=self.time_s,
            x_m=self.x_m,
            y_m=self.y_m,
            z_m=self.z_m,
            heading_deg=self.heading_deg,
            speed_mps=speed_mps,
            slope_deg=slope_deg,
            battery_wh=self.battery_wh,
            battery_pct=bat_pct,
            sun_fraction=sun_fraction,
            solar_power_w=solar_power_w,
            power_draw_w=power_draw_w,
            net_power_w=net_power_w,
            has_los_link=has_link,
            distance_to_lander_m=dist_to_lander,
            waypoint_idx=self.waypoint_idx,
            is_driving=self.is_driving,
            is_stopped_slope=self.is_stopped_slope,
            is_returned=self.is_returned,
            status=status
        )
        self.telemetry_history.append(state)
        return state

    def export_csv_log(self, output_csv_path: str | Path) -> Path:
        """
        Save the simulation flight telemetry to CSV conforming to runs/basilisk/rover_<id>.csv.

        Parameters:
            output_csv_path: Target CSV file path.

        Returns:
            Path: Absolute path to written log file.
        """
        out_path = Path(output_csv_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "time_s",
            "x_m",
            "y_m",
            "z_m",
            "battery_wh",
            "battery_pct",
            "sun_fraction",
            "link_los",
            "speed_mps",
            "slope_deg",
            "distance_to_lander_m",
            "waypoint_idx",
            "status"
        ]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in self.telemetry_history:
                writer.writerow({
                    "time_s": f"{s.time_s:.1f}",
                    "x_m": f"{s.x_m:.3f}",
                    "y_m": f"{s.y_m:.3f}",
                    "z_m": f"{s.z_m:.3f}",
                    "battery_wh": f"{s.battery_wh:.3f}",
                    "battery_pct": f"{s.battery_pct:.1f}",
                    "sun_fraction": f"{s.sun_fraction:.2f}",
                    "link_los": "1" if s.has_los_link else "0",
                    "speed_mps": f"{s.speed_mps:.4f}",
                    "slope_deg": f"{s.slope_deg:.2f}",
                    "distance_to_lander_m": f"{s.distance_to_lander_m:.2f}",
                    "waypoint_idx": s.waypoint_idx,
                    "status": s.status
                })

        print(f"[CSV Log] Saved {len(self.telemetry_history)} records to {out_path}")
        return out_path


def export_rover_vizard_mesh(output_obj_path: str | Path = "vizard/rover_body.obj") -> Path:
    """
    Generate a 3D Wavefront OBJ mesh of the ~25 kg Pragyan/VIPER class lunar rover
    for Basilisk Vizard 3D visualization.

    Parameters:
        output_obj_path: Path where rover 3D OBJ file is saved.

    Returns:
        Path: Path to created OBJ model.
    """
    out_path = Path(output_obj_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Simplified box chassis + solar panel plane + mast geometry (all dimensions in metres)
    # Rover scale: length 0.9 m, width 0.75 m, height 0.5 m
    lx, ly, lz = 0.45, 0.35, 0.15

    vertices = [
        # Chassis box (8 vertices)
        (-lx, -ly, 0.10), (lx, -ly, 0.10), (lx, ly, 0.10), (-lx, ly, 0.10),
        (-lx, -ly, 0.10 + 2 * lz), (lx, -ly, 0.10 + 2 * lz), (lx, ly, 0.10 + 2 * lz), (-lx, ly, 0.10 + 2 * lz),
        # Solar panel top sheet (4 vertices)
        (-lx * 1.1, -ly * 1.1, 0.10 + 2 * lz + 0.02),
        (lx * 1.1, -ly * 1.1, 0.10 + 2 * lz + 0.02),
        (lx * 1.1, ly * 1.1, 0.10 + 2 * lz + 0.02),
        (-lx * 1.1, ly * 1.1, 0.10 + 2 * lz + 0.02),
        # Antenna mast top (1 vertex)
        (0.0, 0.0, 0.80)
    ]

    faces = [
        # Chassis bottom
        (1, 4, 3), (1, 3, 2),
        # Chassis top
        (5, 6, 7), (5, 7, 8),
        # Chassis sides
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 4, 8), (3, 8, 7),
        (4, 1, 5), (4, 5, 8),
        # Solar panel
        (9, 10, 11), (9, 11, 12),
        # Mast pyramid
        (13, 5, 6), (13, 6, 7), (13, 7, 8), (13, 8, 5)
    ]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Wavefront OBJ model for Basilisk Vizard: 25 kg Lunar Rover\n")
        f.write("# Dimensions: 0.9m x 0.75m x 0.8m (mass ~25 kg, Pragyan/VIPER class)\n\n")
        for v in vertices:
            f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
        f.write("\ng rover_mesh\n")
        for fc in faces:
            f.write(f"f {fc[0]} {fc[1]} {fc[2]}\n")

    print(f"[Vizard OBJ] Created rover 3D body model at {out_path}")
    return out_path
