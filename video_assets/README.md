# Basilisk & Vizard 3D Hero Video Assets

This directory contains the 3 high-definition **1080p (1920×1080 @ 30 fps, H.264)** hero video clips demonstrating end-to-end mission flight dynamics, terrain hazard mitigation, and surface science prospecting in Basilisk and Vizard.

Per **SIMULATION_TEAM_HANDBOOK.md (§4 A3 / KAN-47)**, 60% of the project video is the hero lander and rover footage. All 3 clips are generated from physics-accurate Basilisk simulations with real NASA LOLA digital elevation model (DEM) terrain data.

---

## 1. Video Clips Directory

| File | Resolution | Duration | Milestone / Maneuver | Provenance & Labels |
|---|---|---|---|---|
| [`clip1_orbit_release.mp4`](clip1_orbit_release.mp4) | 1080p (1920×1080) | 12.0 s (360 frames @ 30 fps) | 100 km polar orbit $\to$ carrier release $\to$ $-19.5\text{ m/s}$ deorbit burn $\to$ coast to 15.00 km PDI | `MODELLED · Basilisk / LOLA`<br>`vertical exaggeration ×1.0` |
| [`clip2_descent_engine_out.mp4`](clip2_descent_engine_out.mp4) | 1080p (1920×1080) | 13.0 s (390 frames @ 30 fps) | 2 km terminal descent $\to$ Engine 1 fails at $t=20\text{ s}$ $\to$ Engine 3 balanced $\to$ touchdown on cratered DEM | `MODELLED · Basilisk 6-DOF`<br>`vertical exaggeration ×1.5` |
| [`clip3_rover_ice_traverse.mp4`](clip3_rover_ice_traverse.mp4) | 1080p (1920×1080) | 14.0 s (420 frames @ 30 fps) | 25 kg rover traverses 98.7 m to ice target in cold-trap shadow $\to$ returns to lander at sunset | `MODELLED · Basilisk Kinematic`<br>`vertical exaggeration ×1.5`<br>`playback speedup 60×` |
| [`clip4_mission_control.mp4`](clip4_mission_control.mp4) | 1080p (1920×1080) | 16.0 s (480 frames @ 30 fps) | Live Streamlit Mission Control (port 8502): telemetry, 5-engine fault balancing, countdowns, rover, decision log | `MODELLED · Basilisk / Streamlit`<br>`no commentary · facts only` |

---

## 2. Detailed Clip Descriptions

### Clip 1: Orbit $\to$ Release $\to$ Deorbit $\to$ Powered-Descent Initiation (PDI)
- **File**: `video_assets/clip1_orbit_release.mp4`
- **Context**: Spec §4.1, §7.1, KAN-41
- **Flight Dynamics**:
  - $100\text{ km}$ circular lunar polar orbit ($T = 117.8\text{ min}$, $v = 1,633.9\text{ m/s}$).
  - Lander stack ($1,500\text{ kg}$ lander wet mass + $900\text{ kg}$ carrier propulsion module dry mass).
  - At $t = 600\text{ s}$, carrier release separates the stack: carrier continues in $100\text{ km}$ circular orbit while lander reorients to retrograde.
  - Impulsive deorbit burn ($\Delta v = -19.5\text{ m/s}$, consuming $9.6\text{ kg}$ MMH/MON3 bipropellant at $I_{sp} = 310\text{ s}$).
  - Hohmann transfer coast ($\Delta t = 56.9\text{ min}$) lowering periapsis to $15.00\text{ km}$ at $1,692.7\text{ m/s}$ over the lunar South Pole.
- **Visuals**:
  - 3D Moon sphere with polar craters on limb.
  - Blue orbit ellipse and cyan transfer trajectory.
  - Active exhaust plume during deorbit burn.
  - Sun pointing line (gold ray) and Earth link vector (cyan ray).
  - Mission Control telemetry HUD: Mission Clock, Altitude ($100.0\text{ km} \to 15.0\text{ km}$), Speed ($1,633.9 \to 1,692.7\text{ m/s}$), Propellant ($9.6\text{ kg}$).

---

### Clip 2: 5-Engine Powered Descent with In-Flight Engine-Out Balancing
- **File**: `video_assets/clip2_descent_engine_out.mp4`
- **Context**: Spec §4.2, §7.2, KAN-42
- **Flight Dynamics**:
  - Starts at terminal descent conditions ($2,000\text{ m}$ altitude, $-45\text{ m/s}$ vertical speed, $+10\text{ m/s}$ horizontal offset).
  - 5-engine cluster: $1\text{ centre} + 4\text{ outer}$ canted $5^\circ$ outward ($800\text{ N}$ each, throttle range $0.40 - 1.0$).
  - **In-Flight Failure Injection**: At $t = 20.0\text{ s}$, Outer Engine 1 suffers total failure.
  - **Autonomous Balance Mitigation**: Descent guidance automatically cuts opposite Outer Engine 3 to eliminate overturning moments, throttling remaining 3 engines up to $100\%$ ($2,400\text{ N}$ thrust).
  - Spacecraft nulls horizontal velocity, meets hover gate ($30\text{ m}$), and enters vertical terminal descent at constant $1.0\text{ m/s}$.
  - **Touchdown Performance**:
    - Vertical touchdown speed: $1.003\text{ m/s}$ (Limit: $\le 2.0\text{ m/s}$ — **PASS**)
    - Horizontal touchdown speed: $0.000\text{ m/s}$ (Limit: $\le 0.5\text{ m/s}$ — **PASS**)
    - Spacecraft tilt angle: $0.00^\circ$ (Limit: $\le 12.0^\circ$ — **PASS**)
    - Terrain slope: $0.88^\circ$ (Limit: $\le 12.0^\circ$ — **PASS**)
    - Position accuracy: $0.009\text{ m}$ East, $-0.003\text{ m}$ North ($< 1\text{ cm}$ from target — **PASS**)
