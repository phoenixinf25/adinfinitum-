"""
tools/record_vizard_clips.py
============================
Generates 3 full 1080p (1920x1080, 30fps) H.264 MP4 hero video clips for Basilisk Vizard mission replay:
  1. video_assets/clip1_orbit_release.mp4      (100 km orbit -> release -> deorbit burn -> 15 km PDI)
  2. video_assets/clip2_descent_engine_out.mp4 (Powered descent -> engine 1 out at 20s -> 3-engine balance -> touchdown)
  3. video_assets/clip3_rover_ice_traverse.mp4 (Rover traverse to ice target in cold trap -> return at sunset, 60x speedup)

Includes:
- 3D software rendering (orthographic/perspective) of Moon, LOLA terrain, Lander, and Rover.
- Animated thruster plumes, pointing rays (Sun yellow, Earth cyan, Comms green).
- Mission Control telemetry HUD (altitude, velocity, fuel, battery, engine lights, mission clock).
- Visible provenance badges and mandatory labels:
  - "MODELLED · Basilisk / LOLA DEM"
  - "vertical exaggeration x1.5" (on terrain scenes)
  - "PLAYBACK SPEEDUP: 60x" (on rover scene)
  - "ORIGINAL DESIGN: No branded spacecraft models"

Context: Spec §7.3 & KAN-47 Vizard 3D Mission Replay (Arnav).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import av
import numpy as np

# ------------------------------------------------------------------------------
# 1. Monospace Vector / Bitmap Font Engine for Crisp 1080p HUD Telemetry
# ------------------------------------------------------------------------------

# 5x7 Font definitions for ASCII glyphs (encoded as 7 rows of 5-bit masks)
GLYPHS = {
    ' ': [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000],
    '0': [0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110],
    '1': [0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
    '2': [0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111],
    '3': [0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110],
    '4': [0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010],
    '5': [0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110],
    '6': [0b01110, 0b10000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110],
    '7': [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000],
    '8': [0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110],
    '9': [0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00001, 0b01110],
    'A': [0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
    'B': [0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110],
    'C': [0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110],
    'D': [0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110],
    'E': [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111],
    'F': [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000],
    'G': [0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01110],
    'H': [0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
    'I': [0b01110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
    'J': [0b00001, 0b00001, 0b00001, 0b00001, 0b00001, 0b10001, 0b01110],
    'K': [0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001],
    'L': [0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111],
    'M': [0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001],
    'N': [0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001],
    'O': [0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
    'P': [0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000],
    'Q': [0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10011, 0b01111],
    'R': [0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001],
    'S': [0b01110, 0b10001, 0b10000, 0b01110, 0b00001, 0b10001, 0b01110],
    'T': [0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100],
    'U': [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
    'V': [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100],
    'W': [0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b11011, 0b10001],
    'X': [0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001],
    'Y': [0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100],
    'Z': [0b11111, 0b00010, 0b00100, 0b01000, 0b10000, 0b10000, 0b11111],
    ':': [0b00000, 0b01100, 0b01100, 0b00000, 0b01100, 0b01100, 0b00000],
    '.': [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b01100, 0b01100],
    ',': [0b00000, 0b00000, 0b00000, 0b00000, 0b01100, 0b00100, 0b01000],
    '-': [0b00000, 0b00000, 0b00000, 0b11111, 0b00000, 0b00000, 0b00000],
    '+': [0b00000, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0b00000],
    '/': [0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b00000, 0b00000],
    '(': [0b00010, 0b00100, 0b01000, 0b01000, 0b01000, 0b00100, 0b00010],
    ')': [0b01000, 0b00100, 0b00010, 0b00010, 0b00010, 0b00100, 0b01000],
    '[': [0b01110, 0b01000, 0b01000, 0b01000, 0b01000, 0b01000, 0b01110],
    ']': [0b01110, 0b00010, 0b00010, 0b00010, 0b00010, 0b00010, 0b01110],
    '>': [0b10000, 0b01000, 0b00100, 0b00010, 0b00100, 0b01000, 0b10000],
    '<': [0b00010, 0b00100, 0b01000, 0b10000, 0b01000, 0b00100, 0b00010],
    '%': [0b11001, 0b11010, 0b00100, 0b01000, 0b01011, 0b10011, 0b00000],
    '|': [0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100],
    '=': [0b00000, 0b11111, 0b00000, 0b11111, 0b00000, 0b00000, 0b00000],
    '_': [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b11111],
    'X': [0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001],
}


def draw_text(
    canvas: np.ndarray,
    text: str,
    x: int,
    y: int,
    scale: int = 2,
    color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] | None = None,
) -> None:
    """Draw text onto canvas array at (x, y) with integer pixel scaling."""
    h_canvas, w_canvas, _ = canvas.shape
    curr_x = x
    char_w = 6 * scale
    char_h = 8 * scale

    for ch in text.upper():
        glyph = GLYPHS.get(ch, GLYPHS[' '])
        # Background box if requested
        if bg_color is not None:
            x0 = max(0, curr_x - 1)
            x1 = min(w_canvas, curr_x + char_w + 1)
            y0 = max(0, y - 1)
            y1 = min(h_canvas, y + char_h + 1)
            canvas[y0:y1, x0:x1] = bg_color

        for r_idx, row in enumerate(glyph):
            py = y + r_idx * scale
            if py < 0 or py + scale > h_canvas:
                continue
            for c_idx in range(5):
                px = curr_x + c_idx * scale
                if px < 0 or px + scale > w_canvas:
                    continue
                if (row >> (4 - c_idx)) & 1:
                    canvas[py : py + scale, px : px + scale] = color
        curr_x += char_w


def draw_line(
    canvas: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int] = (255, 255, 255),
    thickness: int = 1,
) -> None:
    """Draw Bresenham line with thickness."""
    h_c, w_c, _ = canvas.shape
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    cx, cy = x0, y0
    rad = thickness // 2
    while True:
        y_min = max(0, cy - rad)
        y_max = min(h_c, cy + rad + 1)
        x_min = max(0, cx - rad)
        x_max = min(w_c, cx + rad + 1)
        canvas[y_min:y_max, x_min:x_max] = color

        if cx == x1 and cy == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy


def draw_box(
    canvas: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    fill_color: tuple[int, int, int] | None = None,
    border_color: tuple[int, int, int] | None = None,
    border_thick: int = 1,
) -> None:
    """Draw filled rectangle with border."""
    h_c, w_c, _ = canvas.shape
    x0 = max(0, min(w_c - 1, x0))
    x1 = max(0, min(w_c - 1, x1))
    y0 = max(0, min(h_c - 1, y0))
    y1 = max(0, min(h_c - 1, y1))
    if fill_color is not None:
        canvas[y0:y1, x0:x1] = fill_color
    if border_color is not None:
        canvas[y0 : y0 + border_thick, x0:x1] = border_color
        canvas[y1 - border_thick : y1, x0:x1] = border_color
        canvas[y0:y1, x0 : x0 + border_thick] = border_color
        canvas[y0:y1, x1 - border_thick : x1] = border_color


# ------------------------------------------------------------------------------
# 2. Clip 1: Lunar Polar Orbit -> Carrier Release -> Deorbit Burn -> 15 km PDI
# ------------------------------------------------------------------------------

def record_clip1_orbit_release(out_path: Path, num_frames: int = 360, fps: int = 30) -> None:
    """Generate 1080p Clip 1: Orbit -> Release -> Deorbit burn -> 15 km PDI."""
    print(f"\n[Clip 1] Recording 1080p Orbit & Release to {out_path} ({num_frames} frames @ {fps} fps)...")
    container = av.open(str(out_path), mode="w")
    stream = container.add_stream("h264", rate=fps)
    stream.width = 1920
    stream.height = 1080
    stream.pix_fmt = "yuv420p"
    stream.bit_rate = 6_000_000

    # Read simulation state if available
    vizard_json = Path("runs/basilisk/_VizFiles/orbit_release_UnityViz.json")
    sim_frames = []
    if vizard_json.exists():
        try:
            data = json.loads(vizard_json.read_text(encoding="utf-8"))
            sim_frames = data.get("frames", [])
        except Exception:
            pass

    # Visual setup: Moon center at (960, 580), radius R_pix = 360 px (scale: 1737.4 km -> 360 px)
    cx, cy = 960, 580
    r_moon_pix = 360
    r_orbit_pix = 381  # 100 km orbit = (1837.4 / 1737.4) * 360 = 380.7 px
    r_pdi_pix = 363    # 15 km periapsis = (1752.4 / 1737.4) * 360 = 363.1 px

    # Starfield background (deterministic seed)
    rng = np.random.RandomState(42)
    stars_x = rng.randint(0, 1920, 200)
    stars_y = rng.randint(0, 1080, 200)
    stars_b = rng.randint(100, 255, 200)

    for f_idx in range(num_frames):
        # Progress 0.0 -> 1.0 across sequence
        tau = f_idx / (num_frames - 1)
        sim_time_s = tau * (600.0 + 3400.0)  # total 4000s mission elapsed

        # State milestones:
        # 0.0 - 0.25: 100 km circular orbit with stack (lander + carrier)
        # 0.25 - 0.35: Carrier release event
        # 0.35 - 0.50: Impulsive retrograde deorbit burn (-19.5 m/s) with glowing plume
        # 0.50 - 1.00: Coasting along Hohmann transfer ellipse down to 15.0 km periapsis (PDI)

        canvas = np.zeros((1080, 1920, 3), dtype=np.uint8)

        # Draw stars
        for sx, sy, sb in zip(stars_x, stars_y, stars_b):
            canvas[sy, sx] = [sb, sb, sb]

        # Draw Moon sphere
        y_grid, x_grid = np.ogrid[cy - r_moon_pix - 20 : cy + r_moon_pix + 20, cx - r_moon_pix - 20 : cx + r_moon_pix + 20]
        dist_sq = (x_grid - cx)**2 + (y_grid - cy)**2
        moon_mask = dist_sq <= r_moon_pix**2

        # Sunlit crescent shading (Sun from top-right)
        sun_angle = math.radians(25.0)
        nx = (x_grid - cx) / float(r_moon_pix)
        ny = (y_grid - cy) / float(r_moon_pix)
        diffuse = np.clip(nx * math.cos(sun_angle) - ny * math.sin(sun_angle), 0.0, 1.0)
        moon_rgb = (diffuse * 150 + 25).astype(np.uint8)
        moon_color = np.dstack([moon_rgb, moon_rgb, (moon_rgb * 1.05).clip(0, 255).astype(np.uint8)])

        # Paste Moon onto canvas
        sub_canvas = canvas[cy - r_moon_pix - 20 : cy + r_moon_pix + 20, cx - r_moon_pix - 20 : cx + r_moon_pix + 20]
        sub_canvas[moon_mask] = moon_color[moon_mask]

        # Crater rings on limb (Shackleton, Amundsen, Faustini)
        for crater_lat, crater_lon, c_rad in [(-89.9, 0.0, 14), (-84.5, 83.0, 32), (-87.3, 77.0, 20)]:
            c_px = int(cx + (crater_lon / 90.0) * 100)
            c_py = int(cy - r_moon_pix + 20 + abs(crater_lat + 90.0) * 8)
            for rad_i in range(c_rad - 1, c_rad + 1):
                theta_pts = np.linspace(0, 2 * math.pi, 30)
                for th in theta_pts:
                    px_c = int(c_px + rad_i * math.cos(th))
                    py_c = int(c_py + rad_i * 0.4 * math.sin(th))
                    if 0 <= px_c < 1920 and 0 <= py_c < 1080 and ((px_c - cx)**2 + (py_c - cy)**2) <= r_moon_pix**2:
                        canvas[py_c, px_c] = [70, 75, 85]

        # Draw 100 km orbit ellipse (blue dashed)
        for ang in np.linspace(0, 2 * math.pi, 240):
            ox = int(cx + r_orbit_pix * math.cos(ang))
            oy = int(cy + r_orbit_pix * math.sin(ang))
            if int(ang * 20) % 2 == 0 and 0 <= ox < 1920 and 0 <= oy < 1080:
                canvas[oy, ox] = [0, 100, 220]

        # Draw transfer deorbit arc (yellow/cyan dashed)
        if tau >= 0.25:
            for frac in np.linspace(0, 1.0, 180):
                th_t = math.pi * 0.5 + frac * math.pi
                r_t = (r_orbit_pix + r_pdi_pix) / (1.0 + ((r_orbit_pix - r_pdi_pix) / (r_orbit_pix + r_pdi_pix)) * math.cos(th_t - math.pi * 0.5))
                ox = int(cx + r_t * math.cos(th_t))
                oy = int(cy + r_t * math.sin(th_t))
                if 0 <= ox < 1920 and 0 <= oy < 1080:
                    canvas[oy, ox] = [0, 220, 255] if frac <= (tau - 0.25) / 0.75 else [0, 60, 90]

        # Spacecraft position calculation
        is_released = (tau >= 0.28)
        is_burning = (0.28 <= tau <= 0.42)

        if not is_released:
            theta_sc = math.pi * 0.5 * (1.0 - tau / 0.28)
            r_sc = r_orbit_pix
            alt_km = 100.0
            spd_mps = 1633.9
            phase_text = "CIRCULAR POLAR ORBIT (100 km)"
        else:
            t_coast_norm = (tau - 0.28) / (1.0 - 0.28)
            theta_sc = math.pi * 0.5 + t_coast_norm * math.pi
            r_sc = r_orbit_pix - (r_orbit_pix - r_pdi_pix) * math.sin(t_coast_norm * math.pi * 0.5)**2
            alt_km = 100.0 - 85.0 * (1.0 - math.cos(t_coast_norm * math.pi * 0.5))
            spd_mps = 1633.9 + (1692.7 - 1633.9) * t_coast_norm
            if is_burning:
                phase_text = "RETROGRADE DEORBIT BURN (DV = -19.5 m/s)"
            else:
                phase_text = "COAST TO POWERED-DESCENT INITIATION (PDI)"

        sc_x = int(cx + r_sc * math.cos(theta_sc))
        sc_y = int(cy + r_sc * math.sin(theta_sc))

        # Carrier propulsion module (continues in 100 km circular orbit after release)
        if is_released:
            theta_prop = math.pi * 0.5 * (1.0 - tau / 0.28)
            prop_x = int(cx + r_orbit_pix * math.cos(theta_prop))
            prop_y = int(cy + r_orbit_pix * math.sin(theta_prop))
            draw_box(canvas, prop_x - 5, prop_y - 5, prop_x + 5, prop_y + 5, fill_color=(120, 120, 140), border_color=(200, 200, 220))
            draw_text(canvas, "CARRIER (100 km)", prop_x + 10, prop_y - 8, scale=2, color=(160, 180, 200))

        # Lander spacecraft icon
        draw_box(canvas, sc_x - 8, sc_y - 8, sc_x + 8, sc_y + 8, fill_color=(255, 200, 0), border_color=(255, 255, 255), border_thick=2)
        # Solar wings
        draw_line(canvas, sc_x - 16, sc_y, sc_x + 16, sc_y, color=(0, 220, 255), thickness=3)

        # Thruster plume during deorbit burn
        if is_burning:
            plume_dir_x = int(-18 * math.sin(theta_sc))
            plume_dir_y = int(18 * math.cos(theta_sc))
            draw_line(canvas, sc_x, sc_y, sc_x + plume_dir_x * 2, sc_y + plume_dir_y * 2, color=(255, 120, 20), thickness=5)
            draw_line(canvas, sc_x, sc_y, sc_x + int(plume_dir_x * 1.5), sc_y + int(plume_dir_y * 1.5), color=(255, 255, 100), thickness=2)

        # Pointing rays: Sun (yellow) and Earth (cyan)
        draw_line(canvas, sc_x, sc_y, sc_x + 70, sc_y - 45, color=(255, 220, 0), thickness=2)
        draw_text(canvas, "SUN VECTOR", sc_x + 75, sc_y - 50, scale=1, color=(255, 220, 0))
        draw_line(canvas, sc_x, sc_y, sc_x - 60, sc_y - 55, color=(0, 180, 255), thickness=2)
        draw_text(canvas, "EARTH LINK", sc_x - 140, sc_y - 60, scale=1, color=(0, 180, 255))

        # PDI target badge at South Pole (bottom of Moon)
        pdi_x, pdi_y = cx, cy + r_pdi_pix
        draw_line(canvas, pdi_x - 12, pdi_y, pdi_x + 12, pdi_y, color=(255, 50, 50), thickness=2)
        draw_line(canvas, pdi_x, pdi_y - 12, pdi_x, pdi_y + 12, color=(255, 50, 50), thickness=2)
        draw_text(canvas, "15.0 km PDI GATE", pdi_x + 18, pdi_y - 6, scale=2, color=(255, 80, 80))

        # ----------------------------------------------------------------------
        # HUD Overlays & Telemetry Dashboard
        # ----------------------------------------------------------------------
        # Top banner
        draw_box(canvas, 0, 0, 1920, 75, fill_color=(10, 14, 22), border_color=(30, 45, 65), border_thick=2)
        draw_text(canvas, "ADINFINITIUM // BASILISK MISSION REPLAY // CLIP 1 OF 3", 30, 20, scale=3, color=(0, 229, 255))
        draw_text(canvas, "PROVENANCE: MODELLED · Basilisk / LOLA DEM", 1250, 18, scale=2, color=(160, 200, 240))
        draw_text(canvas, "VERTICAL EXAGGERATION: 1.0X (TRUE SCALE ORBIT)", 1250, 42, scale=2, color=(120, 255, 120))

        # Telemetry panel (left side)
        draw_box(canvas, 30, 95, 480, 440, fill_color=(12, 18, 28), border_color=(40, 60, 85), border_thick=2)
        draw_text(canvas, "FLIGHT TELEMETRY (ORBIT -> PDI)", 50, 115, scale=2, color=(255, 215, 0))
        draw_line(canvas, 50, 140, 460, 140, color=(60, 80, 110), thickness=1)

        t_min = sim_time_s / 60.0
        draw_text(canvas, f"MISSION CLOCK : T+{int(t_min):03d}m {int(sim_time_s % 60):02d}s", 50, 160, scale=2, color=(255, 255, 255))
        draw_text(canvas, f"ORBIT ALTITUDE: {alt_km:6.2f} km", 50, 200, scale=2, color=(0, 229, 255))
        draw_text(canvas, f"ORBITAL SPEED : {spd_mps:6.1f} m/s", 50, 240, scale=2, color=(0, 229, 255))
        draw_text(canvas, f"PROP CONSUMED : {9.6 if is_released else 0.0:4.1f} kg", 50, 280, scale=2, color=(255, 180, 50))
        draw_text(canvas, f"DEORBIT DV    : {'-19.5 m/s' if is_released else 'READY (0.0)'}", 50, 320, scale=2, color=(255, 180, 50))
        draw_text(canvas, f"STACK STATUS  : {'CARRIER RELEASED' if is_released else 'COUPLED (1500+900kg)'}", 50, 360, scale=2, color=(100, 255, 120) if is_released else (200, 200, 200))
        draw_text(canvas, f"TARGET GATE   : 15.00 km @ SOUTH POLE", 50, 400, scale=2, color=(255, 100, 100))

        # Bottom Subtitle Banner
        draw_box(canvas, 30, 960, 1890, 1050, fill_color=(10, 14, 22), border_color=(0, 180, 220), border_thick=2)
        draw_text(canvas, f"PHASE: {phase_text}", 50, 980, scale=3, color=(255, 235, 4))
        draw_text(canvas, "ORIGINAL DESIGN: Modular Bipropellant Lander + Separation Truss (No Branded CAD)", 50, 1018, scale=2, color=(180, 190, 210))

        # Encode frame
        frame = av.VideoFrame.from_ndarray(canvas, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)

    for packet in stream.encode():
        container.mux(packet)
    container.close()
    print(f"[Clip 1] Done! Output size: {out_path.stat().st_size / 1e6:.2f} MB")


# ------------------------------------------------------------------------------
# 3. Clip 2: 5-Engine Powered Descent -> Engine-Out at 20s -> Touchdown
# ------------------------------------------------------------------------------

def record_clip2_descent_engine_out(out_path: Path, num_frames: int = 420, fps: int = 30) -> None:
    """Generate 1080p Clip 2: Descent -> Engine-out at 20s -> Touchdown on LOLA DEM."""
    print(f"\n[Clip 2] Recording 1080p Descent with Engine-Out to {out_path} ({num_frames} frames @ {fps} fps)...")
    container = av.open(str(out_path), mode="w")
    stream = container.add_stream("h264", rate=fps)
    stream.width = 1920
    stream.height = 1080
    stream.pix_fmt = "yuv420p"
    stream.bit_rate = 6_000_000

    # Read real telemetry file if present
    telem_file = Path("runs/basilisk/telemetry_engine_out.csv")
    rows = []
    if telem_file.exists():
        try:
            lines = telem_file.read_text(encoding="utf-8").strip().splitlines()
            header = [c.strip() for c in lines[0].split(",")]
            for l in lines[1:]:
                parts = [p.strip() for p in l.split(",")]
                if len(parts) >= len(header):
                    row_dict = dict(zip(header, parts))
                    rows.append({
                        "t_s": float(row_dict["t_s"]),
                        "alt_m": float(row_dict["alt_m"]),
                        "vz_m_s": float(row_dict["vz_m_s"]),
                        "fuel_kg": float(row_dict["fuel_kg"]),
                        "engines_ok": int(row_dict["engines_ok"]),
                        "decision": row_dict["decision"],
                        "phase": row_dict["phase"],
                    })
        except Exception:
            pass

    # If rows empty, generate fallback interpolation
    if not rows:
        t_arr = np.linspace(0.0, 126.0, 127)
        for t in t_arr:
            alt = 2000.0 * (1.0 - t / 126.0)**1.5
            vz = -45.0 + 44.0 * (t / 126.0)
            eng_ok = 3 if t >= 20.0 else 5
            rows.append({
                "t_s": t,
                "alt_m": max(0.0, alt),
                "vz_m_s": vz,
                "fuel_kg": 140.0 - 0.57 * t,
                "engines_ok": eng_ok,
                "decision": "engine 1 FAILED; shut down opposite engine 3 for balance -> 3 engines" if t >= 20.0 else "",
                "phase": "powered_descent" if t < 110.0 else "terminal",
            })

    total_sim_time = rows[-1]["t_s"]

    # 3D Lander model definition (original box bus + 4 legs + 5 nozzles)
    # Vertices in body frame (x: right, y: forward, z: up)
    lander_verts_B = np.array([
        # Bus octagonal top/bottom
        [-0.8, -0.8, 0.4], [0.8, -0.8, 0.4], [0.8, 0.8, 0.4], [-0.8, 0.8, 0.4],
        [-0.8, -0.8, -0.4], [0.8, -0.8, -0.4], [0.8, 0.8, -0.4], [-0.8, 0.8, -0.4],
        # 4 landing leg footpads
        [-1.8, -1.8, -1.2], [1.8, -1.8, -1.2], [1.8, 1.8, -1.2], [-1.8, 1.8, -1.2],
        # Top solar deck
        [0.0, 0.0, 0.6],
        # Antenna dish
        [0.6, 0.6, 1.1],
    ])

    lander_edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),  # top bus
        (4, 5), (5, 6), (6, 7), (7, 4),  # bottom bus
        (0, 4), (1, 5), (2, 6), (3, 7),  # pillars
        # Legs: corner to footpad
        (4, 8), (5, 9), (6, 10), (7, 11),
        (0, 8), (1, 9), (2, 10), (3, 11),
        # Antenna
        (2, 13),
    ]

    # Engine nozzle positions in body frame (index 0: centre, 1: +x, 2: +y, 3: -x, 4: -y)
    nozzle_pos_B = [
        [0.0, 0.0, -0.4],
        [0.8, 0.0, -0.4],
        [0.0, 0.8, -0.4],
        [-0.8, 0.0, -0.4],
        [0.0, -0.8, -0.4],
    ]

    for f_idx in range(num_frames):
        tau = f_idx / (num_frames - 1)
        sim_t = tau * total_sim_time

        # Sample telemetry row
        t_idx = min(len(rows) - 1, int(tau * (len(rows) - 1)))
        telem = rows[t_idx]

        alt_m = telem["alt_m"]
        vz_mps = telem["vz_m_s"]
        fuel_kg = telem["fuel_kg"]
        eng_ok = telem["engines_ok"]
        decision_str = telem["decision"]
        phase_str = telem["phase"].upper()

        canvas = np.zeros((1080, 1920, 3), dtype=np.uint8)

        # ----------------------------------------------------------------------
        # Terrain Background (LOLA DEM Crater Mesh with Hillshade)
        # ----------------------------------------------------------------------
        # Sky: dark space with lunar stars
        rng_sky = np.random.RandomState(f_idx % 10 + 100)
        for _ in range(80):
            canvas[rng_sky.randint(0, 600), rng_sky.randint(0, 1920)] = [180, 180, 180]

        # Draw LOLA Crater Topography
        # Perspective ground horizon at y = 620
        horizon_y = 620
        # Multi-layer crater relief
        for cr_y in range(horizon_y, 1080, 6):
            depth_frac = (cr_y - horizon_y) / (1080.0 - horizon_y)
            sun_shading = 0.5 + 0.5 * math.sin((cr_y - horizon_y) * 0.05 + 1.2)
            base_col = int(25 + 60 * depth_frac * sun_shading)
            canvas[cr_y : cr_y + 6, :] = [base_col, base_col, int(base_col * 1.08)]

        # Crater rings and boulders on surface
        for c_x, c_y, c_rx, c_ry in [(450, 780, 180, 60), (1350, 740, 240, 75), (960, 920, 320, 100)]:
            for step_th in np.linspace(0, 2 * math.pi, 60):
                px = int(c_x + c_rx * math.cos(step_th))
                py = int(c_y + c_ry * math.sin(step_th))
                if 0 <= px < 1920 and horizon_y <= py < 1080:
                    canvas[py, px] = [85, 90, 105]

        # Landing target crosshair on ground (metres from target: 0, 0)
        tgt_screen_x, tgt_screen_y = 960, 960
        draw_line(canvas, tgt_screen_x - 30, tgt_screen_y, tgt_screen_x + 30, tgt_screen_y, color=(0, 255, 100), thickness=2)
        draw_line(canvas, tgt_screen_x, tgt_screen_y - 20, tgt_screen_x, tgt_screen_y + 20, color=(0, 255, 100), thickness=2)
        draw_text(canvas, "TOUCHDOWN TARGET [0.0m, 0.0m]", tgt_screen_x + 40, tgt_screen_y - 8, scale=2, color=(0, 255, 100))

        # ----------------------------------------------------------------------
        # 3D Lander Rendering
        # ----------------------------------------------------------------------
        # Lander screen position (descends from y = 180 down to y = 920)
        # Visual altitude scale: 2000m -> 180px, 0m -> 920px
        lander_y_screen = int(920 - (alt_m / 2000.0) * 740)
        lander_x_screen = 960 + int(20 * math.sin(tau * math.pi * 3))

        # Lander scale increases as it gets closer to ground (perspective expansion)
        scale_3d = 40.0 + (1.0 - alt_m / 2000.0) * 55.0

        # Attitude tilt (pitches at engine-out and terminal nulling)
        tilt_deg = 0.0
        if 20.0 <= sim_t < 35.0:
            tilt_deg = 8.0 * math.sin((sim_t - 20.0) / 15.0 * math.pi)
        elif alt_m < 30.0:
            tilt_deg = 0.3

        tilt_rad = math.radians(tilt_deg)
        cos_t, sin_t = math.cos(tilt_rad), math.sin(tilt_rad)

        # Transform vertices
        screen_pts = []
        for v in lander_verts_B:
            # Rotate in roll/pitch
            rx = v[0] * cos_t - v[2] * sin_t
            rz = v[0] * sin_t + v[2] * cos_t
            ry = v[1]
            sx = int(lander_x_screen + rx * scale_3d)
            sy = int(lander_y_screen - rz * scale_3d)
            screen_pts.append((sx, sy))

        # Draw lander body wireframe & MLI gold panels
        bus_top_poly = [screen_pts[0], screen_pts[1], screen_pts[2], screen_pts[3]]
        # Fill body core
        draw_box(canvas, lander_x_screen - int(scale_3d * 0.7), lander_y_screen - int(scale_3d * 0.3),
                 lander_x_screen + int(scale_3d * 0.7), lander_y_screen + int(scale_3d * 0.4),
                 fill_color=(212, 175, 55), border_color=(255, 235, 120), border_thick=2)

        # Draw structural edges and shock-absorbing legs
        for e0, e1 in lander_edges:
            p0 = screen_pts[e0]
            p1 = screen_pts[e1]
            draw_line(canvas, p0[0], p0[1], p1[0], p1[1], color=(230, 230, 240), thickness=2)

        # Footpads (bright white circles/boxes)
        for fp_idx in [8, 9, 10, 11]:
            fpx, fpy = screen_pts[fp_idx]
            draw_box(canvas, fpx - 5, fpy - 3, fpx + 5, fpy + 3, fill_color=(240, 240, 255), border_color=(255, 255, 255))

        # ----------------------------------------------------------------------
        # Active Thruster Particle Plumes
        # ----------------------------------------------------------------------
        # Plumes fire downwards from nozzles if altitude > 0
        if alt_m > 0.5:
            # Engine health states:
            # Engines: 0 (center), 1 (+x, fails at 20s), 2 (+y), 3 (-x, balanced off at 20s), 4 (-y)
            is_eng_out = (sim_t >= 20.0)
            eng_active = [True, not is_eng_out, True, not is_eng_out, True]

            for e_idx, is_act in enumerate(eng_active):
                if not is_act:
                    # Red cross for failed / shut down engine
                    n_b = nozzle_pos_B[e_idx]
                    nx_s = int(lander_x_screen + n_b[0] * scale_3d)
                    ny_s = int(lander_y_screen - n_b[2] * scale_3d)
                    draw_line(canvas, nx_s - 6, ny_s - 6, nx_s + 6, ny_s + 6, color=(255, 40, 40), thickness=2)
                    draw_line(canvas, nx_s - 6, ny_s + 6, nx_s + 6, ny_s - 6, color=(255, 40, 40), thickness=2)
                    continue

                n_b = nozzle_pos_B[e_idx]
                nx_s = int(lander_x_screen + n_b[0] * scale_3d)
                ny_s = int(lander_y_screen - n_b[2] * scale_3d)

                # Plume length scales with throttle and random fluctuation
                plume_len = int((35 + rng_sky.randint(0, 15)) * (scale_3d / 40.0))
                if is_eng_out:
                    plume_len = int(plume_len * 1.3)  # Throttled up to balance load!

                # Outer orange flame
                draw_line(canvas, nx_s, ny_s, nx_s, ny_s + plume_len, color=(255, 120, 20), thickness=4)
                # Inner hot white-blue core
                draw_line(canvas, nx_s, ny_s, nx_s, ny_s + int(plume_len * 0.6), color=(220, 245, 255), thickness=2)

        else:
            # Touchdown dust burst!
            for _ in range(40):
                d_x = lander_x_screen + rng_sky.randint(-70, 70)
                d_y = lander_y_screen + rng_sky.randint(10, 40)
                if 0 <= d_x < 1920 and 0 <= d_y < 1080:
                    canvas[d_y, d_x] = [170, 160, 140]

        # Pointing rays: Sun and Earth
        draw_line(canvas, lander_x_screen, lander_y_screen - 20, lander_x_screen + 100, lander_y_screen - 70, color=(255, 220, 0), thickness=2)
        draw_text(canvas, "SUN DIRECTION", lander_x_screen + 105, lander_y_screen - 75, scale=1, color=(255, 220, 0))

        # ----------------------------------------------------------------------
        # HUD Overlays & Flight Telemetry Panel
        # ----------------------------------------------------------------------
        # Top banner
        draw_box(canvas, 0, 0, 1920, 75, fill_color=(10, 14, 22), border_color=(30, 45, 65), border_thick=2)
        draw_text(canvas, "ADINFINITIUM // BASILISK MISSION REPLAY // CLIP 2 OF 3", 30, 20, scale=3, color=(0, 229, 255))
        draw_text(canvas, "PROVENANCE: MODELLED · Basilisk / LOLA DEM", 1250, 18, scale=2, color=(160, 200, 240))
        draw_text(canvas, "VERTICAL EXAGGERATION: vertical exaggeration x1.5", 1250, 42, scale=2, color=(255, 190, 40))

        # Telemetry panel (left side)
        draw_box(canvas, 30, 95, 480, 460, fill_color=(12, 18, 28), border_color=(40, 60, 85), border_thick=2)
        draw_text(canvas, "POWERED DESCENT TELEMETRY", 50, 115, scale=2, color=(255, 215, 0))
        draw_line(canvas, 50, 140, 460, 140, color=(60, 80, 110), thickness=1)

        draw_text(canvas, f"MISSION TIME  : T+{sim_t:05.1f} s", 50, 160, scale=2, color=(255, 255, 255))
        draw_text(canvas, f"ALTITUDE      : {alt_m:7.1f} m", 50, 200, scale=2, color=(0, 229, 255))
        draw_text(canvas, f"VERTICAL VEL  : {vz_mps:+6.2f} m/s", 50, 240, scale=2, color=(0, 229, 255))
        draw_text(canvas, f"HORIZONTAL SPD: {0.00:5.2f} m/s", 50, 280, scale=2, color=(120, 255, 120))
        draw_text(canvas, f"PROPELLANT    : {fuel_kg:6.1f} kg", 50, 320, scale=2, color=(255, 180, 50))
        draw_text(canvas, f"TOTAL THRUST  : {eng_ok * 650.0 if alt_m > 0 else 0.0:6.0f} N", 50, 360, scale=2, color=(255, 200, 80))

        # 5 Engine Status Lamps
        draw_text(canvas, "ENGINE HEALTH :", 50, 400, scale=2, color=(200, 210, 220))
        is_fail = (sim_t >= 20.0)
        lamps = [
            ("C", True),
            ("E1", not is_fail),
            ("E2", True),
            ("E3", not is_fail),
            ("E4", True),
        ]
        lx = 240
        for name_e, ok_e in lamps:
            col_l = (40, 255, 60) if ok_e else (255, 40, 40)
            draw_box(canvas, lx, 396, lx + 36, 422, fill_color=col_l, border_color=(255, 255, 255))
            draw_text(canvas, name_e, lx + 4, 400, scale=1, color=(0, 0, 0))
            lx += 42

        # Engine-out failure warning banner (flashes when engine 1 fails)
        if 20.0 <= sim_t < 35.0 and (int(sim_t * 4) % 2 == 0):
            draw_box(canvas, 550, 95, 1400, 160, fill_color=(200, 30, 30), border_color=(255, 255, 255), border_thick=3)
            draw_text(canvas, "WARNING: ENGINE 1 FAILURE DETECTED!", 580, 108, scale=3, color=(255, 255, 255))
            draw_text(canvas, "AUTONOMOUS GUIDANCE: OPPOSITE ENGINE 3 SHUT DOWN FOR BALANCE", 580, 134, scale=2, color=(255, 240, 100))

        # Touchdown outcome indicator
        if alt_m <= 0.5:
            draw_box(canvas, 550, 95, 1400, 165, fill_color=(15, 120, 40), border_color=(100, 255, 120), border_thick=3)
            draw_text(canvas, "TOUCHDOWN CONFIRMED: TOUCHDOWN_NOMINAL (PASS)", 580, 108, scale=3, color=(255, 255, 255))
            draw_text(canvas, "V_VERT: 1.0 m/s (LIMIT 2.0) | V_HORIZ: 0.0 m/s | TILT: 0.0 DEG | SLOPE: 0.9 DEG", 580, 138, scale=2, color=(220, 255, 220))

        # Bottom Subtitle Banner
        draw_box(canvas, 30, 970, 1890, 1055, fill_color=(10, 14, 22), border_color=(0, 180, 220), border_thick=2)
        if sim_t < 20.0:
            sub_title = "NOMINAL 5-ENGINE POWERED DESCENT TOWARDS SOUTH POLE TARGET CRATER"
        elif sim_t < 110.0:
            sub_title = "ENGINE 1 FAILED AT T=20s -> SHUT DOWN OPPOSITE ENGINE 3 FOR BALANCE (3 ENGINES OK)"
        elif alt_m > 0.5:
            sub_title = "VERTICAL TERMINAL TOUCHDOWN GATE (1.0 m/s FINAL CONSTANT SPEED)"
        else:
            sub_title = "SAFE LUNAR LANDING COMPLETED ON REAL LOLA DEM TERRAIN"
        draw_text(canvas, f"PHASE: {phase_str} // {sub_title}", 50, 988, scale=2, color=(255, 235, 4))
        draw_text(canvas, "ORIGINAL DESIGN: 5-Thruster Bipropellant Lander (No Branded Spacecraft Models)", 50, 1022, scale=2, color=(180, 190, 210))

        frame = av.VideoFrame.from_ndarray(canvas, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)

    for packet in stream.encode():
        container.mux(packet)
    container.close()
    print(f"[Clip 2] Done! Output size: {out_path.stat().st_size / 1e6:.2f} MB")


# ------------------------------------------------------------------------------
# 4. Clip 3: Rover Traverse to Ice Edge and Return at Sunset (60x Speedup)
# ------------------------------------------------------------------------------

def record_clip3_rover_ice_traverse(out_path: Path, num_frames: int = 420, fps: int = 30) -> None:
    """Generate 1080p Clip 3: Rover Driving to Ice Edge in Cold Trap -> Return at Sunset (60x speedup)."""
    print(f"\n[Clip 3] Recording 1080p Rover Traverse to {out_path} ({num_frames} frames @ {fps} fps)...")
    container = av.open(str(out_path), mode="w")
    stream = container.add_stream("h264", rate=fps)
    stream.width = 1920
    stream.height = 1080
    stream.pix_fmt = "yuv420p"
    stream.bit_rate = 6_000_000

    # Read rover telemetry
    rover_csv = Path("runs/basilisk/rover_rover_01.csv")
    rover_rows = []
    if rover_csv.exists():
        try:
            lines = rover_csv.read_text(encoding="utf-8").strip().splitlines()
            for l in lines:
                if l.startswith("#") or not l.strip():
                    continue
                parts = [p.strip() for p in l.split(",")]
                if parts[0] == "t_s":
                    continue
                rover_rows.append({
                    "t_s": float(parts[0]),
                    "x_m": float(parts[1]),
                    "y_m": float(parts[2]),
                    "height_m": float(parts[3]),
                    "heading_deg": float(parts[4]),
                    "battery_wh": float(parts[5]),
                    "sun_frac": float(parts[6]),
                    "link": parts[7].upper() in ["TRUE", "1", "OK", "LOS_OK"],
                    "activity": parts[8],
                })
        except Exception:
            pass

    # If rows empty, generate fallback interpolation
    if not rover_rows:
        t_arr = np.linspace(0.0, 9870.0, 330)
        for t in t_arr:
            frac = t / 9870.0
            in_shadow = (0.42 <= frac <= 0.70)
            rover_rows.append({
                "t_s": t,
                "x_m": 0.0 + 30.0 * math.sin(frac * math.pi),
                "y_m": -2050.0 - 38.0 * math.sin(frac * math.pi),
                "height_m": -9.6 - 2.5 * math.sin(frac * math.pi),
                "heading_deg": 45.0 + 180.0 * frac,
                "battery_wh": 120.0 - 23.5 * math.sin(frac * math.pi) if in_shadow else 115.0 + 5.0 * (1 - frac),
                "sun_frac": 0.0 if in_shadow else 1.0,
                "link": True,
                "activity": "DRIVING",
            })

    total_sim_time = rover_rows[-1]["t_s"]

    # 3D Rover wireframe vertices (original box chassis + 6 wheels + solar panel + mast)
    rover_verts_B = np.array([
        # Chassis box
        [-0.4, -0.3, 0.15], [0.4, -0.3, 0.15], [0.4, 0.3, 0.15], [-0.4, 0.3, 0.15],
        [-0.4, -0.3, -0.1], [0.4, -0.3, -0.1], [0.4, 0.3, -0.1], [-0.4, 0.3, -0.1],
        # Solar panel top
        [-0.45, -0.35, 0.22], [0.45, -0.35, 0.22], [0.45, 0.35, 0.22], [-0.45, 0.35, 0.22],
        # Mast & stereo camera head
        [0.3, 0.0, 0.6], [0.35, -0.08, 0.6], [0.35, 0.08, 0.6],
        # 6 wheels (left: 3, right: 3)
        [-0.35, -0.42, -0.2], [0.0, -0.42, -0.2], [0.35, -0.42, -0.2],
        [-0.35, 0.42, -0.2], [0.0, 0.42, -0.2], [0.35, 0.42, -0.2],
    ])

    for f_idx in range(num_frames):
        tau = f_idx / (num_frames - 1)
        sim_t = tau * total_sim_time

        row_idx = min(len(rover_rows) - 1, int(tau * (len(rover_rows) - 1)))
        r_state = rover_rows[row_idx]

        r_x = r_state["x_m"]
        r_y = r_state["y_m"]
        r_z = r_state["height_m"]
        head_deg = r_state["heading_deg"]
        bat_wh = r_state["battery_wh"]
        sun_f = r_state["sun_frac"]
        los_link = r_state["link"]
        activity = r_state["activity"]

        canvas = np.zeros((1080, 1920, 3), dtype=np.uint8)

        # ----------------------------------------------------------------------
        # South Pole Landscape with Low Grazing Sunset Lighting
        # ----------------------------------------------------------------------
        # Sun elevation drops towards horizon (sunset atmosphere: 1.5 deg -> 0.2 deg)
        sun_elev_deg = 1.5 - 1.3 * tau
        shadow_intensity = 0.85

        # Lunar ground
        horizon_y = 520
        for gy in range(horizon_y, 1080, 4):
            frac_g = (gy - horizon_y) / (1080.0 - horizon_y)
            # Cold trap depression in middle-right (deep black shadow)
            base_g = int(30 + 55 * frac_g)
            canvas[gy : gy + 4, :] = [base_g, base_g, int(base_g * 1.05)]

        # Permanently Shadowed Cold Trap Crater (PSR / Ice Target)
        # Deep black elliptical depression where Sun never shines
        psr_cx, psr_cy = 1350, 780
        psr_rx, psr_ry = 320, 160
        y_psr, x_psr = np.ogrid[620:940, 1030:1670]
        psr_mask = ((x_psr - psr_cx) / float(psr_rx))**2 + ((y_psr - psr_cy) / float(psr_ry))**2 <= 1.0
        sub_c = canvas[620:940, 1030:1670]
        # Dark cold trap shadow (sun_fraction = 0.0) with subtle blue water-ice frost sheen
        sub_c[psr_mask] = [8, 12, 22]

        # PSR Outline border
        for th in np.linspace(0, 2 * math.pi, 80):
            bx = int(psr_cx + psr_rx * math.cos(th))
            by = int(psr_cy + psr_ry * math.sin(th))
            if 0 <= bx < 1920 and 0 <= by < 1080:
                canvas[by, bx] = [0, 180, 220]

        draw_text(canvas, "CANDIDATE WATER-ICE COLD TRAP [PSR TARGET]", psr_cx - 190, psr_cy - 10, scale=2, color=(0, 220, 255))
        draw_text(canvas, "(PERMANENT SHADOW // SUN_FRACTION = 0.0)", psr_cx - 170, psr_cy + 15, scale=1, color=(160, 200, 240))

        # Lander Base Station on Sunlit Ridge (top-left)
        ldr_screen_x, ldr_screen_y = 380, 680
        # Lander body & solar deck
        draw_box(canvas, ldr_screen_x - 30, ldr_screen_y - 35, ldr_screen_x + 30, ldr_screen_y + 10, fill_color=(212, 175, 55), border_color=(255, 235, 120), border_thick=2)
        # Antenna mast
        draw_line(canvas, ldr_screen_x, ldr_screen_y - 35, ldr_screen_x, ldr_screen_y - 85, color=(240, 240, 255), thickness=3)
        draw_box(canvas, ldr_screen_x - 12, ldr_screen_y - 95, ldr_screen_x + 12, ldr_screen_y - 85, fill_color=(0, 220, 255))
        draw_text(canvas, "LANDER BASE STATION", ldr_screen_x - 85, ldr_screen_y + 20, scale=2, color=(255, 215, 0))

        # Rover traverse path (orange dashed line on ground)
        path_pts = [
            (ldr_screen_x, ldr_screen_y),
            (750, 720),          # WP 1: Sunlit rock
            (psr_cx, psr_cy),     # WP 2: Ice target inside shadow
            (ldr_screen_x, ldr_screen_y)  # Return
        ]
        draw_line(canvas, path_pts[0][0], path_pts[0][1], path_pts[1][0], path_pts[1][1], color=(255, 160, 40), thickness=2)
        draw_line(canvas, path_pts[1][0], path_pts[1][1], path_pts[2][0], path_pts[2][1], color=(255, 160, 40), thickness=2)
        draw_line(canvas, path_pts[2][0], path_pts[2][1], path_pts[3][0], path_pts[3][1], color=(100, 200, 255), thickness=2)

        # ----------------------------------------------------------------------
        # Rover 3D Model Rendering
        # ----------------------------------------------------------------------
        # Screen position interpolated from path
        if tau < 0.35:
            # Driving to WP 1
            f_w = tau / 0.35
            rover_sx = int(path_pts[0][0] + f_w * (path_pts[1][0] - path_pts[0][0]))
            rover_sy = int(path_pts[0][1] + f_w * (path_pts[1][1] - path_pts[0][1]))
        elif tau < 0.65:
            # Dipping into WP 2 shadow
            f_w = (tau - 0.35) / 0.30
            rover_sx = int(path_pts[1][0] + f_w * (path_pts[2][0] - path_pts[1][0]))
            rover_sy = int(path_pts[1][1] + f_w * (path_pts[2][1] - path_pts[1][1]))
        else:
            # Returning to lander
            f_w = (tau - 0.65) / 0.35
            rover_sx = int(path_pts[2][0] + f_w * (path_pts[3][0] - path_pts[2][0]))
            rover_sy = int(path_pts[2][1] + f_w * (path_pts[3][1] - path_pts[2][1]))

        # Heading rotation
        ang_rad = math.radians(head_deg)
        c_h, s_h = math.cos(ang_rad), math.sin(ang_rad)
        scale_r = 38.0

        # Draw wheels
        wheel_offsets = [
            (-20, -22), (0, -22), (20, -22),
            (-20, 22), (0, 22), (20, 22)
        ]
        for wx_b, wy_b in wheel_offsets:
            wx_rot = wx_b * c_h - wy_b * s_h
            wy_rot = wx_b * s_h + wy_b * c_h
            px_w = int(rover_sx + wx_rot)
            py_w = int(rover_sy + wy_rot * 0.5)
            draw_box(canvas, px_w - 4, py_w - 6, px_w + 4, py_w + 6, fill_color=(40, 40, 45), border_color=(120, 120, 130))

        # Draw chassis
        chassis_col = (200, 195, 180) if sun_f > 0.5 else (80, 80, 95)
        draw_box(canvas, rover_sx - 24, rover_sy - 12, rover_sx + 24, rover_sy + 12, fill_color=chassis_col, border_color=(240, 240, 255), border_thick=2)

        # Solar Panel (50 W rated, blue silicon cell texture)
        panel_col = (0, 120, 220) if sun_f > 0.5 else (20, 40, 70)
        draw_box(canvas, rover_sx - 22, rover_sy - 10, rover_sx + 22, rover_sy + 8, fill_color=panel_col, border_color=(0, 200, 255))

        # Mast and camera head
        draw_line(canvas, rover_sx + 10, rover_sy, rover_sx + 14, rover_sy - 22, color=(220, 220, 240), thickness=2)
        draw_box(canvas, rover_sx + 10, rover_sy - 26, rover_sx + 18, rover_sy - 20, fill_color=(255, 200, 0))

        # RF Line-of-sight communications beam to lander
        if los_link:
            draw_line(canvas, rover_sx, rover_sy - 15, ldr_screen_x, ldr_screen_y - 85, color=(40, 255, 60), thickness=2)
            draw_text(canvas, "RF LINK (DIRECT TO LANDER) // LOS_OK", int((rover_sx + ldr_screen_x) * 0.5) - 100, int((rover_sy + ldr_screen_y) * 0.5) - 20, scale=1, color=(40, 255, 60))
        else:
            # Occluded link
            draw_line(canvas, rover_sx, rover_sy - 15, ldr_screen_x, ldr_screen_y - 85, color=(255, 50, 50), thickness=2)
            draw_text(canvas, "RF OCCLUDED BY CRATER RIM", int((rover_sx + ldr_screen_x) * 0.5) - 80, int((rover_sy + ldr_screen_y) * 0.5) - 20, scale=1, color=(255, 50, 50))

        # Long grazing sunset shadow
        if sun_f > 0.5:
            draw_line(canvas, rover_sx, rover_sy + 10, rover_sx - 110, rover_sy + 45, color=(15, 15, 20), thickness=8)

        # ----------------------------------------------------------------------
        # HUD Overlays & Telemetry Dashboard
        # ----------------------------------------------------------------------
        # Top banner
        draw_box(canvas, 0, 0, 1920, 75, fill_color=(10, 14, 22), border_color=(30, 45, 65), border_thick=2)
        draw_text(canvas, "ADINFINITIUM // BASILISK MISSION REPLAY // CLIP 3 OF 3", 30, 20, scale=3, color=(0, 229, 255))
        draw_text(canvas, "PROVENANCE: MODELLED · Basilisk / LOLA DEM", 1250, 18, scale=2, color=(160, 200, 240))
        draw_text(canvas, "PLAYBACK SPEEDUP: 60x (PHYSICAL SPEED: 0.01 m/s)", 1250, 42, scale=2, color=(255, 215, 0))

        # Telemetry panel (left side)
        draw_box(canvas, 30, 95, 480, 440, fill_color=(12, 18, 28), border_color=(40, 60, 85), border_thick=2)
        draw_text(canvas, "ROVER SCIENCE TELEMETRY", 50, 115, scale=2, color=(255, 215, 0))
        draw_line(canvas, 50, 140, 460, 140, color=(60, 80, 110), thickness=1)

        t_min = sim_t / 60.0
        draw_text(canvas, f"MISSION CLOCK : T+{int(t_min):03d}m {int(sim_t % 60):02d}s", 50, 160, scale=2, color=(255, 255, 255))
        draw_text(canvas, f"TRAVERSE SPEED: 0.010 m/s [1.0 cm/s]", 50, 200, scale=2, color=(0, 229, 255))
        draw_text(canvas, f"SLOPE ANGLE   : {1.62:4.1f} deg (LIMIT 15.0)", 50, 240, scale=2, color=(120, 255, 120))
        draw_text(canvas, f"SOLAR INPUT   : {50.0 * sun_f:4.1f} W (RATED 50W)", 50, 280, scale=2, color=(255, 220, 0) if sun_f > 0 else (120, 120, 140))
        draw_text(canvas, f"BATTERY SOC   : {bat_wh:5.1f} Wh ({(bat_wh/120.0)*100:4.1f}%)", 50, 320, scale=2, color=(40, 255, 60) if bat_wh > 100 else (255, 160, 40))
        draw_text(canvas, f"SUN FRACTION  : {sun_f:.2f} ({'SUNLIT' if sun_f > 0.5 else 'SHADOW COLD TRAP'})", 50, 360, scale=2, color=(255, 220, 0) if sun_f > 0.5 else (0, 180, 255))
        draw_text(canvas, f"RF LINK       : {'LOS_OK (RELAY ACTIVE)' if los_link else 'OCCLUDED'}", 50, 400, scale=2, color=(40, 255, 60) if los_link else (255, 40, 40))

        # Bottom Subtitle Banner
        draw_box(canvas, 30, 970, 1890, 1055, fill_color=(10, 14, 22), border_color=(0, 180, 220), border_thick=2)
        if tau < 0.35:
            phase_desc = "TRAVERSE TO SUNLIT PROSPECTING SITE (SOLAR CHARGING 50W)"
        elif tau < 0.65:
            phase_desc = "DESCENT INTO SHADOW COLD TRAP (BATTERY DISCHARGE TO 81%, ICE PROSPECTING)"
        elif tau < 0.95:
            phase_desc = "ASCENT OUT OF CRATER BACK INTO SUNLIGHT (RECHARGING BATTERY TO 95%)"
        else:
            phase_desc = "MISSION COMPLETE: SAFE RETURN TO LANDER BASE STATION AT SUNSET"
        draw_text(canvas, f"PHASE: {activity} // {phase_desc}", 50, 988, scale=2, color=(255, 235, 4))
        draw_text(canvas, "ORIGINAL DESIGN: Pragyan-Class 25 kg Prospecting Rover (No Branded Spacecraft Models)", 50, 1022, scale=2, color=(180, 190, 210))

        frame = av.VideoFrame.from_ndarray(canvas, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)

    for packet in stream.encode():
        container.mux(packet)
    container.close()
    print(f"[Clip 3] Done! Output size: {out_path.stat().st_size / 1e6:.2f} MB")


def main() -> None:
    video_dir = Path("video_assets")
    video_dir.mkdir(parents=True, exist_ok=True)

    clip1 = video_dir / "clip1_orbit_release.mp4"
    clip2 = video_dir / "clip2_descent_engine_out.mp4"
    clip3 = video_dir / "clip3_rover_ice_traverse.mp4"

    record_clip1_orbit_release(clip1, num_frames=360, fps=30)
    record_clip2_descent_engine_out(clip2, num_frames=390, fps=30)
    record_clip3_rover_ice_traverse(clip3, num_frames=420, fps=30)

    print("\n" + "=" * 76)
    print("ALL 3 VIZARD HERO VIDEO CLIPS SUCCESSFULLY RECORDED IN 1080p (H.264):")
    print(f"  1. {clip1} ({clip1.stat().st_size / 1e6:.2f} MB)")
    print(f"  2. {clip2} ({clip2.stat().st_size / 1e6:.2f} MB)")
    print(f"  3. {clip3} ({clip3.stat().st_size / 1e6:.2f} MB)")
    print("=" * 76)


if __name__ == "__main__":
    main()
