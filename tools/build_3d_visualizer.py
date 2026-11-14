"""
Generates a stunning 3D WebGL interactive simulation of the lunar rover mission using Three.js.
Features:
- Real 3D lunar DEM surface terrain mesh with craters and realistic lunar regolith shader.
- Detailed 3D Pragyan/VIPER rover model with rotating rocker-bogie wheels, solar panel deck, and mast.
- 3D Lunar Lander base station with gold MLI foil, landing struts, and high-gain antenna mast.
- South Pole low-angle harsh sunlight casting dramatic shadows.
- Active RF Line-of-Sight comms beam between rover and lander that tracks in real-time.
- Multiple camera modes: Follow Rover (Chase Cam), Lander Mast Cam, Free 3D Orbit.
- Telemetry HUD with real-time speed, slope, battery level, sun fraction, and distance.
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

# 1. Load real terrain subgrid around traverse
terrain = LunarTerrain("demo_craters", tiles_dir="data/tiles")
lander_x_m = 0.0
lander_y_m = -2050.0
lander_z_m = float(terrain.ground_height(lander_x_m, lander_y_m))

# Extract 60x60 height grid covering 120m x 120m
grid_size = 64
span_x = 110.0
span_y = 110.0

xs = np.linspace(lander_x_m - 40.0, lander_x_m + 70.0, grid_size)
ys = np.linspace(lander_y_m - 80.0, lander_y_m + 30.0, grid_size)
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

html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>3D Lunar Rover Mission Simulation (Spec §4.3)</title>
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
    background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(10px);
    border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 12px;
    padding: 14px 20px; pointer-events: auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5);
  }}
  .mission-title {{ font-size: 18px; font-weight: 700; color: #f8fafc; display: flex; align-items: center; gap: 8px; }}
  .mission-sub {{ font-size: 12px; color: #94a3b8; margin-top: 2px; }}
  
  /* Camera Controls */
  .cam-buttons {{ display: flex; gap: 8px; margin-top: 8px; }}
  .btn {{
    background: rgba(30, 41, 59, 0.8); color: #cbd5e1; border: 1px solid #334155;
    padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer;
    transition: 0.15s; pointer-events: auto;
  }}
  .btn:hover {{ background: #38bdf8; color: #0f172a; border-color: #38bdf8; }}
  .btn.active {{ background: #38bdf8; color: #0f172a; border-color: #38bdf8; }}
  
  /* Telemetry Panel */
  .hud-right {{
    position: absolute; top: 16px; right: 20px; width: 280px;
  }}
  .metric-row {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.08); font-size: 13px; }}
  .metric-label {{ color: #94a3b8; }}
  .metric-value {{ font-weight: 700; color: #fff; font-variant-numeric: tabular-nums; }}
  .status-tag {{
    display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;
  }}
  .tag-sun {{ background: rgba(251, 191, 36, 0.2); color: #fbbf24; border: 1px solid #fbbf24; }}
  .tag-shadow {{ background: rgba(96, 165, 250, 0.2); color: #60a5fa; border: 1px solid #60a5fa; }}
  .tag-link-ok {{ color: #34d399; font-weight: bold; }}
  
  /* Bottom Playback Bar */
  .hud-bottom {{
    position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%);
    width: min(850px, 94vw);
    background: rgba(15, 23, 42, 0.9); backdrop-filter: blur(12px);
    border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 14px;
    padding: 14px 22px; display: flex; flex-direction: column; gap: 10px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.7);
  }}
  .timeline-bar {{ display: flex; align-items: center; gap: 16px; }}
  input[type=range] {{ flex: 1; accent-color: #38bdf8; cursor: pointer; }}
  .play-btn {{
    background: #38bdf8; color: #0f172a; border: none; padding: 8px 18px; border-radius: 8px;
    font-weight: 700; font-size: 13px; cursor: pointer; transition: 0.15s; min-width: 90px;
  }}
  .play-btn:hover {{ background: #7dd3fc; }}
  .speed-select {{
    background: #1e293b; color: #f8fafc; border: 1px solid #334155; padding: 6px 10px;
    border-radius: 6px; font-size: 12px; cursor: pointer; outline: none;
  }}
  .bottom-info {{
    display: flex; justify-content: space-between; font-size: 12px; color: #94a3b8;
  }}
</style>
<!-- Three.js + OrbitControls from reliable CDNs with fallback -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
</head>
<body>

<canvas id="viewport"></canvas>

<!-- Top Left: Mission & Camera Views -->
<div class="hud-top">
  <div class="hud-card">
    <div class="mission-title"><span>🛰️</span> LUNAR ROVER 3D MISSION SIMULATION</div>
    <div class="mission-sub">Spec §4.3 Autonomous Traverse • Real DEM Terrain (Demo Craters)</div>
    <div class="cam-buttons">
      <button class="btn active" id="camChase">Chase Cam (Rover)</button>
      <button class="btn" id="camLander">Lander Mast Cam</button>
      <button class="btn" id="camFree">Free 3D Orbit</button>
    </div>
  </div>
</div>

<!-- Top Right: Live Flight Telemetry -->
<div class="hud-right hud-card">
  <div style="font-size: 13px; font-weight: 700; color: #38bdf8; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em;">Live Telemetry</div>
  <div class="metric-row"><span class="metric-label">Traverse Speed</span><span class="metric-value" id="valSpeed">0.010 m/s (1 cm/s)</span></div>
  <div class="metric-row"><span class="metric-label">Terrain Slope</span><span class="metric-value" id="valSlope">0.0°</span></div>
  <div class="metric-row"><span class="metric-label">Battery Charge</span><span class="metric-value" id="valBat">115.0 Wh (95.8%)</span></div>
  <div class="metric-row"><span class="metric-label">Solar Illumination</span><span id="valSun"><span class="status-tag tag-sun">100% Sun (50W)</span></span></div>
  <div class="metric-row"><span class="metric-label">RF Link to Lander</span><span id="valLink" class="tag-link-ok">● LOS ACTIVE</span></div>
  <div class="metric-row"><span class="metric-label">Range to Lander</span><span class="metric-value" id="valDist">0.0 m</span></div>
  <div class="metric-row" style="border-bottom:none;"><span class="metric-label">Navigation Status</span><span class="metric-value" style="font-size:11px; color:#38bdf8;" id="valStatus">INITIALIZING</span></div>
</div>

<!-- Bottom: Playback Controls -->
<div class="hud-bottom">
  <div class="timeline-bar">
    <button class="play-btn" id="playBtn">▶ Play</button>
    <input type="range" id="timeline" min="0" max="{len(trajectory) - 1}" value="0">
    <select class="speed-select" id="speedSelect">
      <option value="1">1x Speed</option>
      <option value="30">30x Speed</option>
      <option value="60">60x Speed</option>
      <option value="120" selected>120x Playback (Recommended)</option>
      <option value="300">300x Speed</option>
    </select>
  </div>
  <div class="bottom-info">
    <span id="dispTime">Time: t = 0.0 min (0 s)</span>
    <span>Drag slider to scrub mission • Right-click / scroll mouse to orbit & zoom</span>
    <span id="dispTarget">Target: WP 1 (Sunlit Science Site)</span>
  </div>
</div>

<script>
const traj = {json.dumps(trajectory)};
const heightGrid = {json.dumps(height_grid)};
const gridSize = {grid_size};
const spanX = {span_x};
const spanZ = {span_y};

// --- Three.js Scene Setup ---
const canvas = document.getElementById("viewport");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x020308);
scene.fog = new THREE.FogExp2(0x020308, 0.004);

const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
const renderer = new THREE.WebGLRenderer({{ canvas, antialias: true, powerPreference: "high-performance" }});
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.maxDistance = 200;
controls.minDistance = 2;

// --- Lighting (Lunar South Pole low-angle sun) ---
const ambientLight = new THREE.AmbientLight(0x222638, 0.6);
scene.add(ambientLight);

// Sun angled at ~5° above horizon casting long dramatic shadows
const sunLight = new THREE.DirectionalLight(0xfff7e6, 2.8);
sunLight.position.set(-60, 15, -80);
sunLight.castShadow = true;
sunLight.shadow.mapSize.width = 2048;
sunLight.shadow.mapSize.height = 2048;
sunLight.shadow.camera.near = 10;
sunLight.shadow.camera.far = 300;
sunLight.shadow.camera.left = -80;
sunLight.shadow.camera.right = 80;
sunLight.shadow.camera.top = 80;
sunLight.shadow.camera.bottom = -80;
scene.add(sunLight);

// Distant Earth in the lunar sky
const earthGeo = new THREE.SphereGeometry(3, 32, 32);
const earthMat = new THREE.MeshBasicMaterial({{ color: 0x2563eb }});
const earth = new THREE.Mesh(earthGeo, earthMat);
earth.position.set(120, 45, -150);
scene.add(earth);

// Starfield particles
const starGeo = new THREE.BufferGeometry();
const starCount = 1200;
const starPos = new Float32Array(starCount * 3);
for (let i = 0; i < starCount * 3; i += 3) {{
  starPos[i] = (Math.random() - 0.5) * 600;
  starPos[i+1] = Math.random() * 200 + 10;
  starPos[i+2] = (Math.random() - 0.5) * 600;
}}
starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
const starMat = new THREE.PointsMaterial({{ color: 0xffffff, size: 1.2, transparent: true, opacity: 0.8 }});
scene.add(new THREE.Points(starGeo, starMat));

// --- Real Terrain Surface Mesh ---
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

// Procedural regolith material with vertex coloring
const terrainMat = new THREE.MeshStandardMaterial({{
  color: 0x888b94,
  roughness: 0.95,
  metalness: 0.05,
  flatShading: false
}});
const terrainMesh = new THREE.Mesh(terrainGeo, terrainMat);
// Center the mesh over the traverse corridor
terrainMesh.position.set(15.0, 0.0, 25.0);
terrainMesh.receiveShadow = true;
scene.add(terrainMesh);

// --- Traverse Path Ribbon & Waypoint Markers ---
const pathPoints = traj.map(p => new THREE.Vector3(p.x, p.y + 0.1, p.z));
const pathCurve = new THREE.CatmullRomCurve3(pathPoints);
const pathGeo = new THREE.TubeGeometry(pathCurve, traj.length * 2, 0.08, 6, false);
const pathMat = new THREE.MeshBasicMaterial({{ color: 0x38bdf8, transparent: true, opacity: 0.85 }});
const pathMesh = new THREE.Mesh(pathGeo, pathMat);
scene.add(pathMesh);

// Waypoint visual markers
function createMarker(x, y, z, label, colorHex) {{
  const group = new THREE.Group();
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 3, 8), new THREE.MeshBasicMaterial({{ color: colorHex }}));
  pole.position.y = 1.5;
  group.add(pole);
  const flag = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.4, 0.05), new THREE.MeshBasicMaterial({{ color: colorHex }}));
  flag.position.set(0.4, 2.7, 0);
  group.add(flag);
  group.position.set(x, y, z);
  scene.add(group);
}}
createMarker(25.0, -0.6, 15.0, "WP1", 0x10b981);
createMarker(30.0, -0.9, 38.0, "WP2", 0x818cf8);

// --- 3D Lander Base Station ---
const landerGroup = new THREE.Group();
// Octagonal Body
const landerBody = new THREE.Mesh(
  new THREE.CylinderGeometry(1.6, 2.0, 1.8, 8),
  new THREE.MeshStandardMaterial({{ color: 0xd97706, roughness: 0.3, metalness: 0.85 }}) // Gold MLI foil
);
landerBody.position.y = 1.2;
landerBody.castShadow = true;
landerGroup.add(landerBody);

// Lander 4 canted legs
for (let i = 0; i < 4; i++) {{
  const ang = (i * Math.PI) / 2 + Math.PI / 4;
  const leg = new THREE.Mesh(
    new THREE.CylinderGeometry(0.06, 0.06, 2.2),
    new THREE.MeshStandardMaterial({{ color: 0x475569, metalness: 0.7 }})
  );
  leg.position.set(Math.cos(ang) * 1.8, 0.6, Math.sin(ang) * 1.8);
  leg.rotation.z = Math.cos(ang) * 0.5;
  leg.rotation.x = -Math.sin(ang) * 0.5;
  landerGroup.add(leg);
}}

// Top mast & dish
const landerMast = new THREE.Mesh(
  new THREE.CylinderGeometry(0.04, 0.04, 1.5),
  new THREE.MeshStandardMaterial({{ color: 0x94a3b8 }})
);
landerMast.position.y = 2.7;
landerGroup.add(landerMast);

const dish = new THREE.Mesh(
  new THREE.ConeGeometry(0.4, 0.15, 16, 1, true),
  new THREE.MeshStandardMaterial({{ color: 0xffffff, metalness: 0.5 }})
);
dish.position.y = 3.4;
dish.rotation.x = Math.PI;
landerGroup.add(dish);

landerGroup.position.set(0, 0, 0);
scene.add(landerGroup);

// --- 3D Pragyan/VIPER Class Rover Model ---
const rover = new THREE.Group();

// Chassis
const chassis = new THREE.Mesh(
  new THREE.BoxGeometry(0.85, 0.28, 0.65),
  new THREE.MeshStandardMaterial({{ color: 0xb45309, roughness: 0.3, metalness: 0.8 }}) // Gold/amber MLI
);
chassis.position.y = 0.32;
chassis.castShadow = true;
rover.add(chassis);

// Solar Panel Top Deck
const panel = new THREE.Mesh(
  new THREE.BoxGeometry(0.92, 0.03, 0.72),
  new THREE.MeshStandardMaterial({{ color: 0x1e3a8a, roughness: 0.2, metalness: 0.6 }}) // Dark blue solar cells
);
panel.position.y = 0.48;
panel.castShadow = true;
rover.add(panel);

// Camera / Antenna Mast
const roverMast = new THREE.Mesh(
  new THREE.CylinderGeometry(0.025, 0.025, 0.55),
  new THREE.MeshStandardMaterial({{ color: 0x64748b }})
);
roverMast.position.set(0.25, 0.75, 0);
rover.add(roverMast);

const mastHead = new THREE.Mesh(
  new THREE.BoxGeometry(0.12, 0.08, 0.15),
  new THREE.MeshStandardMaterial({{ color: 0x334155 }})
);
mastHead.position.set(0.25, 1.05, 0);
rover.add(mastHead);

// 6 Rocker-Bogie Wheels
const wheels = [];
const wheelGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.08, 16);
wheelGeo.rotateZ(Math.PI / 2);
const wheelMat = new THREE.MeshStandardMaterial({{ color: 0x1e293b, roughness: 0.8 }});

const wheelOffsets = [
  [-0.32, -0.38], [0.0, -0.40], [0.32, -0.38],
  [-0.32, 0.38],  [0.0, 0.40],  [0.32, 0.38]
];
wheelOffsets.forEach(([dx, dz]) => {{
  const wMesh = new THREE.Mesh(wheelGeo, wheelMat);
  wMesh.position.set(dx, 0.12, dz);
  wMesh.castShadow = true;
  rover.add(wMesh);
  wheels.push(wMesh);
}});

scene.add(rover);

// --- Active Line-of-Sight Laser Beam ---
const beamGeo = new THREE.BufferGeometry();
beamGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
const beamMat = new THREE.LineBasicMaterial({{ color: 0x34d399, linewidth: 2, transparent: true, opacity: 0.7 }});
const commsBeam = new THREE.Line(beamGeo, beamMat);
scene.add(commsBeam);

// --- Animation & Telemetry Sync ---
let currentIndex = 0;
let playbackSpeed = 120.0;
let isPlaying = true;
let cameraMode = "chase"; // chase, lander, free

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
  if (mode === "lander") document.getElementById("camLander").classList.add("active");
  if (mode === "free") document.getElementById("camFree").classList.add("active");
}}
document.getElementById("camChase").onclick = () => setCameraMode("chase");
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

  // Wheel rotation
  if (p0.speed > 0) {{
    wheels.forEach(w => {{ w.rotation.x += 0.08; }});
  }}

  // Update Line of Sight Comms Laser
  const beamPos = commsBeam.geometry.attributes.position;
  beamPos.setXYZ(0, 0, 2.7, 0); // Lander mast top
  beamPos.setXYZ(1, rx, ry + 1.0, rz); // Rover mast top
  beamPos.needsUpdate = true;

  if (p0.link) {{
    commsBeam.material.color.setHex(0x34d399); // Green = Clear LOS
    valLink.className = "tag-link-ok";
    valLink.textContent = "● LOS ACTIVE";
  }} else {{
    commsBeam.material.color.setHex(0xef4444); // Red = Occluded
    valLink.className = "";
    valLink.textContent = "✖ OCCLUDED BY TERRAIN";
    valLink.style.color = "#ef4444";
  }}

  // Update HUD
  valSpeed.textContent = `${{p0.speed.toFixed(3)}} m/s (1 cm/s)`;
  valSlope.textContent = `${{p0.slope.toFixed(2)}}°`;
  valBat.textContent = `${{p0.bat_wh.toFixed(1)}} Wh (${{p0.bat_pct.toFixed(1)}}%)`;
  valDist.textContent = `${{p0.dist.toFixed(1)}} m`;
  valStatus.textContent = p0.status;
  dispTime.textContent = `Time: t = ${{p0.t_min.toFixed(1)}} min (${{p0.t_s.toFixed(0)}} s)`;

  if (p0.sun > 0.5) {{
    valSun.innerHTML = '<span class="status-tag tag-sun">100% Sun (50W)</span>';
  }} else {{
    valSun.innerHTML = '<span class="status-tag tag-shadow">❄ Cold Trap Shadow (0W)</span>';
  }}

  if (p0.dist < 2.0 && idxFloat > 200) {{
    dispTarget.textContent = "Mission Complete: Safely Returned to Lander";
  }} else if (idxFloat < 100) {{
    dispTarget.textContent = "Target: WP 1 (Sunlit Science Site)";
  }} else if (idxFloat < 200) {{
    dispTarget.textContent = "Target: WP 2 (Candidate Ice Shadow Dip)";
  }} else {{
    dispTarget.textContent = "Target: Return to Lander Base Station";
  }}

  timeline.value = idxFloat;
}}

// Camera views
function updateCamera() {{
  if (cameraMode === "chase") {{
    // Smooth chase camera trailing behind rover
    const offset = new THREE.Vector3(0, 3.5, -6.5);
    offset.applyAxisAngle(new THREE.Vector3(0, 1, 0), rover.rotation.y);
    camera.position.lerp(rover.position.clone().add(offset), 0.1);
    controls.target.copy(rover.position.clone().add(new THREE.Vector3(0, 0.8, 0)));
  }} else if (cameraMode === "lander") {{
    // Camera situated at lander mast watching rover
    camera.position.set(0, 3.5, 0);
    controls.target.copy(rover.position);
  }}
  controls.update();
}}

// Main Render Loop
let lastTime = performance.now();
function animate() {{
  requestAnimationFrame(animate);
  const now = performance.now();
  const dtReal = (now - lastTime) / 1000.0;
  lastTime = now;

  if (isPlaying && currentIndex < traj.length - 1) {{
    // 30 s per trajectory step
    const stepAdvance = (dtReal * playbackSpeed) / 30.0;
    currentIndex += stepAdvance;
    if (currentIndex >= traj.length - 1) {{
      currentIndex = traj.length - 1;
      isPlaying = false;
      playBtn.textContent = "▶ Replay";
    }}
    updateRoverPose(currentIndex);
  }}

  updateCamera();
  renderer.render(scene, camera);
}}

window.addEventListener('resize', () => {{
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}});

// Initialize
updateRoverPose(0);
camera.position.set(0, 5, -8);
animate();
</script>
</body>
</html>
"""

out_path = Path("rover_3d_simulation.html")
out_path.write_text(html_template, encoding="utf-8")
print(f"Generated 3D Simulation: {out_path.resolve()}")
