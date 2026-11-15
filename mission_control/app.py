"""Mission Control Console (Port 8502) · Spec §9.2 (Arnav).

Launch command:
    streamlit run mission_control/app.py --server.port 8502

Displays live flight telemetry, 5-engine cluster status, power & comms,
Navigator-matched countdowns, rover mini-panel, and autonomous decision log.
Strictly reads and displays files; no physics calculations are performed here.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from contracts.paths import repo_root
from mission_control.data import (
    extract_decisions,
    get_available_telemetry_files,
    get_site_countdowns,
    load_rover_telemetry,
    load_telemetry,
    parse_engine_cluster,
)

# Page configuration
st.set_page_config(
    page_title="Mission Control | Lunar Operations",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------------------------
# Dark "Mission Control" Theme Styling
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* Dark console background */
    .stApp {
        background-color: #070b12;
        color: #d1d5db;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Header bar */
    .mc-header {
        background: linear-gradient(90deg, #0e1526 0%, #111b33 100%);
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 14px 20px;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
    }
    
    .mc-title {
        font-size: 1.35rem;
        font-weight: 700;
        letter-spacing: 1px;
        color: #f8fafc;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    
    .mc-clock {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 1.5rem;
        font-weight: 700;
        color: #00f0ff;
        text-shadow: 0 0 10px rgba(0, 240, 255, 0.4);
        background: #060910;
        padding: 4px 14px;
        border-radius: 6px;
        border: 1px solid #00f0ff33;
    }
    
    /* Phase Pill Badges */
    .phase-badge {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
        font-size: 0.95rem;
        font-weight: 700;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        padding: 6px 14px;
        border-radius: 6px;
        display: inline-block;
    }
    .phase-powered_descent, .phase-descent {
        background: rgba(0, 240, 255, 0.15);
        color: #00f0ff;
        border: 1px solid #00f0ff;
        box-shadow: 0 0 8px rgba(0, 240, 255, 0.3);
    }
    .phase-terminal, .phase-hover {
        background: rgba(255, 170, 0, 0.15);
        color: #ffaa00;
        border: 1px solid #ffaa00;
        box-shadow: 0 0 8px rgba(255, 170, 0, 0.3);
    }
    .phase-touchdown, .phase-surface {
        background: rgba(0, 255, 136, 0.15);
        color: #00ff88;
        border: 1px solid #00ff88;
        box-shadow: 0 0 8px rgba(0, 255, 136, 0.3);
    }
    .phase-night {
        background: rgba(147, 51, 234, 0.15);
        color: #c084fc;
        border: 1px solid #a855f7;
    }
    .phase-orbit, .phase-release, .phase-deorbit {
        background: rgba(59, 130, 246, 0.15);
        color: #60a5fa;
        border: 1px solid #3b82f6;
    }

    /* Provenance Badges */
    .badge-fixture {
        background: #3b111a;
        color: #ff3366;
        border: 1px solid #ff3366;
        font-weight: 700;
        font-size: 0.8rem;
        padding: 3px 8px;
        border-radius: 4px;
        letter-spacing: 1px;
    }
    .badge-modelled {
        background: #2e1d05;
        color: #ffaa00;
        border: 1px solid #ffaa00;
        font-weight: 700;
        font-size: 0.8rem;
        padding: 3px 8px;
        border-radius: 4px;
        letter-spacing: 1px;
    }

    /* Panel cards */
    .mc-card {
        background: #0d1322;
        border: 1px solid #1a253d;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 14px;
    }
    .mc-card-title {
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        color: #94a3b8;
        margin-bottom: 12px;
        font-weight: 600;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #1a253d;
        padding-bottom: 6px;
    }
    
    /* Metrics display */
    .metric-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 10px;
    }
    .metric-cell {
        background: #080c16;
        border: 1px solid #162035;
        border-radius: 6px;
        padding: 10px 12px;
    }
    .metric-label {
        font-size: 0.72rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 4px;
    }
    .metric-value {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 1.25rem;
        font-weight: 700;
        color: #f1f5f9;
    }
    .metric-unit {
        font-size: 0.75rem;
        color: #94a3b8;
        margin-left: 4px;
    }

    /* Engine Cluster visual */
    .engine-bar-wrap {
        margin: 6px 0;
    }
    .engine-header {
        display: flex;
        justify-content: space-between;
        font-size: 0.78rem;
        margin-bottom: 3px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
    }
    .engine-bar-bg {
        background: #0a0e18;
        border: 1px solid #1e293b;
        height: 14px;
        border-radius: 3px;
        overflow: hidden;
    }
    .engine-bar-fill {
        height: 100%;
        transition: width 0.2s ease;
    }

    /* Decision Log */
    .decision-terminal {
        background: #050810;
        border: 1px solid #1e293b;
        border-radius: 6px;
        padding: 12px 14px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 0.85rem;
        max-height: 220px;
        overflow-y: auto;
    }
    .decision-line {
        padding: 4px 0;
        border-bottom: 1px solid #111a2e;
        color: #94a3b8;
    }
    .decision-time {
        color: #00f0ff;
        font-weight: 600;
        margin-right: 8px;
    }
    .decision-alert {
        color: #ff3366;
        font-weight: 700;
    }
    .decision-success {
        color: #00ff88;
        font-weight: 600;
    }
    .decision-highlight {
        background: rgba(255, 170, 0, 0.12);
        color: #ffea79;
        font-weight: 600;
        padding: 4px 8px;
        border-left: 3px solid #ffaa00;
        margin: 4px 0;
        border-radius: 0 4px 4px 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Sidebar: File Picker and Mission Configuration
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🛰️ Telemetry Input")
    available_files = get_available_telemetry_files()

    if not available_files:
        st.error("No telemetry CSV files found in `tests/fixtures` or `runs/basilisk`.")
        st.stop()

    file_names = [f.name for f in available_files]
    # Default to the real engine-out run or fixture
    default_idx = 0
    for idx, f in enumerate(available_files):
        if "telemetry_engine_out.csv" in f.name:
            default_idx = idx
            break
        elif "engine_out" in f.name:
            default_idx = idx

    selected_name = st.selectbox(
        "Choose flight log to replay:",
        file_names,
        index=default_idx,
        help="Select any Basilisk flight log or tests/fixtures stand-in.",
    )

    selected_file = next(f for f in available_files if f.name == selected_name)

    st.markdown("---")
    st.markdown("### 🌍 Landing Site & Light")
    site = st.selectbox("Site Region:", ["shackleton", "demo_craters", "malapert"], index=0)
    date = st.selectbox("Mission Epoch:", ["2026-11-14", "2027-03-01"], index=0)

    st.markdown("---")
    st.markdown("### ℹ️ Mission Info")
    st.caption(f"**Loaded File**: `{selected_file.path.name}`")
    st.caption(f"**Rows**: {selected_file.row_count}")
    if selected_file.is_fixture:
        st.markdown('<span class="badge-fixture">FIXTURE — STAND-IN</span>', unsafe_allow_html=True)
        st.caption("Using fixture dataset for testing Mission Control console.")
    else:
        st.markdown('<span class="badge-modelled">MODELLED · Basilisk</span>', unsafe_allow_html=True)
        st.caption("Real 6-DOF closed-loop flight simulation log.")

# -----------------------------------------------------------------------------
# Load Telemetry and Rover Data
# -----------------------------------------------------------------------------
df = load_telemetry(selected_file.path)
rover_df = load_rover_telemetry()
decisions = extract_decisions(df)

if df.empty:
    st.error("Telemetry file contains no rows.")
    st.stop()

n_rows = len(df)
max_t = float(df["t_s"].max()) if pd.notna(df["t_s"].max()) else float(n_rows)

# -----------------------------------------------------------------------------
# Replay State & Session Controls
# -----------------------------------------------------------------------------
if "current_step" not in st.session_state:
    st.session_state.current_step = 0
if "is_playing" not in st.session_state:
    st.session_state.is_playing = False

# Quick Milestone Jump functions
col_ctrl1, col_ctrl2, col_ctrl3, col_ctrl4 = st.columns([2, 1, 1, 2])
with col_ctrl1:
    # Scrub slider over time
    step = st.slider(
        "⏱️ Replay Timeline (Time t_s)",
        min_value=0,
        max_value=n_rows - 1,
        value=min(st.session_state.current_step, n_rows - 1),
        format="%d step",
        key="timeline_scrubber",
        help="Scrub to inspect any point in the flight telemetry.",
    )
    st.session_state.current_step = step

with col_ctrl2:
    speed = st.selectbox("Speed:", ["1×", "10×", "100×"], index=1)

with col_ctrl3:
    c_back, c_fwd = st.columns(2)
    with c_back:
        if st.button("⏮ -5s", use_container_width=True):
            st.session_state.current_step = max(0, st.session_state.current_step - 5)
            st.rerun()
    with c_fwd:
        if st.button("⏭ +5s", use_container_width=True):
            st.session_state.current_step = min(n_rows - 1, st.session_state.current_step + 5)
            st.rerun()

with col_ctrl4:
    # Key Milestones Jump
    milestone_options = ["Jump to Milestone..."]
    for d in decisions:
        label = f"T+{d['t_s']:.0f}s: {d['decision'][:28]}..."
        milestone_options.append(label)
    
    selected_milestone = st.selectbox("Milestones:", milestone_options, label_visibility="collapsed")
    if selected_milestone != "Jump to Milestone...":
        idx_match = milestone_options.index(selected_milestone) - 1
        target_t = decisions[idx_match]["t_s"]
        # Find closest row index
        closest_row = int((df["t_s"] - target_t).abs().argmin())
        st.session_state.current_step = closest_row
        st.rerun()

# -----------------------------------------------------------------------------
# Current Timestep Telemetry Data
# -----------------------------------------------------------------------------
row = df.iloc[st.session_state.current_step]
curr_t = float(row["t_s"]) if pd.notna(row["t_s"]) else 0.0
curr_phase = str(row["phase"]).replace(" ", "_").lower()
curr_engines_ok = int(row["engines_ok"]) if pd.notna(row["engines_ok"]) else 5
curr_decision = str(row["decision"]) if pd.notna(row["decision"]) else ""
curr_thrust = float(row["thrust_n"]) if pd.notna(row["thrust_n"]) else 0.0

# -----------------------------------------------------------------------------
# Top Header Bar
# -----------------------------------------------------------------------------
provenance_html = (
    '<span class="badge-fixture">FIXTURE</span>'
    if selected_file.is_fixture
    else '<span class="badge-modelled">MODELLED · Basilisk</span>'
)

phase_label = curr_phase.replace("_", " ").upper()
st.markdown(
    f"""
    <div class="mc-header">
        <div class="mc-title">
            <span>🌙 MISSION OPERATIONS CONSOLE</span>
            {provenance_html}
            <span class="phase-badge phase-{curr_phase}">{phase_label}</span>
        </div>
        <div class="mc-clock">
            MET: T+ {curr_t:06.1f} s
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Main Console Grid: Flight Telemetry & 5-Engine Cluster vs Power/Comms & Rover
# -----------------------------------------------------------------------------
col_flight, col_power = st.columns([1.1, 0.9])

