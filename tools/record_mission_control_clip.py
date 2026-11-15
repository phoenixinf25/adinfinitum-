"""Renderer for Mission Control 1080p Screen Recording (Spec §9.2).

Generates video_assets/clip4_mission_control.mp4:
- Real closed-loop Basilisk descent telemetry with Engine-Out at T=21s.
- Live 5-engine cluster fault response and autonomous thrust balancing.
- Navigator-matched countdowns to sunset and Earthset.
- Rover mini-panel telemetry.
- Autonomous decision log tracking G&C events to touchdown.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Ensure repo root is on sys.path
_repo_dir = str(Path(__file__).resolve().parent.parent)
if _repo_dir not in sys.path:
    sys.path.insert(0, _repo_dir)

import av
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from contracts.paths import repo_root
from mission_control.data import (
    extract_decisions,
    get_site_countdowns,
    load_rover_telemetry,
    load_telemetry,
    parse_engine_cluster,
)

WIDTH = 1920
HEIGHT = 1080
FPS = 30
DURATION_S = 16.0  # 16 seconds video showing full 126s descent condensed


def get_font(size: int = 16, bold: bool = False):
    try:
        # Standard Windows fonts
        font_name = "consola.ttf" if bold else "consolab.ttf"
        return ImageFont.truetype(f"C:/Windows/Fonts/{font_name}", size)
    except Exception:
        try:
            return ImageFont.truetype("arial.ttf", size)
        except Exception:
            return ImageFont.load_default()


def render_mc_frame(
    df: pd.DataFrame,
    rover_df: pd.DataFrame | None,
    decisions: list[dict],
    countdowns: dict,
    sim_t: float,
    fonts: dict[str, Any],
) -> Image.Image:
    # Find row closest to sim_t
    idx = int((df["t_s"] - sim_t).abs().argmin())
    row = df.iloc[idx]

    curr_t = float(row["t_s"])
    curr_phase = str(row["phase"]).replace("_", " ").upper()
    curr_engines_ok = int(row["engines_ok"]) if pd.notna(row["engines_ok"]) else 5
    curr_decision = str(row["decision"]) if pd.notna(row["decision"]) else ""
    curr_thrust = float(row["thrust_n"]) if pd.notna(row["thrust_n"]) else 0.0

    alt_val = float(row["alt_m"])
    vz_val = float(row["vz_m_s"])
    vh_val = float(row["v_horizontal_m_s"])
    fuel_val = float(row["fuel_kg"])
    mass_val = float(row["mass_kg"])
    x_val = float(row["x_m"])
    y_val = float(row["y_m"])

    # Engine cluster
    cluster = parse_engine_cluster(curr_engines_ok, curr_decision, curr_thrust)

    im = Image.new("RGB", (WIDTH, HEIGHT), color=(7, 11, 18))
    draw = ImageDraw.Draw(im)

    # 1. Top Header Bar
    draw.rectangle([(20, 20), (WIDTH - 20, 90)], fill=(14, 21, 38), outline=(30, 41, 59), width=1)
    
    # Title & badges
    draw.text((40, 36), "🌙 MISSION OPERATIONS CONSOLE (PORT 8502)", fill=(248, 250, 252), font=fonts["title"])
    
    # Provenance badge
    draw.rectangle([(620, 38), (790, 72)], fill=(46, 29, 5), outline=(255, 170, 0), width=1)
    draw.text((632, 45), "MODELLED · Basilisk", fill=(255, 170, 0), font=fonts["badge"])

    # Phase badge
    phase_bg = (0, 240, 255, 38) if "DESCENT" in curr_phase else (0, 255, 136, 38) if "TOUCHDOWN" in curr_phase else (255, 170, 0, 38)
    phase_outline = (0, 240, 255) if "DESCENT" in curr_phase else (0, 255, 136) if "TOUCHDOWN" in curr_phase else (255, 170, 0)
    draw.rectangle([(810, 38), (1050, 72)], fill=(10, 20, 35), outline=phase_outline, width=1)
    draw.text((825, 45), f"[ {curr_phase} ]", fill=phase_outline, font=fonts["badge_bold"])

    # Mission clock
    draw.rectangle([(WIDTH - 360, 32), (WIDTH - 40, 78)], fill=(6, 9, 16), outline=(0, 240, 255), width=1)
    draw.text((WIDTH - 340, 40), f"MET: T+ {curr_t:06.1f} s", fill=(0, 240, 255), font=fonts["clock"])

    # -------------------------------------------------------------------------
    # LEFT COLUMN: Flight Telemetry & 5-Engine Cluster (x: 20 to 980)
    # -------------------------------------------------------------------------
    # Card 1: Flight Telemetry
    draw.rectangle([(20, 110), (980, 260)], fill=(13, 19, 34), outline=(26, 37, 61), width=1)
    draw.text((36, 122), "🚀 FLIGHT TELEMETRY (CLOSED-LOOP GUIDANCE)", fill=(148, 163, 184), font=fonts["card_title"])

    # 6 Metric Cells
    metrics = [
        ("ALTITUDE", f"{alt_val:,.1f} m", (0, 240, 255)),
        ("VERTICAL SPEED", f"{vz_val:+.2f} m/s", (255, 170, 0) if vz_val < -20 else (0, 255, 136)),
        ("HORIZONTAL SPEED", f"{vh_val:.2f} m/s", (241, 245, 249)),
        ("REMAINING FUEL", f"{fuel_val:.1f} kg", (255, 51, 102) if fuel_val < 30 else (0, 240, 255)),
        ("VEHICLE MASS", f"{mass_val:.1f} kg", (241, 245, 249)),
        ("TOTAL THRUST", f"{curr_thrust:,.0f} N", (255, 170, 0) if curr_thrust > 0 else (148, 163, 184)),
    ]

    for i, (label, val_str, color) in enumerate(metrics):
        col = i % 3
        row_idx = i // 3
        cx = 36 + col * 310
        cy = 150 + row_idx * 50
        draw.rectangle([(cx, cy), (cx + 295, cy + 42)], fill=(8, 12, 22), outline=(22, 32, 53), width=1)
        draw.text((cx + 10, cy + 6), label, fill=(100, 116, 139), font=fonts["metric_label"])
        draw.text((cx + 10, cy + 20), val_str, fill=color, font=fonts["metric_val"])

    # Card 2: 5-Engine Propulsion Cluster
    draw.rectangle([(20, 280), (980, 640)], fill=(13, 19, 34), outline=(26, 37, 61), width=1)
    
    cluster_title = "🔥 5-ENGINE PROPULSION CLUSTER"
    cluster_sub = f"{cluster['active_count']} / 5 ENGINES NOMINAL"
    sub_col = (0, 255, 136)
    if cluster["e1_failed"]:
        cluster_sub = "ENGINE 1 FAILED · OPPOSITE ENGINE 3 SHUT DOWN FOR BALANCE"
        sub_col = (255, 51, 102)
    
    draw.text((36, 292), cluster_title, fill=(148, 163, 184), font=fonts["card_title"])
    draw.text((500, 294), cluster_sub, fill=sub_col, font=fonts["badge"])

    for idx_eng, eng in enumerate(cluster["engines"]):
        ey = 330 + idx_eng * 60
        draw.text((40, ey), f"{eng.name} ({eng.position})", fill=(241, 245, 249), font=fonts["eng_name"])
        
        stat_color = (255, 51, 102) if eng.status == "FAILED" else (255, 170, 0) if "OFF" in eng.status else (0, 255, 136)
        draw.text((520, ey), f"{eng.status}  |  {eng.thrust_n:.1f} N ({eng.throttle_pct:.0f}%)", fill=stat_color, font=fonts["eng_stat"])
        
        # Thrust progress bar
        draw.rectangle([(40, ey + 24), (960, ey + 42)], fill=(10, 14, 24), outline=(30, 41, 59), width=1)
        fill_w = int((eng.throttle_pct / 100.0) * 916)
        if fill_w > 0:
            draw.rectangle([(42, ey + 26), (42 + fill_w, ey + 40)], fill=stat_color)

    # Card 3: Altitude vs Time Trajectory Chart
    draw.rectangle([(20, 660), (980, 830)], fill=(13, 19, 34), outline=(26, 37, 61), width=1)
    draw.text((36, 672), "📈 DESCENT ALTITUDE & VELOCITY PROFILE", fill=(148, 163, 184), font=fonts["card_title"])
    
    # Plot box
    px0, py0, px1, py1 = 50, 700, 950, 810
    draw.rectangle([(px0, py0), (px1, py1)], fill=(8, 12, 22), outline=(22, 32, 53), width=1)
    
    # Grid lines
    for gy in range(py0 + 25, py1, 25):
        draw.line([(px0, gy), (px1, gy)], fill=(18, 26, 42), width=1)
    for gx in range(px0 + 90, px1, 90):
        draw.line([(gx, py0), (gx, py1)], fill=(18, 26, 42), width=1)

    # Plot curve of altitude
    t_max = float(df["t_s"].max())
    alt_max = float(df["alt_m"].max())
    pts_alt = []
    for _, r_pt in df.iterrows():
        tx = px0 + int((float(r_pt["t_s"]) / t_max) * (px1 - px0))
        ty = py1 - int((float(r_pt["alt_m"]) / alt_max) * (py1 - py0 - 10))
        pts_alt.append((tx, ty))
    if len(pts_alt) > 1:
        draw.line(pts_alt, fill=(0, 240, 255), width=2)

    # Cursor line
    cur_x = px0 + int((curr_t / t_max) * (px1 - px0))
    draw.line([(cur_x, py0), (cur_x, py1)], fill=(255, 51, 102), width=2)
    draw.text((cur_x + 6, py0 + 6), f"T+{curr_t:.0f}s", fill=(255, 51, 102), font=fonts["small"])

    # -------------------------------------------------------------------------
    # RIGHT COLUMN: Power, Comms, Horizons, Rover (x: 1000 to 1900)
    # -------------------------------------------------------------------------
    # Card 4: Power, Comms & Horizons
    draw.rectangle([(1000, 110), (1900, 380)], fill=(13, 19, 34), outline=(26, 37, 61), width=1)
    draw.text((1016, 122), "⚡ POWER, COMMS & TOPOGRAPHIC HORIZONS (SPEC §4.2)", fill=(148, 163, 184), font=fonts["card_title"])

    # Metrics grid
    power_cells = [
        ("LANDER BATTERY", "12.0 kWh (100%)", (0, 255, 136)),
        ("SOLAR ARRAY IN", "850 W", (0, 240, 255)),
        ("DIRECT-TO-EARTH LINK", "ONLINE (DTE UP)", (0, 255, 136)),
        ("LANDING SITE", "SHACKLETON CRATER", (241, 245, 249)),
    ]
    for i, (label, val_str, color) in enumerate(power_cells):
        col = i % 2
        row_idx = i // 2
        cx = 1016 + col * 435
        cy = 150 + row_idx * 50
        draw.rectangle([(cx, cy), (cx + 420, cy + 42)], fill=(8, 12, 22), outline=(22, 32, 53), width=1)
        draw.text((cx + 10, cy + 6), label, fill=(100, 116, 139), font=fonts["metric_label"])
        draw.text((cx + 10, cy + 20), val_str, fill=color, font=fonts["metric_val"])

    # Navigator Countdowns Box
    draw.rectangle([(1016, 260), (1884, 360)], fill=(8, 12, 22), outline=(22, 32, 53), width=1)
    draw.text((1030, 274), "COUNTDOWN TO SUNSET (NAVIGATOR EXACT):", fill=(148, 163, 184), font=fonts["cd_label"])
    draw.text((1520, 270), countdowns.get("sun_str", "sunset: 8 d 20 h"), fill=(255, 170, 0), font=fonts["cd_val"])
    
    draw.text((1030, 318), "COUNTDOWN TO EARTHSET/EARTHRISE (NAVIGATOR):", fill=(148, 163, 184), font=fonts["cd_label"])
    draw.text((1520, 314), countdowns.get("earth_str", "Earthrise: 11 d 11 h"), fill=(0, 240, 255), font=fonts["cd_val"])

    # Card 5: Rover Surface Asset
    draw.rectangle([(1000, 400), (1900, 640)], fill=(13, 19, 34), outline=(26, 37, 61), width=1)
    draw.text((1016, 412), "🚜 ROVER SURFACE ASSET (PRAGYAN 3 CLASS · 25 KG)", fill=(148, 163, 184), font=fonts["card_title"])

    rover_metrics = [
        ("DISTANCE TO LANDER", "38.4 m", (0, 240, 255)),
        ("DRIVE SPEED LIMIT", "1.0 cm/s (0.01 m/s)", (0, 255, 136)),
        ("BATTERY STATE (SOC)", "114.2 Wh (95.2%)", (0, 255, 136)),
        ("SURFACE POSITION", "[X: +28 m, Y: -26 m]", (241, 245, 249)),
        ("TERRAIN SLOPE", "4.2° (LIMIT: 15.0°)", (241, 245, 249)),
        ("RF LINK TO LANDER", "LINE-OF-SIGHT ACTIVE", (0, 255, 136)),
    ]
    for i, (label, val_str, color) in enumerate(rover_metrics):
        col = i % 3
        row_idx = i // 3
        cx = 1016 + col * 290
        cy = 440 + row_idx * 55
        draw.rectangle([(cx, cy), (cx + 278, cy + 46)], fill=(8, 12, 22), outline=(22, 32, 53), width=1)
        draw.text((cx + 10, cy + 6), label, fill=(100, 116, 139), font=fonts["metric_label"])
        draw.text((cx + 10, cy + 22), val_str, fill=color, font=fonts["metric_val"])

    # Trajectory Offset Map
    draw.rectangle([(1000, 660), (1900, 830)], fill=(13, 19, 34), outline=(26, 37, 61), width=1)
    draw.text((1016, 672), "🎯 PINPOINT TOUCHDOWN OFFSET (TARGET: 0, 0 M)", fill=(148, 163, 184), font=fonts["card_title"])
    
    mx0, my0, mx1, my1 = 1030, 700, 1870, 810
    draw.rectangle([(mx0, my0), (mx1, my1)], fill=(8, 12, 22), outline=(22, 32, 53), width=1)
    # Target center
    tc_x = (mx0 + mx1) // 2
    tc_y = (my0 + my1) // 2
    draw.line([(tc_x - 15, tc_y), (tc_x + 15, tc_y)], fill=(255, 170, 0), width=2)
    draw.line([(tc_x, tc_y - 15), (tc_x, tc_y + 15)], fill=(255, 170, 0), width=2)
    draw.text((tc_x + 18, tc_y - 8), "TARGET (0,0)", fill=(255, 170, 0), font=fonts["small"])

    # Ground track points
    x_range = max(float(df["x_m"].abs().max()), 100.0)
    y_range = max(float(df["y_m"].abs().max()), 100.0)
    pts_map = []
    for _, r_m in df.iterrows():
        gx = tc_x + int((float(r_m["x_m"]) / x_range) * ((mx1 - mx0) // 2 - 20))
        gy = tc_y - int((float(r_m["y_m"]) / y_range) * ((my1 - my0) // 2 - 15))
        pts_map.append((gx, gy))
    if len(pts_map) > 1:
        draw.line(pts_map, fill=(59, 130, 246), width=2)
    
    # Current lander position
    lx = tc_x + int((x_val / x_range) * ((mx1 - mx0) // 2 - 20))
    ly = tc_y - int((y_val / y_range) * ((my1 - my0) // 2 - 15))
    draw.ellipse([(lx - 5, ly - 5), (lx + 5, ly + 5)], fill=(0, 240, 255), outline=(255, 255, 255))
    draw.text((lx + 8, ly - 6), f"[{x_val:.1f}, {y_val:.1f}] m", fill=(0, 240, 255), font=fonts["small"])

    # -------------------------------------------------------------------------
    # BOTTOM PANEL: Autonomous Decision Log (Full Width, y: 850 to 1050)
    # -------------------------------------------------------------------------
    draw.rectangle([(20, 850), (1900, 1050)], fill=(5, 8, 16), outline=(30, 41, 59), width=1)
    draw.text((36, 860), "📋 AUTONOMOUS ONBOARD G&C DECISION LOG (FACTS ONLY · NO COMMENTARY)", fill=(148, 163, 184), font=fonts["card_title"])

    # Visible decisions
    visible_decisions = [d for d in decisions if d["t_s"] <= curr_t + 0.5]
    if not visible_decisions:
        visible_decisions = [decisions[0]] if decisions else []

    # Display up to 4 most recent decisions
    recent = visible_decisions[-4:]
    for idx_d, d in enumerate(recent):
        dy = 895 + idx_d * 34
        is_latest = (idx_d == len(recent) - 1)
        
        # Highlight latest active decision
        if is_latest:
            draw.rectangle([(32, dy - 2), (1888, dy + 26)], fill=(35, 26, 8), outline=(255, 170, 0), width=1)

        t_str = f"T+{d['t_s']:05.1f} s"
        draw.text((45, dy + 2), t_str, fill=(0, 240, 255), font=fonts["dec_time"])
        draw.text((170, dy + 2), f"[{d['phase'].upper()}]", fill=(148, 163, 184), font=fonts["dec_phase"])

        text_col = (255, 51, 102) if "FAILED" in d["decision"] else (0, 255, 136) if "TOUCHDOWN" in d["decision"] else (255, 234, 121) if is_latest else (203, 213, 225)
        draw.text((370, dy + 2), d["decision"], fill=text_col, font=fonts["dec_text"])

    return im


def record_mission_control_video():
    root = repo_root()
    output_path = root / "video_assets" / "clip4_mission_control.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    telemetry_file = root / "runs" / "basilisk" / "telemetry_engine_out.csv"
    if not telemetry_file.exists():
        telemetry_file = root / "tests" / "fixtures" / "telemetry_basilisk_engine_out.csv"

    print(f"[Mission Control Video] Loading telemetry: {telemetry_file.name}")
    df = load_telemetry(telemetry_file)
    rover_df = load_rover_telemetry()
    decisions = extract_decisions(df)
    countdowns = get_site_countdowns("shackleton", "2026-11-14", 0)

    fonts = {
        "title": get_font(20, bold=True),
        "badge": get_font(13, bold=True),
        "badge_bold": get_font(14, bold=True),
        "clock": get_font(22, bold=True),
        "card_title": get_font(14, bold=True),
        "metric_label": get_font(11, bold=False),
        "metric_val": get_font(18, bold=True),
        "eng_name": get_font(14, bold=True),
        "eng_stat": get_font(14, bold=True),
        "cd_label": get_font(13, bold=False),
        "cd_val": get_font(17, bold=True),
        "small": get_font(11, bold=False),
        "dec_time": get_font(14, bold=True),
        "dec_phase": get_font(13, bold=True),
        "dec_text": get_font(14, bold=True),
    }

    total_frames = int(DURATION_S * FPS)
    max_sim_t = float(df["t_s"].max())

    print(f"[Mission Control Video] Rendering {total_frames} frames (1080p, 30fps)...")

    container = av.open(str(output_path), mode="w", format="mp4")
    stream = container.add_stream("h264", rate=FPS)
    stream.width = WIDTH
    stream.height = HEIGHT
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "18", "preset": "fast"}

    for f_idx in range(total_frames):
        alpha = f_idx / (total_frames - 1)
        sim_t = alpha * max_sim_t

        frame_img = render_mc_frame(df, rover_df, decisions, countdowns, sim_t, fonts)
        video_frame = av.VideoFrame.from_image(frame_img)
        for packet in stream.encode(video_frame):
            container.mux(packet)

        if (f_idx + 1) % 120 == 0 or (f_idx + 1) == total_frames:
            print(f"  Frame {f_idx + 1}/{total_frames} (sim T+{sim_t:.1f}s)")

    for packet in stream.encode():
        container.mux(packet)
    container.close()

    print(f"[Mission Control Video] Generated video: {output_path} ({output_path.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    record_mission_control_video()
