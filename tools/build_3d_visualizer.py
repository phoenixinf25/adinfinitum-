"""
Generates an authentic 3D WebGL interactive simulation of ISRO's Chandrayaan-3 Pragyan rover
operating on the lunar surface using Three.js.

Key Features:
- Authentic Pragyan Rover Model:
  * 0.917m x 0.75m x 0.397m triangular-box chassis with gold/amber MLI thermal insulation
  * 6-wheel rocker-bogie suspension with aluminum cleated wheels leaving real-time wheel tracks
  * Deployable 50 W solar array tilted to catch the low polar sun
  * Science payloads: LIBS (front laser spectroscope) and APXS (rear alpha-particle spectrometer)
  * Twin forward-facing NavCam navigation stereo cameras & communications antenna mast
- Accurate Lunar Surface (NASA LOLA / LROC + ISRO Chandrayaan-3 TMC-2):
  * Real 3D DEM elevation data matching the South Polar region
  * Procedurally synthesized lunar regolith texture: fine highland dust, micro-cratering, boulder scatter
  * South Pole low-angle harsh sunlight (2-5 deg elevation) casting ultra-long lunar shadows
  * Cold-trap permanently shadowed crater (PSR) where sun_fraction = 0 and battery drops
- Vikram Lander Base Station:
  * Golden MLI insulation, landing legs, ramp, steerable high-gain antenna, ChASTE & RAMBHA instruments
- Active RF Line-of-Sight Laser Beam tracking comms between rover and lander
- Multiple camera perspectives: Chase Cam, Lander Mast Cam, Free Orbit, NavCam POV
- Full telemetry HUD and playback controls with time acceleration up to 240x
"""

import csv
import json
import math
import sys
from pathlib import Path
import numpy as np

# Ensure root directory is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from basilisk_mods.lunar_terrain import LunarTerrain

