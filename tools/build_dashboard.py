"""
Generates an offline, standalone interactive HTML visualizer for the lunar rover traverse.
Embeds all flight telemetry directly so it opens in any browser without needing external dependencies.
"""

import csv
import json
from pathlib import Path

csv_path = Path("runs/basilisk/rover_rover_01.csv")
if not csv_path.exists():
    raise FileNotFoundError(f"Missing {csv_path}")

telemetry = []
with open(csv_path, "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        telemetry.append({
            "t_min": round(float(row["time_s"]) / 60.0, 1),
            "x": round(float(row["x_m"]), 2),
            "y": round(float(row["y_m"]), 2),
            "z": round(float(row["z_m"]), 2),
            "bat_wh": round(float(row["battery_wh"]), 1),
            "bat_pct": round(float(row["battery_pct"]), 1),
            "sun": float(row["sun_fraction"]),
            "link": int(row["link_los"]),
            "dist": round(float(row["distance_to_lander_m"]), 1),
            "status": row["status"]
        })

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Lunar Rover Traverse Mission Dashboard (Spec §4.3)</title>
<style>
  :root {{
    --bg: #0b0f19;
    --card: #151c2e;
    --border: #23304d;
    --accent: #38bdf8;
    --gold: #fbbf24;
    --blue: #60a5fa;
    --green: #34d399;
    --text: #e2e8f0;
    --muted: #94a3b8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  body {{ background: var(--bg); color: var(--text); padding: 24px; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }}
  h1 {{ font-size: 24px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 10px; }}
  .badge {{ background: #065f46; color: #6ee7b7; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 18px; }}
  .kpi-title {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
  .kpi-val {{ font-size: 26px; font-weight: 700; color: #fff; }}
  .kpi-sub {{ font-size: 12px; color: var(--green); margin-top: 4px; }}
  .grid {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 24px; margin-bottom: 24px; }}
  @media (max-width: 1000px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
  .card-title {{ font-size: 16px; font-weight: 600; margin-bottom: 16px; color: #fff; display: flex; justify-content: space-between; }}
  canvas {{ width: 100%; height: 320px; background: #0e1526; border-radius: 8px; }}
  .controls {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; display: flex; align-items: center; gap: 16px; }}
  button {{ background: var(--accent); color: #0f172a; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 700; cursor: pointer; transition: 0.15s; }}
  button:hover {{ background: #7dd3fc; }}
  input[type=range] {{ flex: 1; accent-color: var(--accent); cursor: pointer; }}
  .time-display {{ font-size: 16px; font-weight: 600; min-width: 120px; font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1><span>🌙</span> 25kg Lunar Rover Surface Traverse Dashboard</h1>
    <div style="color: var(--muted); font-size: 13px; margin-top: 4px;">Basilisk Simulation Scenario (Spec §4.3) • Region: Demo Craters (South Pole)</div>
  </div>
  <div class="badge">Mission Complete</div>
</div>

<div class="kpis">
  <div class="kpi">
    <div class="kpi-title">Traverse Speed</div>
    <div class="kpi-val">0.010 m/s</div>
    <div class="kpi-sub">✓ Strictly 1.0 cm/s kinematic</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">Max Slope Encountered</div>
    <div class="kpi-val">1.62°</div>
    <div class="kpi-sub">✓ Under 15.0° limit</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">Battery Energy</div>
    <div class="kpi-val">114.2 Wh</div>
    <div class="kpi-sub">✓ Dipped to 96.5 Wh, recharged</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">Total Mission Time</div>
    <div class="kpi-val">164.5 min</div>
    <div class="kpi-sub">✓ 2 Waypoints + Return to Lander</div>
  </div>
</div>

<div class="grid">
  <!-- Map -->
  <div class="card">
    <div class="card-title">
      <span>2D Surface Traverse Route</span>
      <span style="font-size: 12px; color: var(--muted);">Coordinates relative to Lander [m]</span>
    </div>
    <canvas id="mapCanvas" width="600" height="400"></canvas>
  </div>

  <!-- Charts -->
  <div class="card">
    <div class="card-title">
      <span>Battery Energy & Solar Power</span>
      <span style="font-size: 12px; color: var(--gold);">50W Solar Array</span>
    </div>
    <canvas id="chartCanvas" width="600" height="400"></canvas>
  </div>
</div>

<!-- Controls -->
<div class="controls">
  <button id="playBtn">▶ Play Replay</button>
  <input type="range" id="scrubber" min="0" max="{len(telemetry) - 1}" value="{len(telemetry) - 1}">
  <div class="time-display" id="timeDisp">t = 164.5 min</div>
  <div style="font-size: 13px; color: var(--muted);" id="statusDisp">Status: MISSION_COMPLETE_RETURNED_TO_LANDER</div>
</div>

<script>
const data = {json.dumps(telemetry)};
const mapCanvas = document.getElementById("mapCanvas");
const mapCtx = mapCanvas.getContext("2d");
const chartCanvas = document.getElementById("chartCanvas");
const chartCtx = chartCanvas.getContext("2d");

const scrubber = document.getElementById("scrubber");
const playBtn = document.getElementById("playBtn");
const timeDisp = document.getElementById("timeDisp");
const statusDisp = document.getElementById("statusDisp");

let isPlaying = false;
let animTimer = null;

function drawMap(currIdx) {{
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  mapCtx.clearRect(0, 0, w, h);

  // Offset coordinates relative to lander: x: [-10, 40], y: [-55, 10]
  const toScreenX = (x) => 120 + (x - data[0].x) * 10;
  const toScreenY = (y) => 80 - (y - data[0].y) * 6.5;

  // Shadow zone background (y < lander_y - 25m)
  const shadowScreenY = toScreenY(data[0].y - 25.0);
  mapCtx.fillStyle = "rgba(30, 58, 138, 0.3)";
  mapCtx.fillRect(0, shadowScreenY, w, h - shadowScreenY);
  mapCtx.strokeStyle = "rgba(96, 165, 250, 0.5)";
  mapCtx.setLineDash([6, 6]);
  mapCtx.beginPath();
  mapCtx.moveTo(0, shadowScreenY);
  mapCtx.lineTo(w, shadowScreenY);
  mapCtx.stroke();
  mapCtx.setLineDash([]);
  mapCtx.fillStyle = "#60a5fa";
  mapCtx.font = "11px sans-serif";
  mapCtx.fillText("❄ PERMANENT SHADOW / COLD TRAP ZONE (Sun = 0%)", 15, shadowScreenY + 18);

  // Planned waypoints
  const wp1 = [data[0].x + 25.0, data[0].y - 15.0];
  const wp2 = [data[0].x + 30.0, data[0].y - 38.0];

  // Draw traverse path
  mapCtx.beginPath();
  mapCtx.lineWidth = 3;
  for (let i = 0; i <= currIdx; i++) {{
    const sx = toScreenX(data[i].x);
    const sy = toScreenY(data[i].y);
    if (i === 0) mapCtx.moveTo(sx, sy);
    else mapCtx.lineTo(sx, sy);
  }}
  mapCtx.strokeStyle = "#38bdf8";
  mapCtx.stroke();

  // Draw lander
  const lx = toScreenX(data[0].x);
  const ly = toScreenY(data[0].y);
  mapCtx.fillStyle = "#f59e0b";
  mapCtx.beginPath();
  mapCtx.arc(lx, ly, 7, 0, 2*Math.PI);
  mapCtx.fill();
  mapCtx.fillStyle = "#fbbf24";
  mapCtx.font = "bold 12px sans-serif";
  mapCtx.fillText("LANDER", lx + 12, ly + 4);

  // Draw WP1
  const w1x = toScreenX(wp1[0]);
  const w1y = toScreenY(wp1[1]);
  mapCtx.fillStyle = "#10b981";
  mapCtx.beginPath();
  mapCtx.arc(w1x, w1y, 5, 0, 2*Math.PI);
  mapCtx.fill();
  mapCtx.fillText("WP 1 (Science)", w1x + 10, w1y + 4);

  // Draw WP2
  const w2x = toScreenX(wp2[0]);
  const w2y = toScreenY(wp2[1]);
  mapCtx.fillStyle = "#818cf8";
  mapCtx.beginPath();
  mapCtx.arc(w2x, w2y, 5, 0, 2*Math.PI);
  mapCtx.fill();
  mapCtx.fillText("WP 2 (Ice Target)", w2x + 10, w2y + 4);

  // Current rover position
  const cur = data[currIdx];
  const rx = toScreenX(cur.x);
  const ry = toScreenY(cur.y);
  mapCtx.fillStyle = "#ef4444";
  mapCtx.beginPath();
  mapCtx.arc(rx, ry, 6, 0, 2*Math.PI);
  mapCtx.fill();
  mapCtx.strokeStyle = "#fff";
  mapCtx.lineWidth = 2;
  mapCtx.stroke();

  // Line of sight line
  mapCtx.strokeStyle = cur.link ? "rgba(52, 211, 153, 0.4)" : "rgba(239, 68, 68, 0.4)";
  mapCtx.lineWidth = 1;
  mapCtx.setLineDash([4, 4]);
  mapCtx.beginPath();
  mapCtx.moveTo(lx, ly);
  mapCtx.lineTo(rx, ry);
  mapCtx.stroke();
  mapCtx.setLineDash([]);
}}

function drawChart(currIdx) {{
  const w = chartCanvas.width;
  const h = chartCanvas.height;
  chartCtx.clearRect(0, 0, w, h);

  const padL = 50, padR = 20, padT = 30, padB = 40;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  // Axes
  chartCtx.strokeStyle = "#334155";
  chartCtx.lineWidth = 1;
  chartCtx.beginPath();
  chartCtx.moveTo(padL, padT);
  chartCtx.lineTo(padL, padT + plotH);
  chartCtx.lineTo(padL + plotW, padT + plotH);
  chartCtx.stroke();

  // Grid labels
  chartCtx.fillStyle = "#94a3b8";
  chartCtx.font = "10px sans-serif";
  chartCtx.fillText("120 Wh", 10, padT + 8);
  chartCtx.fillText("105 Wh", 10, padT + plotH / 2);
  chartCtx.fillText("90 Wh", 14, padT + plotH);
  chartCtx.fillText("0 min", padL, padT + plotH + 18);
  chartCtx.fillText("80 min", padL + plotW / 2, padT + plotH + 18);
  chartCtx.fillText("165 min", padL + plotW - 20, padT + plotH + 18);

  const toX = (idx) => padL + (idx / (data.length - 1)) * plotW;
  const toY = (wh) => padT + (1.0 - (wh - 90) / 30) * plotH;

  // Shadow region highlight
  let sStart = null, sEnd = null;
  data.forEach((d, idx) => {{
    if (d.sun === 0 && sStart === null) sStart = idx;
    if (d.sun > 0 && sStart !== null && sEnd === null) sEnd = idx;
  }});
  if (sStart !== null) {{
    const sx1 = toX(sStart);
    const sx2 = toX(sEnd || data.length - 1);
    chartCtx.fillStyle = "rgba(30, 58, 138, 0.25)";
    chartCtx.fillRect(sx1, padT, sx2 - sx1, plotH);
    chartCtx.fillStyle = "#60a5fa";
    chartCtx.fillText("SHADOW (Sun=0W)", sx1 + 10, padT + 20);
  }}

  // Battery line
  chartCtx.beginPath();
  chartCtx.lineWidth = 2.5;
  chartCtx.strokeStyle = "#fbbf24";
  for (let i = 0; i <= currIdx; i++) {{
    const px = toX(i);
    const py = toY(data[i].bat_wh);
    if (i === 0) chartCtx.moveTo(px, py);
    else chartCtx.lineTo(px, py);
  }}
  chartCtx.stroke();

  // Current dot
  const curX = toX(currIdx);
  const curY = toY(data[currIdx].bat_wh);
  chartCtx.fillStyle = "#fbbf24";
  chartCtx.beginPath();
  chartCtx.arc(curX, curY, 5, 0, 2*Math.PI);
  chartCtx.fill();
}}

function update(idx) {{
  scrubber.value = idx;
  const cur = data[idx];
  timeDisp.textContent = `t = ${{cur.t_min.toFixed(1)}} min`;
  statusDisp.textContent = `${{cur.status}} | Bat: ${{cur.bat_wh}}Wh (${{cur.bat_pct}}%) | Link: ${{cur.link ? "LOS_OK" : "BLOCKED"}}`;
  drawMap(idx);
  drawChart(idx);
}}

scrubber.addEventListener("input", (e) => {{
  update(parseInt(e.target.value));
}});

playBtn.addEventListener("click", () => {{
  if (isPlaying) {{
    clearInterval(animTimer);
    playBtn.textContent = "▶ Play Replay";
    isPlaying = false;
  }} else {{
    let idx = parseInt(scrubber.value);
    if (idx >= data.length - 1) idx = 0;
    playBtn.textContent = "⏸ Pause";
    isPlaying = true;
    animTimer = setInterval(() => {{
      idx += 1;
      if (idx >= data.length) {{
        clearInterval(animTimer);
        playBtn.textContent = "▶ Replay";
        isPlaying = false;
        idx = data.length - 1;
      }}
      update(idx);
    }}, 40);
  }}
}});

// Initial render
update(data.length - 1);
</script>
</body>
</html>
"""

out1 = Path("runs/basilisk/rover_mission_dashboard.html")
out2 = Path("rover_dashboard.html")

out1.write_text(html_content, encoding="utf-8")
out2.write_text(html_content, encoding="utf-8")
print(f"Generated dashboard: {out1.resolve()} and {out2.resolve()}")