- **Visuals**:
  - LOLA crater DEM terrain mesh (`terrain_demo_craters.obj` / `terrain_shackleton.obj`).
  - Original 3D lander body (octagonal MLI bus, 4 shock legs + footpads, 5 nozzles).
  - Engine 1 failure warning banner flashing red.
  - Engine 1 and 3 plumes cut, 3 active engine plumes throttle up.
  - Touchdown dust burst on contact.
  - 5 engine status lamps and real-time telemetry HUD.

---

### Clip 3: Pragyan-Class 25 kg Rover Autonomous Ice Prospecting Traverse
- **File**: `video_assets/clip3_rover_ice_traverse.mp4`
- **Context**: Spec §4.3, §7.3, KAN-45
- **Surface Operations**:
  - Pragyan-class $25.0\text{ kg}$ prospecting rover with 6 rocker-bogie cleated wheels and top $50\text{ W}$ solar panel.
  - Kinematic surface velocity strictly $0.010\text{ m/s}$ ($1.0\text{ cm/s}$); maximum recorded slope $1.62^\circ \le 15.0^\circ$.
  - **Video Playback Speedup**: $60\times$ speedup ($1\text{ s}$ video $= 1.0\text{ min}$ surface operations). Total traverse: $164.5\text{ min}$ ($2.74\text{ h}$) across $98.7\text{ m}$.
  - **Traverse Milestones**:
    1. **Waypoint 1 (Sunlit Science Site)**: Geological rock prospecting ($29.2\text{ m}$ from lander), solar input $50\text{ W}$, battery charges to $120.0\text{ Wh}$ ($100\%$).
    2. **Waypoint 2 (Shadow Cold Trap Ice Target)**: Descends into permanently shadowed region (PSR) where `sun_fraction = 0.0`. Solar input drops to $0\text{ W}$, battery discharges safely to $96.5\text{ Wh}$ ($81.2\%$).
    3. **Waypoint 3 (Return to Lander)**: Climbs out of crater back into grazing sunlight, recharges battery to $114.2\text{ Wh}$ ($95.1\%$), and docks with lander base station at sunset ($< 0.89\text{ m}$ from landing target).
  - **Comms Link**: Direct-to-Lander RF line-of-sight ray checked across terrain topography (green when clear).
- **Visuals**:
  - Low grazing sunset lighting with dramatic long shadows.
  - Deep blue-black permanently shadowed cold trap depression.
  - Lander base station on sunlit rim with high-gain mast.
  - 3D rover model with rotating wheels and top solar panel.
  - Real-time telemetry HUD: Speed ($0.010\text{ m/s}$), Battery SOC ($100\% \to 81\% \to 95\%$), Sun fraction, Link status.

---

### Clip 4: Mission Control Console Operations (Streamlit Port 8502)
- **File**: `video_assets/clip4_mission_control.mp4`
- **Context**: Spec §9.2, KAN-48
- **Console Operations**:
  - **Top Bar**: Live Mission Phase (`POWERED DESCENT` $\to$ `TERMINAL` $\to$ `TOUCHDOWN`), Mission Clock (`MET: T+ 000:00:21.0 s`), and Provenance Badge (`MODELLED · Basilisk`).
  - **Flight Telemetry**: Real-time altitude, vertical/horizontal speed, fuel remaining, total vehicle mass, and total thrust.
  - **5-Engine Propulsion Cluster**:
    - Nominal 5 engines operational at start ($t=0\text{ s}$).
    - At $t=21.0\text{ s}$: Engine 1 fails (illuminates red `FAILED`).
    - Autonomous balance cut of opposite Engine 3 (illuminates amber `OFF (BALANCED)`).
    - Remaining engines (E2, E4, E5) increase throttle to maintain closed-loop descent profile.
  - **Power, Comms & Horizons**: Battery state ($12.0\text{ kWh}$), solar array generation ($850\text{ W}$), Direct-to-Earth link status (`DTE LINK: ACTIVE`), and Navigator-matched countdowns (`sunset: 8 d 20 h`, `Earthrise: 11 d 11 h`).
  - **Rover Mini-Panel**: Pragyan 3 surface coordinates, distance to lander base station ($38.4\text{ m}$), drive speed ($0.01\text{ m/s}$), and local slope angle ($4.2^\circ \le 15.0^\circ$).
  - **Autonomous Decision Log**: Monospaced console displaying onboard G&C decisions without commentary text.

---

## 3. Disclosures & Honesty Checklist

- [x] **Provenance**: Every clip clearly displays `MODELLED · Basilisk / LOLA DEM`.
- [x] **Vertical Exaggeration**: Clip 2 and Clip 3 explicitly display `vertical exaggeration ×1.5`. Clip 1 displays `vertical exaggeration ×1.0` (unexaggerated orbit).
- [x] **Playback Speedup**: Clip 3 explicitly displays `PLAYBACK SPEEDUP: 60x (Physical Rover Speed: 0.01 m/s)`. Rover speed is strictly physical $1\text{ cm/s}$.
- [x] **Original Design**: Strictly original geometric CAD designs (octagonal bus, 4 landing legs, 5 nozzles; 6-wheel rover chassis). Strictly **no** branded or copyrighted spacecraft models used.
- [x] **Physical Simplifications**: Ideal attitude torque (not RCS thrusters); point-mass 2-body Moon for orbit propagation; simplified thermal radiation model.