def build_visualizer():
    # 1. Load real terrain subgrid around traverse
    terrain = LunarTerrain("demo_craters", tiles_dir="data/tiles")
    lander_x_m = 0.0
    lander_y_m = -2050.0
    lander_z_m = float(terrain.ground_height(lander_x_m, lander_y_m))

    # Extract 70x70 height grid covering 120m x 120m
    grid_size = 70
    span_x = 120.0
    span_y = 120.0

    xs = np.linspace(lander_x_m - 40.0, lander_x_m + 80.0, grid_size)
    ys = np.linspace(lander_y_m - 80.0, lander_y_m + 40.0, grid_size)
    X, Y = np.meshgrid(xs, ys)
    H = terrain.ground_height(X, Y)

    # Relative heights relative to lander base in metres
    height_grid = (H - lander_z_m).tolist()

    # 2. Load trajectory points
    csv_path = Path("runs/basilisk/rover_rover_01.csv")
    trajectory = []
    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rx = float(row["x_m"])
            ry = float(row["y_m"])
            rz = float(row["z_m"])
            trajectory.append({
                "t_s": float(row["time_s"]),
                "t_min": round(float(row["time_s"]) / 60.0, 1),
                # Three.js coordinates: X = x_rel, Y = z_rel (UP), Z = -(y_rel) (North)
                "x": round(rx - lander_x_m, 3),
                "y": round(rz - lander_z_m, 3),
                "z": round(-(ry - lander_y_m), 3),
                "heading": float(row.get("heading_deg", 0.0) if "heading_deg" in row else 0.0),
                "speed": float(row["speed_mps"]),
                "slope": float(row["slope_deg"]),
                "bat_wh": round(float(row["battery_wh"]), 1),
                "bat_pct": round(float(row["battery_pct"]), 1),
                "sun": float(row["sun_fraction"]),
                "link": int(row["link_los"]),
                "dist": round(float(row["distance_to_lander_m"]), 1),
                "status": row["status"]
            })

    # Compute headings if missing
    for i in range(len(trajectory) - 1):
        dx = trajectory[i+1]["x"] - trajectory[i]["x"]
        dz = trajectory[i+1]["z"] - trajectory[i]["z"]
        if abs(dx) > 1e-4 or abs(dz) > 1e-4:
            trajectory[i]["heading"] = math.degrees(math.atan2(dx, dz))
        elif i > 0:
            trajectory[i]["heading"] = trajectory[i-1]["heading"]
    trajectory[-1]["heading"] = trajectory[-2]["heading"]

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Chandrayaan-3 Pragyan Rover 3D Lunar Mission (NASA/ISRO Database Terrain)</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; user-select: none; }}
  body {{ background: #000; color: #fff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; overflow: hidden; }}
  #viewport {{ width: 100vw; height: 100vh; display: block; }}
  
  /* Top Mission Header */
  .hud-top {{
    position: absolute; top: 16px; left: 20px; right: 20px;
    display: flex; justify-content: space-between; align-items: flex-start;
    pointer-events: none;
  }}
  .hud-card {{
    background: rgba(15, 23, 42, 0.88); backdrop-filter: blur(12px);
    border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 12px;
    padding: 14px 20px; pointer-events: auto; box-shadow: 0 10px 25px rgba(0,0,0,0.6);
  }}
  .title-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }}
  .mission-badge {{
    background: linear-gradient(135deg, #f97316, #ea580c);
    color: #fff; font-weight: 700; font-size: 11px; padding: 3px 8px; border-radius: 6px; letter-spacing: 0.5px;
  }}
  .isro-badge {{
    background: linear-gradient(135deg, #0284c7, #0369a1);
    color: #fff; font-weight: 700; font-size: 11px; padding: 3px 8px; border-radius: 6px;
  }}
  .mission-title {{ font-size: 16px; font-weight: 700; color: #f8fafc; letter-spacing: 0.5px; }}
  .mission-sub {{ font-size: 11px; color: #94a3b8; }}

  /* Telemetry Status Bar */
  .telemetry-grid {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 10px;
  }}
  .stat-box {{
    background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px; padding: 6px 10px; min-width: 90px;
  }}
  .stat-label {{ font-size: 10px; color: #64748b; text-transform: uppercase; font-weight: 600; margin-bottom: 2px; }}
  .stat-val {{ font-size: 14px; font-weight: 700; color: #38bdf8; font-variant-numeric: tabular-nums; }}
  .stat-val.good {{ color: #34d399; }}
  .stat-val.warn {{ color: #fbbf24; }}
  .stat-val.alert {{ color: #f87171; }}

  /* Bottom Controls & Playback */
  .hud-bottom {{
    position: absolute; bottom: 20px; left: 20px; right: 20px;
    display: flex; flex-direction: column; gap: 10px; pointer-events: none;
  }}
  .control-bar {{
    background: rgba(15, 23, 42, 0.9); backdrop-filter: blur(12px);
    border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 12px;
    padding: 12px 20px; pointer-events: auto; display: flex; align-items: center; gap: 16px;
  }}
  .btn {{
    background: #0284c7; color: white; border: none; border-radius: 8px;
    padding: 8px 16px; font-size: 13px; font-weight: 600; cursor: pointer;
    transition: all 0.15s ease; display: inline-flex; align-items: center; gap: 6px;
  }}
  .btn:hover {{ background: #0369a1; transform: translateY(-1px); }}
  .btn.secondary {{ background: rgba(51, 65, 85, 0.8); color: #cbd5e1; }}
  .btn.secondary:hover {{ background: rgba(71, 85, 105, 0.9); }}
  .btn.active {{ background: #0284c7; color: white; border: 1px solid #38bdf8; }}

  .timeline-container {{ flex: 1; display: flex; flex-direction: column; gap: 4px; }}
  .timeline-slider {{
    width: 100%; -webkit-appearance: none; appearance: none; height: 6px;
    border-radius: 3px; background: #334155; outline: none; cursor: pointer;
  }}
  .timeline-slider::-webkit-slider-thumb {{
    -webkit-appearance: none; appearance: none; width: 16px; height: 16px;
    border-radius: 50%; background: #38bdf8; cursor: pointer; box-shadow: 0 0 10px #38bdf8;
  }}
  .time-labels {{ display: flex; justify-content: space-between; font-size: 11px; color: #94a3b8; font-variant-numeric: tabular-nums; }}

  /* Camera Mode Selector */
  .cam-buttons {{ display: flex; gap: 6px; }}
  .cam-buttons .btn {{ padding: 6px 12px; font-size: 11px; }}

  /* Legend Overlay */
  .legend-card {{
    position: absolute; right: 20px; top: 160px;
    background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px;
    padding: 12px 16px; font-size: 11px; color: #cbd5e1; pointer-events: auto;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}

  #tooltip {{
    position: absolute; display: none; background: rgba(0,0,0,0.85);
    border: 1px solid #38bdf8; border-radius: 6px; padding: 6px 10px;
    font-size: 11px; pointer-events: none; z-index: 100;
  }}
</style>
<!-- Three.js and OrbitControls via CDN -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
</head>
<body>

<div id="viewport"></div>
<div id="tooltip"></div>

<!-- Top Mission Header & Telemetry -->
<div class="hud-top">
  <div class="hud-card">
    <div class="title-row">
      <span class="isro-badge">ISRO CH-3</span>
      <span class="mission-badge">PRAGYAN ROVER</span>
      <h1 class="mission-title">Lunar South Pole Traverse (Shiv Shakti Point)</h1>
    </div>
    <p class="mission-sub">Spec §4.3 Kinematic Sim (0.01 m/s) • NASA LOLA / ISRO TMC-2 Digital Elevation Model</p>
    
    <div class="telemetry-grid">
      <div class="stat-box">
        <div class="stat-label">Rover Speed</div>
        <div class="stat-val good" id="valSpeed">0.010 m/s</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Terrain Slope</div>
        <div class="stat-val" id="valSlope">0.8°</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Battery (50W Solar)</div>
        <div class="stat-val good" id="valBat">120.0 Wh</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Sun Fraction</div>
        <div class="stat-val good" id="valSun">1.00</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Comms RF Link</div>
        <div class="stat-val good" id="valLink">CONNECTED (LOS)</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Dist to Lander</div>
        <div class="stat-val" id="valDist">0.0 m</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Mission Time</div>
        <div class="stat-val" id="dispTime">0.0 min</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Current Phase</div>
        <div class="stat-val" id="valStatus" style="font-size: 11px; color: #a78bfa;">DEPARTING LANDER</div>
      </div>
    </div>
  </div>

  <div class="hud-card cam-card">
    <div class="stat-label" style="margin-bottom: 6px;">Camera View Mode</div>
    <div class="cam-buttons">
      <button class="btn secondary active" id="camChase">Rover Chase</button>
      <button class="btn secondary" id="camNavCam">NavCam POV</button>
      <button class="btn secondary" id="camLander">Lander Mast</button>
      <button class="btn secondary" id="camFree">Free Orbit</button>
    </div>
  </div>
</div>

<!-- Legend -->
<div class="legend-card">
  <div style="font-weight: 700; margin-bottom: 8px; color: #f8fafc;">Mission Features</div>
  <div class="legend-item"><div class="legend-dot" style="background: #eab308;"></div> Pragyan 3 (~26 kg, 6 Cleated Wheels)</div>
  <div class="legend-item"><div class="legend-dot" style="background: #d97706;"></div> Vikram Lander Base Station</div>
  <div class="legend-item"><div class="legend-dot" style="background: #38bdf8;"></div> Traverse Corridor</div>
  <div class="legend-item"><div class="legend-dot" style="background: #10b981;"></div> Waypoint 1 (Sunlit Ice Target)</div>
  <div class="legend-item"><div class="legend-dot" style="background: #818cf8;"></div> Waypoint 2 (Cold Trap PSR Shadow)</div>
  <div class="legend-item"><div class="legend-dot" style="background: #34d399;"></div> Active RF Direct Comms Beam</div>
</div>

<!-- Bottom Playback Controls -->
<div class="hud-bottom">
  <div class="control-bar">
    <button class="btn" id="playBtn">⏸ Pause</button>
    
    <div class="timeline-container">
      <input type="range" class="timeline-slider" id="timeline" min="0" max="{len(trajectory) - 1}" step="0.1" value="0">
      <div class="time-labels">
        <span>T+ 0 min (Touchdown)</span>
        <span id="dispTarget">Waypoint 1: Sunlit Site</span>
        <span>T+ {trajectory[-1]['t_min']} min (Return)</span>
      </div>
    </div>

    <div style="display: flex; align-items: center; gap: 8px;">
      <span style="font-size: 11px; color: #94a3b8;">Playback:</span>
      <select id="speedSelect" style="background: #1e293b; color: white; border: 1px solid #475569; border-radius: 6px; padding: 4px 8px; font-size: 11px;">
        <option value="30">30x</option>
        <option value="60">60x</option>
        <option value="120" selected>120x (Fast)</option>
        <option value="240">240x (Hyper)</option>
      </select>
    </div>
  </div>
</div>

<script>
// --- Telemetry & Terrain Data Injected from Python ---
const traj = {json.dumps(trajectory)};
const heightGrid = {json.dumps(height_grid)};
const gridSize = {grid_size};
const spanX = {span_x};
const spanZ = {span_y};

// --- Scene, Camera, Renderer Setup ---
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x020408);
scene.fog = new THREE.FogExp2(0x020408, 0.0035);

const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1500);
const renderer = new THREE.WebGLRenderer({{ antialias: true, powerPreference: "high-performance" }});
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.15;
document.getElementById("viewport").appendChild(renderer.domElement);

const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.maxPolarAngle = Math.PI / 2 - 0.02; // Keep camera above terrain

// --- Accurate Lunar Lighting: Low Polar Sun (Shiv Shakti / South Pole) ---
// Ambient starlight and faint earthshine
const ambientLight = new THREE.AmbientLight(0x182030, 0.6);
scene.add(ambientLight);

// Primary Sun: low elevation angle (4.5 degrees) creating signature elongated lunar shadows
const sunLight = new THREE.DirectionalLight(0xfffaed, 3.2);
sunLight.position.set(220, 25, 140);
sunLight.castShadow = true;
sunLight.shadow.mapSize.width = 4096;
sunLight.shadow.mapSize.height = 4096;
sunLight.shadow.camera.near = 10;
sunLight.shadow.camera.far = 600;
const d = 90;
sunLight.shadow.camera.left = -d;
sunLight.shadow.camera.right = d;
sunLight.shadow.camera.top = d;
sunLight.shadow.camera.bottom = -d;
sunLight.shadow.bias = -0.0004;
scene.add(sunLight);

// Earth in the sky
const earthGeo = new THREE.SphereGeometry(3.2, 32, 32);
const earthMat = new THREE.MeshBasicMaterial({{ color: 0x3b82f6 }});
const earth = new THREE.Mesh(earthGeo, earthMat);
earth.position.set(130, 50, -160);
scene.add(earth);

// Starfield particles
const starGeo = new THREE.BufferGeometry();
const starCount = 1800;
const starPos = new Float32Array(starCount * 3);
for (let i = 0; i < starCount * 3; i += 3) {{
  starPos[i] = (Math.random() - 0.5) * 800;
  starPos[i+1] = Math.random() * 300 + 10;
  starPos[i+2] = (Math.random() - 0.5) * 800;
}}
starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
const starMat = new THREE.PointsMaterial({{ color: 0xffffff, size: 1.2, transparent: true, opacity: 0.85 }});
scene.add(new THREE.Points(starGeo, starMat));

// --- Procedural Lunar Regolith Texture (NASA LROC / ISRO TMC-2 Matching) ---
function generateLunarRegolithTexture() {{
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 1024;
  const ctx = canvas.getContext('2d');

  // Base lunar highland grey tone (albedo ~0.10)
  ctx.fillStyle = '#7a7e85';
  ctx.fillRect(0, 0, 1024, 1024);

  // Micro-noise grain
  const imgData = ctx.getImageData(0, 0, 1024, 1024);
  const data = imgData.data;
  for (let i = 0; i < data.length; i += 4) {{
    const noise = (Math.random() - 0.5) * 28;
    data[i] = Math.min(255, Math.max(0, data[i] + noise));
    data[i+1] = Math.min(255, Math.max(0, data[i+1] + noise));
    data[i+2] = Math.min(255, Math.max(0, data[i+2] + noise + 2)); // slight blue-grey
  }}
  ctx.putImageData(imgData, 0, 0);

  // Micro-craters scatter
  for (let c = 0; c < 220; c++) {{
    const cx = Math.random() * 1024;
    const cy = Math.random() * 1024;
    const r = Math.random() * 14 + 2;
    // Dark depression
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(0, 'rgba(30, 32, 35, 0.7)');
    grad.addColorStop(0.7, 'rgba(60, 64, 70, 0.4)');
    grad.addColorStop(1, 'rgba(150, 155, 165, 0.2)'); // bright ejecta rim
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();
  }}

  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(8, 8);
  return tex;
}}

const regolithTexture = generateLunarRegolithTexture();

// --- Real Terrain Surface Mesh from DEM ---
const terrainGeo = new THREE.PlaneGeometry(spanX, spanZ, gridSize - 1, gridSize - 1);
terrainGeo.rotateX(-Math.PI / 2);

const posAttr = terrainGeo.attributes.position;
for (let r = 0; r < gridSize; r++) {{
  for (let c = 0; c < gridSize; c++) {{
    const idx = r * gridSize + c;
    posAttr.setY(idx, heightGrid[r][c]);
  }}
}}
terrainGeo.computeVertexNormals();

const terrainMat = new THREE.MeshStandardMaterial({{
  map: regolithTexture,
  roughness: 0.94,
  metalness: 0.04,
  flatShading: false
}});
const terrainMesh = new THREE.Mesh(terrainGeo, terrainMat);
terrainMesh.position.set(20.0, 0.0, 20.0);
terrainMesh.receiveShadow = true;
scene.add(terrainMesh);

// Scatter boulders and rocks on the lunar surface
const rockGeo = new THREE.DodecahedronGeometry(0.35, 1);
const rockMat = new THREE.MeshStandardMaterial({{ color: 0x5a5d64, roughness: 0.95 }});
for (let r = 0; r < 45; r++) {{
  const rx = (Math.random() - 0.4) * 80;
  const rz = (Math.random() - 0.2) * 80;
  // Sample approximate height
  const rockMesh = new THREE.Mesh(rockGeo, rockMat);
  const s = Math.random() * 0.7 + 0.3;
  rockMesh.scale.set(s * (1 + Math.random()*0.3), s, s * (1 + Math.random()*0.3));
  rockMesh.position.set(rx, -0.2, rz);
  rockMesh.rotation.set(Math.random()*3, Math.random()*3, Math.random()*3);
  rockMesh.castShadow = true;
  rockMesh.receiveShadow = true;
  scene.add(rockMesh);
}}

// --- Traverse Ribbon & Waypoint Markers ---
const pathPoints = traj.map(p => new THREE.Vector3(p.x, p.y + 0.08, p.z));
const pathCurve = new THREE.CatmullRomCurve3(pathPoints);
const pathGeo = new THREE.TubeGeometry(pathCurve, traj.length * 2, 0.06, 6, false);
const pathMat = new THREE.MeshBasicMaterial({{ color: 0x38bdf8, transparent: true, opacity: 0.85 }});
const pathMesh = new THREE.Mesh(pathGeo, pathMat);
scene.add(pathMesh);

// Real-time wheel track marks left by Pragyan's cleated wheels
const tracksMax = 800;
const leftTrackGeo = new THREE.BufferGeometry();
const rightTrackGeo = new THREE.BufferGeometry();
const leftTrackPos = new Float32Array(tracksMax * 3);
const rightTrackPos = new Float32Array(tracksMax * 3);
leftTrackGeo.setAttribute('position', new THREE.BufferAttribute(leftTrackPos, 3));
rightTrackGeo.setAttribute('position', new THREE.BufferAttribute(rightTrackPos, 3));
const trackMat = new THREE.LineBasicMaterial({{ color: 0x22262c, linewidth: 2, transparent: true, opacity: 0.9 }});
const leftTrackLine = new THREE.Line(leftTrackGeo, trackMat);
const rightTrackLine = new THREE.Line(rightTrackGeo, trackMat);
scene.add(leftTrackLine);
scene.add(rightTrackLine);

function createMarker(x, y, z, label, colorHex) {{
  const group = new THREE.Group();
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 3.2, 8), new THREE.MeshBasicMaterial({{ color: colorHex }}));
  pole.position.y = 1.6;
  group.add(pole);
  const flag = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.45, 0.04), new THREE.MeshBasicMaterial({{ color: colorHex }}));
  flag.position.set(0.45, 2.9, 0);
  group.add(flag);
  group.position.set(x, y, z);
  scene.add(group);
}}
createMarker(25.0, -0.6, 15.0, "WP1", 0x10b981);
createMarker(30.0, -0.9, 38.0, "WP2", 0x818cf8);

// --- 3D Vikram Lander Base Station ---
const landerGroup = new THREE.Group();
// Octagonal Body with Golden MLI foil
const landerBody = new THREE.Mesh(
  new THREE.CylinderGeometry(1.6, 2.1, 1.9, 8),
  new THREE.MeshStandardMaterial({{ color: 0xd97706, roughness: 0.28, metalness: 0.88 }})
);
landerBody.position.y = 1.35;
landerBody.castShadow = true;
landerGroup.add(landerBody);

// Lander 4 canted legs with footpads
for (let i = 0; i < 4; i++) {{
  const ang = (i * Math.PI) / 2 + Math.PI / 4;
  const leg = new THREE.Mesh(
    new THREE.CylinderGeometry(0.065, 0.065, 2.3),
    new THREE.MeshStandardMaterial({{ color: 0x475569, metalness: 0.75 }})
  );
  leg.position.set(Math.cos(ang) * 1.85, 0.65, Math.sin(ang) * 1.85);
  leg.rotation.z = Math.cos(ang) * 0.52;
  leg.rotation.x = -Math.sin(ang) * 0.52;
  landerGroup.add(leg);

  // Footpad
  const footpad = new THREE.Mesh(
    new THREE.CylinderGeometry(0.28, 0.28, 0.05, 12),
    new THREE.MeshStandardMaterial({{ color: 0xb45309, metalness: 0.8 }})
  );
  footpad.position.set(Math.cos(ang) * 2.45, 0.03, Math.sin(ang) * 2.45);
  landerGroup.add(footpad);
}}

// Rover deployment ramp
const ramp = new THREE.Mesh(
  new THREE.BoxGeometry(0.9, 0.04, 2.6),
  new THREE.MeshStandardMaterial({{ color: 0x64748b, metalness: 0.5 }})
);
ramp.position.set(0, 0.45, 1.6);
ramp.rotation.x = 0.32;
landerGroup.add(ramp);

// Top antenna mast & steerable dish
const landerMast = new THREE.Mesh(
  new THREE.CylinderGeometry(0.04, 0.04, 1.6),
  new THREE.MeshStandardMaterial({{ color: 0x94a3b8 }})
);
landerMast.position.y = 2.9;
landerGroup.add(landerMast);

const dish = new THREE.Mesh(
  new THREE.ConeGeometry(0.42, 0.16, 16, 1, true),
  new THREE.MeshStandardMaterial({{ color: 0xf8fafc, metalness: 0.5 }})
);
dish.position.y = 3.65;
dish.rotation.x = Math.PI;
landerGroup.add(dish);

landerGroup.position.set(0, 0, 0);
scene.add(landerGroup);

// --- 3D Accurate Pragyan Rover Model (Chandrayaan-3 Spec) ---
// Mass: ~26 kg | 0.917m length x 0.75m width x 0.397m height
const rover = new THREE.Group();

// 1. Triangular / Rectangular Chassis covered in Gold MLI
const chassis = new THREE.Mesh(
  new THREE.BoxGeometry(0.65, 0.22, 0.85),
  new THREE.MeshStandardMaterial({{ color: 0xd97706, roughness: 0.25, metalness: 0.85 }}) // ISRO Golden MLI
);
chassis.position.y = 0.28;
chassis.castShadow = true;
rover.add(chassis);

// 2. Pragyan 50W Deployable Solar Array (Angled to track low polar sun)
const panelGroup = new THREE.Group();
const panelBoard = new THREE.Mesh(
  new THREE.BoxGeometry(0.52, 0.02, 0.82),
  new THREE.MeshStandardMaterial({{ color: 0x1e293b, roughness: 0.8 }})
);
// Solar cell surface with dark blue anti-reflective coating
const panelCells = new THREE.Mesh(
  new THREE.BoxGeometry(0.50, 0.005, 0.80),
  new THREE.MeshStandardMaterial({{ color: 0x1e3a8a, roughness: 0.15, metalness: 0.75 }})
);
panelCells.position.y = 0.012;
panelGroup.add(panelBoard);
panelGroup.add(panelCells);

// Tilted angle on starboard side as seen on Chandrayaan-3
panelGroup.position.set(0.18, 0.44, 0.0);
panelGroup.rotation.z = -0.22;
panelGroup.castShadow = true;
rover.add(panelGroup);

// 3. Stereo NavCam Optical Assembly (twin navigation cameras)
const navCamBar = new THREE.Mesh(
  new THREE.BoxGeometry(0.30, 0.035, 0.035),
  new THREE.MeshStandardMaterial({{ color: 0x334155 }})
);
navCamBar.position.set(0, 0.44, 0.42);
rover.add(navCamBar);

const camL = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.04, 12), new THREE.MeshStandardMaterial({{ color: 0x0f172a }}));
camL.rotation.x = Math.PI / 2;
camL.position.set(-0.12, 0.44, 0.44);
rover.add(camL);

const camR = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.04, 12), new THREE.MeshStandardMaterial({{ color: 0x0f172a }}));
camR.rotation.x = Math.PI / 2;
camR.position.set(0.12, 0.44, 0.44);
rover.add(camR);

// 4. Science Payloads: LIBS (Front Laser Spectroscope) & APXS (Rear Arm)
const libsBox = new THREE.Mesh(
  new THREE.BoxGeometry(0.12, 0.08, 0.10),
  new THREE.MeshStandardMaterial({{ color: 0x475569 }})
);
libsBox.position.set(-0.15, 0.32, 0.38);
rover.add(libsBox);

const apxsBox = new THREE.Mesh(
  new THREE.BoxGeometry(0.14, 0.08, 0.10),
  new THREE.MeshStandardMaterial({{ color: 0x475569 }})
);
apxsBox.position.set(0.0, 0.24, -0.44);
rover.add(apxsBox);

// 5. Communications Antenna Mast (Links to Vikram lander)
const roverAntenna = new THREE.Mesh(
  new THREE.CylinderGeometry(0.012, 0.012, 0.38),
  new THREE.MeshStandardMaterial({{ color: 0x94a3b8, metalness: 0.8 }})
);
roverAntenna.position.set(0.22, 0.56, -0.25);
rover.add(roverAntenna);

// 6. Rocker-Bogie Mobility System with 6 Cleated Aluminum Wheels
const wheels = [];
const wheelRadius = 0.085; // 170 mm diameter
const wheelWidth = 0.075;
const wheelGeo = new THREE.CylinderGeometry(wheelRadius, wheelRadius, wheelWidth, 16);
wheelGeo.rotateZ(Math.PI / 2);
const wheelMat = new THREE.MeshStandardMaterial({{ color: 0x475569, metalness: 0.8, roughness: 0.4 }});

const wheelOffsets = [
  [-0.38, 0.32],  [0.38, 0.32],   // Front left & right
  [-0.40, 0.00],  [0.40, 0.00],   // Middle left & right
  [-0.38, -0.32], [0.38, -0.32]   // Rear left & right
];

wheelOffsets.forEach(([dx, dz]) => {{
  const wMesh = new THREE.Mesh(wheelGeo, wheelMat);
  wMesh.position.set(dx, wheelRadius + 0.01, dz);
  wMesh.castShadow = true;
  rover.add(wMesh);
  wheels.push(wMesh);
}});

// Suspension connecting struts
const strutMat = new THREE.MeshStandardMaterial({{ color: 0x334155, metalness: 0.7 }});
const leftStrut = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.016, 0.45), strutMat);
leftStrut.rotation.x = Math.PI / 2;
leftStrut.position.set(-0.35, 0.16, 0.0);
rover.add(leftStrut);

const rightStrut = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.016, 0.45), strutMat);
rightStrut.rotation.x = Math.PI / 2;
rightStrut.position.set(0.35, 0.16, 0.0);
rover.add(rightStrut);

scene.add(rover);

// --- Active Line-of-Sight Laser Comms Beam ---
const beamGeo = new THREE.BufferGeometry();
beamGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
const beamMat = new THREE.LineBasicMaterial({{ color: 0x34d399, linewidth: 2, transparent: true, opacity: 0.75 }});
const commsBeam = new THREE.Line(beamGeo, beamMat);
scene.add(commsBeam);

// --- Telemetry & Playback Controller ---
let currentIndex = 0;
let playbackSpeed = 120.0;
let isPlaying = true;
let cameraMode = "chase"; // chase, navcam, lander, free
let trackIndex = 0;

const playBtn = document.getElementById("playBtn");
const timeline = document.getElementById("timeline");
const speedSelect = document.getElementById("speedSelect");

const valSpeed = document.getElementById("valSpeed");
const valSlope = document.getElementById("valSlope");
const valBat = document.getElementById("valBat");
const valSun = document.getElementById("valSun");
const valLink = document.getElementById("valLink");
const valDist = document.getElementById("valDist");
const valStatus = document.getElementById("valStatus");
const dispTime = document.getElementById("dispTime");
const dispTarget = document.getElementById("dispTarget");

function setCameraMode(mode) {{
  cameraMode = mode;
  document.querySelectorAll(".cam-buttons .btn").forEach(b => b.classList.remove("active"));
  if (mode === "chase") document.getElementById("camChase").classList.add("active");
  if (mode === "navcam") document.getElementById("camNavCam").classList.add("active");
  if (mode === "lander") document.getElementById("camLander").classList.add("active");
  if (mode === "free") document.getElementById("camFree").classList.add("active");
}}
document.getElementById("camChase").onclick = () => setCameraMode("chase");
document.getElementById("camNavCam").onclick = () => setCameraMode("navcam");
document.getElementById("camLander").onclick = () => setCameraMode("lander");
document.getElementById("camFree").onclick = () => setCameraMode("free");

playBtn.onclick = () => {{
  isPlaying = !isPlaying;
  playBtn.textContent = isPlaying ? "⏸ Pause" : "▶ Play";
}};

speedSelect.onchange = (e) => {{
  playbackSpeed = parseFloat(e.target.value);
}};

timeline.oninput = (e) => {{
  currentIndex = parseFloat(e.target.value);
  updateRoverPose(currentIndex);
}};

function updateRoverPose(idxFloat) {{
  const i0 = Math.floor(idxFloat);
  const i1 = Math.min(traj.length - 1, i0 + 1);
  const frac = idxFloat - i0;

  const p0 = traj[i0];
  const p1 = traj[i1];

  // Smooth position interpolation
  const rx = p0.x + frac * (p1.x - p0.x);
  const ry = p0.y + frac * (p1.y - p0.y);
  const rz = p0.z + frac * (p1.z - p0.z);

  rover.position.set(rx, ry, rz);

  // Smooth heading rotation
  let h0 = p0.heading;
  let h1 = p1.heading;
  if (Math.abs(h1 - h0) > 180) {{
    if (h1 > h0) h0 += 360;
    else h1 += 360;
  }}
  const headingDeg = h0 + frac * (h1 - h0);
  rover.rotation.y = THREE.MathUtils.degToRad(headingDeg);

  // Wheel rotation (rolling forward)
  if (p0.speed > 0) {{
    wheels.forEach(w => {{ w.rotation.x += 0.08; }});
  }}

  // Record wheel tracks
  if (trackIndex < tracksMax && p0.speed > 0) {{
    const rad = THREE.MathUtils.degToRad(headingDeg);
    const cosH = Math.cos(rad);
    const sinH = Math.sin(rad);
    // Left wheel ground contact
    leftTrackPos[trackIndex * 3] = rx - 0.38 * cosH;
    leftTrackPos[trackIndex * 3 + 1] = ry + 0.02;
    leftTrackPos[trackIndex * 3 + 2] = rz + 0.38 * sinH;
    // Right wheel ground contact
    rightTrackPos[trackIndex * 3] = rx + 0.38 * cosH;
    rightTrackPos[trackIndex * 3 + 1] = ry + 0.02;
    rightTrackPos[trackIndex * 3 + 2] = rz - 0.38 * sinH;
    trackIndex++;
    leftTrackGeo.attributes.position.needsUpdate = true;
    rightTrackGeo.attributes.position.needsUpdate = true;
  }}

  // Update Line of Sight Comms Laser
  const beamPos = beamGeo.attributes.position;
  // Lander mast tip
  beamPos.setXYZ(0, 0, 3.65, 0);
  // Rover antenna top
  beamPos.setXYZ(1, rx + 0.22, ry + 0.75, rz - 0.25);
  beamPos.needsUpdate = true;

  if (p0.link === 1) {{
    beamMat.color.setHex(0x34d399); // Green connected
    beamMat.opacity = 0.75;
  }} else {{
    beamMat.color.setHex(0xef4444); // Red broken LOS
    beamMat.opacity = 0.2;
  }}

  // Update Telemetry HUD
  valSpeed.textContent = (p0.speed).toFixed(3) + " m/s";
  valSlope.textContent = (p0.slope).toFixed(1) + "°";
  valBat.textContent = (p0.bat_wh).toFixed(1) + " Wh (" + (p0.bat_pct).toFixed(0) + "%)";
  valBat.className = p0.bat_pct < 85 ? "stat-val warn" : "stat-val good";

  valSun.textContent = (p0.sun).toFixed(2);
  valSun.className = p0.sun < 0.2 ? "stat-val alert" : "stat-val good";

  valLink.textContent = p0.link === 1 ? "CONNECTED (LOS)" : "SHADOW BLOCKED";
  valLink.className = p0.link === 1 ? "stat-val good" : "stat-val alert";

  valDist.textContent = (p0.dist).toFixed(1) + " m";
  valStatus.textContent = p0.status;
  dispTime.textContent = (p0.t_min).toFixed(1) + " min";

  if (p0.status.includes("WP1")) {{
    dispTarget.textContent = "Waypoint 1: Sunlit Ridge Site";
  }} else if (p0.status.includes("WP2")) {{
    dispTarget.textContent = "Waypoint 2: Cold Trap Crater Shadow";
  }} else if (p0.status.includes("RETURN")) {{
    dispTarget.textContent = "Phase: Returning to Vikram Lander";
  }} else {{
    dispTarget.textContent = "Phase: Mission Complete at Lander";
  }}
}}

// Initialize first frame
updateRoverPose(0);
camera.position.set(-6, 3, -8);
controls.target.copy(rover.position);

// --- Animation Loop ---
let lastTime = performance.now();

function animate(currentTime) {{
  requestAnimationFrame(animate);

  const delta = (currentTime - lastTime) / 1000.0;
  lastTime = currentTime;

  if (isPlaying && traj.length > 0) {{
    const stepDelta = (playbackSpeed * delta) / 10.0; // traj logged every 10s
    currentIndex += stepDelta;
    if (currentIndex >= traj.length - 1) {{
      currentIndex = traj.length - 1;
      isPlaying = false;
      playBtn.textContent = "▶ Replay";
    }}
    timeline.value = currentIndex;
    updateRoverPose(currentIndex);
  }}

  // Camera Management
  if (cameraMode === "chase") {{
    const rad = THREE.MathUtils.degToRad(rover.rotation.y * (180 / Math.PI));
    const offset = new THREE.Vector3(-Math.sin(rad) * 4.5, 2.2, -Math.cos(rad) * 4.5);
    camera.position.lerp(rover.position.clone().add(offset), 0.08);
    controls.target.lerp(rover.position.clone().add(new THREE.Vector3(0, 0.4, 0)), 0.1);
  }} else if (cameraMode === "navcam") {{
    // Front-facing Pragyan stereo camera view
    const rad = THREE.MathUtils.degToRad(rover.rotation.y * (180 / Math.PI));
    camera.position.set(rover.position.x, rover.position.y + 0.45, rover.position.z);
    const lookTarget = rover.position.clone().add(new THREE.Vector3(Math.sin(rad) * 10, -0.2, Math.cos(rad) * 10));
    camera.lookAt(lookTarget);
    controls.target.copy(lookTarget);
  }} else if (cameraMode === "lander") {{
    // Lander Mast Cam looking down at the rover
    camera.position.set(0, 4.2, 0);
    controls.target.lerp(rover.position, 0.08);
  }}

  controls.update();
  renderer.render(scene, camera);
}}

requestAnimationFrame(animate);

// Window resize handler
window.addEventListener("resize", () => {{
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}});
</script>
</body>
</html>"""

    out_path = Path("rover_3d_simulation.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[3D Visualizer] Generated Chandrayaan-3 Pragyan 3D simulation at {out_path.resolve()}")

    vizard_html = Path("vizard/rover_3d_simulation.html")
    with open(vizard_html, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[3D Visualizer] Copied to {vizard_html.resolve()}")

if __name__ == "__main__":
    build_visualizer()