with col_flight:
    st.markdown('<div class="mc-card">', unsafe_allow_html=True)
    st.markdown('<div class="mc-card-title">🚀 Flight Telemetry</div>', unsafe_allow_html=True)

    alt_val = float(row["alt_m"]) if pd.notna(row["alt_m"]) else 0.0
    vz_val = float(row["vz_m_s"]) if pd.notna(row["vz_m_s"]) else 0.0
    vh_val = float(row["v_horizontal_m_s"]) if pd.notna(row["v_horizontal_m_s"]) else 0.0
    fuel_val = float(row["fuel_kg"]) if pd.notna(row["fuel_kg"]) else 0.0
    mass_val = float(row["mass_kg"]) if pd.notna(row["mass_kg"]) else 0.0
    x_val = float(row["x_m"]) if pd.notna(row["x_m"]) else 0.0
    y_val = float(row["y_m"]) if pd.notna(row["y_m"]) else 0.0

    st.markdown(
        f"""
        <div class="metric-grid">
            <div class="metric-cell">
                <div class="metric-label">Altitude</div>
                <div class="metric-value">{alt_val:,.1f}<span class="metric-unit">m</span></div>
            </div>
            <div class="metric-cell">
                <div class="metric-label">Vertical Speed (Vz)</div>
                <div class="metric-value" style="color: {'#ffaa00' if vz_val < -20 else '#00ff88'}">{vz_val:+.2f}<span class="metric-unit">m/s</span></div>
            </div>
            <div class="metric-cell">
                <div class="metric-label">Horizontal Speed (Vh)</div>
                <div class="metric-value">{vh_val:.2f}<span class="metric-unit">m/s</span></div>
            </div>
            <div class="metric-cell">
                <div class="metric-label">Usable Propellant</div>
                <div class="metric-value" style="color: {'#ff3366' if fuel_val < 30 else '#00f0ff'}">{fuel_val:.1f}<span class="metric-unit">kg</span></div>
            </div>
            <div class="metric-cell">
                <div class="metric-label">Vehicle Mass</div>
                <div class="metric-value">{mass_val:.1f}<span class="metric-unit">kg</span></div>
            </div>
            <div class="metric-cell">
                <div class="metric-label">Total Thrust</div>
                <div class="metric-value">{curr_thrust:,.0f}<span class="metric-unit">N</span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # 5-Engine Cluster Status
    st.markdown('<div class="mc-card">', unsafe_allow_html=True)
    engine_state = parse_engine_cluster(curr_engines_ok, curr_decision, curr_thrust)
    status_summary = f"{engine_state['active_count']} / 5 ENGINES NOMINAL"
    if engine_state["e1_failed"]:
        status_summary = "ENGINE 1 FAILED · E3 BALANCED OFF"

    st.markdown(
        f"""
        <div class="mc-card-title">
            <span>🔥 5-Engine Propulsion Cluster</span>
            <span style="font-family: monospace; font-size: 0.8rem; color: {'#ff3366' if engine_state['e1_failed'] else '#00ff88'}">{status_summary}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for eng in engine_state["engines"]:
        st.markdown(
            f"""
            <div class="engine-bar-wrap">
                <div class="engine-header">
                    <span><strong>{eng.name}</strong> ({eng.position})</span>
                    <span style="color: {eng.color}; font-weight: 600;">{eng.status} &nbsp;|&nbsp; {eng.thrust_n:.1f} N ({eng.throttle_pct:.0f}%)</span>
                </div>
                <div class="engine-bar-bg">
                    <div class="engine-bar-fill" style="width: {eng.throttle_pct}%; background: {eng.color};"></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    # Real-Time Plotly Chart: Altitude and Velocity Profiles
    st.markdown('<div class="mc-card">', unsafe_allow_html=True)
    st.markdown('<div class="mc-card-title">📈 Trajectory Profile</div>', unsafe_allow_html=True)

    fig_traj = go.Figure()
    # Past trajectory up to current step
    df_sub = df.iloc[: st.session_state.current_step + 1]

    fig_traj.add_trace(
        go.Scatter(
            x=df["t_s"],
            y=df["alt_m"],
            name="Altitude (m)",
            line=dict(color="#00f0ff", width=2),
            hoverinfo="x+y",
        )
    )
    fig_traj.add_trace(
        go.Scatter(
            x=df["t_s"],
            y=df["vz_m_s"],
            name="Vertical Speed (m/s)",
            line=dict(color="#ffaa00", width=1.5, dash="dot"),
            yaxis="y2",
            hoverinfo="x+y",
        )
    )

    # Current scrubber position line
    fig_traj.add_vline(
        x=curr_t,
        line_width=2,
        line_dash="dash",
        line_color="#ff3366",
        annotation_text=f"T+{curr_t:.0f}s",
        annotation_position="top left",
    )

    fig_traj.update_layout(
        paper_bgcolor="#080c16",
        plot_bgcolor="#080c16",
        height=240,
        margin=dict(l=40, r=40, t=10, b=30),
        xaxis=dict(
            title="Time (s)",
            titlefont=dict(color="#64748b", size=10),
            tickfont=dict(color="#94a3b8", size=9),
            gridcolor="#162035",
            showgrid=True,
        ),
        yaxis=dict(
            title="Altitude (m)",
            titlefont=dict(color="#00f0ff", size=10),
            tickfont=dict(color="#00f0ff", size=9),
            gridcolor="#162035",
            showgrid=True,
        ),
        yaxis2=dict(
            title="Speed (m/s)",
            titlefont=dict(color="#ffaa00", size=10),
            tickfont=dict(color="#ffaa00", size=9),
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color="#94a3b8", size=9),
        ),
    )
    st.plotly_chart(fig_traj, use_container_width=True, config={"displayModeBar": False})
    st.markdown("</div>", unsafe_allow_html=True)


with col_power:
    # Power and Comms Panel
    st.markdown('<div class="mc-card">', unsafe_allow_html=True)
    st.markdown('<div class="mc-card-title">⚡ Power, Comms & Horizons</div>', unsafe_allow_html=True)

    # Read power fields (or show "—" when not present in flight log)
    bat_val = row["battery_wh"] if pd.notna(row["battery_wh"]) else None
    solar_val = row["solar_w"] if pd.notna(row["solar_w"]) else None
    earth_val = row["earth_visible"] if pd.notna(row["earth_visible"]) else None

    bat_display = f"{float(bat_val):,.0f} Wh" if bat_val is not None else "—"
    solar_display = f"{float(solar_val):,.0f} W" if solar_val is not None else "—"
    
    if earth_val is not None:
        earth_status = "ONLINE" if float(earth_val) > 0.5 else "OCCLUDED"
        earth_color = "#00ff88" if float(earth_val) > 0.5 else "#ff3366"
    else:
        earth_status = "STANDBY"
        earth_color = "#94a3b8"

    # Query matching Navigator countdowns for this site and epoch
    countdowns = get_site_countdowns(site, date, step_hour=0)

    st.markdown(
        f"""
        <div class="metric-grid" style="grid-template-columns: repeat(2, 1fr); margin-bottom: 12px;">
            <div class="metric-cell">
                <div class="metric-label">Lander Battery</div>
                <div class="metric-value">{bat_display}</div>
            </div>
            <div class="metric-cell">
                <div class="metric-label">Solar Array In</div>
                <div class="metric-value">{solar_display}</div>
            </div>
            <div class="metric-cell">
                <div class="metric-label">Direct-to-Earth Link</div>
                <div class="metric-value" style="color: {earth_color}">{earth_status}</div>
            </div>
            <div class="metric-cell">
                <div class="metric-label">Target Region</div>
                <div class="metric-value" style="font-size: 1.05rem; text-transform: uppercase;">{site}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Navigator-matched Countdowns
    st.markdown(
        f"""
        <div style="background: #080c16; border: 1px solid #162035; border-radius: 6px; padding: 10px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-size: 0.75rem; color: #64748b; text-transform: uppercase;">Next Solar Event</span>
                <span style="font-family: monospace; font-size: 0.95rem; font-weight: 700; color: #ffaa00;">{countdowns['sun_str']}</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-size: 0.75rem; color: #64748b; text-transform: uppercase;">Next Direct-to-Earth Link</span>
                <span style="font-family: monospace; font-size: 0.95rem; font-weight: 700; color: #00f0ff;">{countdowns['earth_str']}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # Rover Mini-Panel (Spec §4.3)
    st.markdown('<div class="mc-card">', unsafe_allow_html=True)
    st.markdown('<div class="mc-card-title">🚜 Rover Surface Asset (Pragyan 3)</div>', unsafe_allow_html=True)

    if rover_df is not None and not rover_df.empty:
        # Match rover step or show nominal initial state
        r_step = min(st.session_state.current_step, len(rover_df) - 1)
        r_row = rover_df.iloc[r_step]
        r_x = float(r_row["x_m"]) if "x_m" in r_row else 0.0
        r_y = float(r_row["y_m"]) if "y_m" in r_row else 0.0
        r_dist = float(r_row["distance_to_lander_m"]) if "distance_to_lander_m" in r_row else np.sqrt(r_x**2 + r_y**2)
        r_bat = float(r_row["battery_pct"]) if "battery_pct" in r_row else 100.0
        r_speed = float(r_row["speed_mps"]) if "speed_mps" in r_row else 0.01
        r_link = int(r_row["link_los"]) if "link_los" in r_row else 1
        r_slope = float(r_row["slope_deg"]) if "slope_deg" in r_row else 2.5

        link_text = "CONNECTED" if r_link == 1 else "OCCLUDED"
        link_col = "#00ff88" if r_link == 1 else "#ff3366"

        st.markdown(
            f"""
            <div class="metric-grid" style="grid-template-columns: repeat(3, 1fr);">
                <div class="metric-cell">
                    <div class="metric-label">Rover Distance</div>
                    <div class="metric-value">{r_dist:.1f}<span class="metric-unit">m</span></div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Drive Speed</div>
                    <div class="metric-value">{r_speed * 100:.1f}<span class="metric-unit">cm/s</span></div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Battery SOC</div>
                    <div class="metric-value">{r_bat:.1f}<span class="metric-unit">%</span></div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Position (X, Y)</div>
                    <div class="metric-value" style="font-size: 1.0rem;">[{r_x:.0f}, {r_y:.0f}]<span class="metric-unit">m</span></div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">Terrain Slope</div>
                    <div class="metric-value" style="color: {'#ffaa00' if r_slope > 12 else '#f1f5f9'}">{r_slope:.1f}<span class="metric-unit">°</span></div>
                </div>
                <div class="metric-cell">
                    <div class="metric-label">RF to Lander</div>
                    <div class="metric-value" style="color: {link_col}; font-size: 1.05rem;">{link_text}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.caption("Rover surface telemetry file not found in runs/basilisk. Displaying vehicle specifications:")
        st.markdown(
            """
            <div class="metric-grid" style="grid-template-columns: repeat(3, 1fr);">
                <div class="metric-cell"><div class="metric-label">Asset Mass</div><div class="metric-value">25.0<span class="metric-unit">kg</span></div></div>
                <div class="metric-cell"><div class="metric-label">Speed Limit</div><div class="metric-value">1.0<span class="metric-unit">cm/s</span></div></div>
                <div class="metric-cell"><div class="metric-label">Max Slope</div><div class="metric-value">15.0<span class="metric-unit">°</span></div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    # Horizontal Landing Offset & Trajectory Map
    st.markdown('<div class="mc-card">', unsafe_allow_html=True)
    st.markdown('<div class="mc-card-title">🎯 Horizontal Touchdown Offset</div>', unsafe_allow_html=True)

    fig_map = go.Figure()
    # Entire ground track
    fig_map.add_trace(
        go.Scatter(
            x=df["x_m"],
            y=df["y_m"],
            mode="lines",
            name="Descent Track",
            line=dict(color="#3b82f6", width=2),
        )
    )
    # Target (0, 0)
    fig_map.add_trace(
        go.Scatter(
            x=[0],
            y=[0],
            mode="markers",
            name="Target (0,0)",
            marker=dict(size=10, color="#ffaa00", symbol="cross"),
        )
    )
    # Current Spacecraft Position
    fig_map.add_trace(
        go.Scatter(
            x=[x_val],
            y=[y_val],
            mode="markers",
            name="Lander",
            marker=dict(size=12, color="#00f0ff", symbol="circle"),
        )
    )

    fig_map.update_layout(
        paper_bgcolor="#080c16",
        plot_bgcolor="#080c16",
        height=180,
        margin=dict(l=40, r=40, t=10, b=30),
        xaxis=dict(
            title="Easting (m)",
            titlefont=dict(color="#64748b", size=9),
            tickfont=dict(color="#94a3b8", size=8),
            gridcolor="#162035",
            showgrid=True,
        ),
        yaxis=dict(
            title="Northing (m)",
            titlefont=dict(color="#64748b", size=9),
            tickfont=dict(color="#94a3b8", size=8),
            gridcolor="#162035",
            showgrid=True,
            scaleanchor="x",
            scaleratio=1,
        ),
        showlegend=False,
    )
    st.plotly_chart(fig_map, use_container_width=True, config={"displayModeBar": False})
    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Bottom Panel: Autonomous Decision Log
# -----------------------------------------------------------------------------
st.markdown('<div class="mc-card">', unsafe_allow_html=True)
st.markdown('<div class="mc-card-title">📋 Autonomous Decision Log (Onboard G&C Facts Only)</div>', unsafe_allow_html=True)

if decisions:
    lines_html = []
    for d in decisions:
        is_current = (abs(d["t_s"] - curr_t) <= 1.0) or (d["t_s"] <= curr_t and d == decisions[-1])
        cls = "decision-highlight" if is_current else "decision-line"
        
        # Color coding text based on keywords
        text = d["decision"]
        if "FAILED" in text or "failure" in text.lower():
            text = f'<span class="decision-alert">{text}</span>'
        elif "ok" in text.lower() or "touchdown" in text.lower():
            text = f'<span class="decision-success">{text}</span>'

        lines_html.append(
            f'<div class="{cls}"><span class="decision-time">T+{d["t_s"]:05.1f} s</span> [{d["phase"].upper()}] {text}</div>'
        )
    
    st.markdown(
        f'<div class="decision-terminal">{"".join(lines_html)}</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="decision-terminal"><div class="decision-line" style="color: #64748b;">No autonomous re-target or fault decisions recorded in this run.</div></div>',
        unsafe_allow_html=True,
    )

st.markdown("</div>", unsafe_allow_html=True)
