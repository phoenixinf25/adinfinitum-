#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Mission constants for the lunar rover simulation.

Every value in this file is an **ASSUMPTION** unless a comment says otherwise.
No rover specification sheet was available when this file was written, so the
numbers describe a generic small solar-powered rover (Pragyan class, as in
``data/ice/README.md``). Replace them with the real rover specification as
soon as it exists; nothing else in the package hard-codes a physical value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SECONDS_PER_DAY = 86400.0  # [s]


@dataclass(frozen=True)
class RoverConfig:
    """Rover hardware and operating limits (ASSUMED, see module docstring)."""

    mass_kg: float = 25.0  # [kg] Pragyan class, from data/ice/README.md
    max_speed_m_s: float = 0.01  # [m/s] ~1 cm/s, from data/ice/README.md
    max_turn_rate_rad_s: float = 0.05  # [rad/s] assumed
    battery_capacity_wh: float = 350.0  # [Wh] assumed placeholder, sets how deep a dip into shadow is affordable
    battery_initial_frac: float = 0.9  # [-] assumed
    solar_peak_w: float = 50.0  # [W] ~50 W array, from data/ice/README.md
    load_sleep_w: float = 2.0  # [W] assumed
    load_hold_w: float = 6.0  # [W] assumed
    load_drive_w: float = 15.0  # [W] assumed
    load_drill_w: float = 30.0  # [W] assumed
    heater_w: float = 6.0  # [W] survival heater, applied inside a PSR (assumed)
    slope_limit_deg: float = 20.0  # [deg] rover refuses to drive onto steeper ground (assumed)
    slope_derate_start_deg: float = 8.0  # [deg] speed falls linearly above this slope (assumed)
    hazard_block: float = 0.95  # [-] cells at or above this hazard value are blocked (assumed)
    drill_duration_s: float = 900.0  # [s] assumed
    sample_radius_m: float = 6.0  # [m] rover must be this close to a target to sample it
    mast_height_m: float = 1.0  # [m] camera and antenna height above ground


@dataclass(frozen=True)
class SkyConfig:
    """Simplified Sun and Earth model (MODELLED stand-in, not SPICE).

    The validated SPICE/Horizons light model lives in the Adinfinitium
    ``worldmodel/light`` package. This stand-in keeps the demo self-contained
    and is labelled MODELLED in the user interface.
    """

    sun_elevation_deg: float = 1.5  # [deg] near-polar Sun stays within ~1.5 deg of the horizon
    sun_azimuth_start_deg: float = 20.0  # [deg] azimuth at t = 0, clockwise from grid +y
    synodic_period_s: float = 29.53 * SECONDS_PER_DAY  # [s] one lunar day
    earth_azimuth_deg: float = 0.0  # [deg] grid +y points along the 0 deg meridian toward the near side (convention verified on Site01)
    earth_libration_amp_deg: float = 6.0  # [deg] Earth elevation swings by this much
    earth_libration_period_s: float = 27.32 * SECONDS_PER_DAY  # [s] sidereal month
    horizon_bins: int = 36  # [-] azimuth bins for the horizon maps
    horizon_range_m: float = 1000.0  # [m] how far terrain is allowed to shade a point


@dataclass(frozen=True)
class MissionConfig:
    """Mission-level settings."""

    region: str = "lola5m_site01"  # falls back to the generated "rover_demo" tile if the file is absent
    mission_duration_s: float = 14.0 * SECONDS_PER_DAY  # [s] ends the episode
    physics_dt_s: float = 5.0  # [s] integration step
    decision_dt_s: float = 30.0  # [s] time between policy decisions
    n_targets: int = 8  # [-] number of candidate ice-evidence sites
    min_target_spacing_m: float = 60.0  # [m] minimum distance between sites
    patch_size: int = 15  # [-] observation patch width in cells
    patch_spacing_m: float = 10.0  # [m] distance between observation patch cells
    rover: RoverConfig = field(default_factory=RoverConfig)
    sky: SkyConfig = field(default_factory=SkyConfig)
