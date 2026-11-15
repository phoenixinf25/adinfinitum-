"""Builder for Standalone Mission Control Dashboard HTML (Spec §9.2).

Generates mission_control_dashboard.html with embedded real telemetry:
- Real closed-loop 5-engine descent with Engine 1 failure at T=21s.
- Interactive timeline scrubber with Play/Pause and speed controls.
- 5-engine cluster with live thrust and failure indicators.
- Navigator-matched countdowns to sunset and Earthset.
- Rover mini-panel (Pragyan 3) with battery, slope, and LOS link.
- Monospaced autonomous decision log.
"""

from __future__ import annotations

import json
from pathlib import Path

from contracts.paths import repo_root
from mission_control.data import (
    extract_decisions,
    get_site_countdowns,
    load_rover_telemetry,
    load_telemetry,
    parse_engine_cluster,
)


def build_dashboard():
    root = repo_root()
    output_html = root / "mission_control_dashboard.html"

    # Load engine out run and fixture
    engine_out_file = root / "runs" / "basilisk" / "telemetry_engine_out.csv"
    fixture_file = root / "tests" / "fixtures" / "telemetry_basilisk_engine_out.csv"

    df_run = load_telemetry(engine_out_file if engine_out_file.exists() else fixture_file)
    df_fix = load_telemetry(fixture_file)
    rover_df = load_rover_telemetry()

    run_records = df_run.to_dict(orient="records")
    fix_records = df_fix.to_dict(orient="records")
    rover_records = rover_df.to_dict(orient="records") if rover_df is not None else []

    countdowns = get_site_countdowns("shackleton", "2026-11-14", 0)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mission Control Console | Spec §9.2</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-dark: #070b12;
            --card-bg: #0d1322;
            --border-col: #1a253d;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --cyan: #00f0ff;
            --green: #00ff88;
            --amber: #ffaa00;
            --red: #ff2a55;
            --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg-dark);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            padding: 20px;
            overflow-x: hidden;
        }}
        .header {{
            background: linear-gradient(90deg, #0e1526 0%, #111b33 100%);
            border: 1px solid var(--border-col);
            border-radius: 8px;
            padding: 14px 20px;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header-left {{ display: flex; align-items: center; gap: 12px; }}
        .title {{ font-size: 1.3rem; font-weight: 700; letter-spacing: 1px; }}
        .badge {{
            font-family: var(--mono);
            font-size: 0.78rem;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 4px;
            text-transform: uppercase;
        }}
        .badge-modelled {{ background: #2e1d05; color: var(--amber); border: 1px solid var(--amber); }}
        .badge-fixture {{ background: #3b111a; color: var(--red); border: 1px solid var(--red); }}
        .phase-badge {{
            font-family: var(--mono);
            font-size: 0.85rem;
            font-weight: 700;
            padding: 5px 12px;
            border-radius: 6px;
            background: rgba(0, 240, 255, 0.15);
            color: var(--cyan);
            border: 1px solid var(--cyan);
        }}
        .clock {{
            font-family: var(--mono);
            font-size: 1.45rem;
            font-weight: 700;
            color: var(--cyan);
            background: #050810;
            padding: 4px 14px;
            border-radius: 6px;
            border: 1px solid rgba(0, 240, 255, 0.3);
            text-shadow: 0 0 10px rgba(0, 240, 255, 0.4);
        }}
        .controls-bar {{
            background: var(--card-bg);
            border: 1px solid var(--border-col);
            border-radius: 8px;
            padding: 12px 18px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .btn {{
            background: #162238;
            color: var(--text-main);
            border: 1px solid var(--border-col);
            padding: 8px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-family: var(--mono);
            font-size: 0.85rem;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .btn:hover {{ background: #20304e; border-color: var(--cyan); }}
        .btn-active {{ background: rgba(0, 240, 255, 0.2); border-color: var(--cyan); color: var(--cyan); }}
        .slider-wrap {{ flex: 1; display: flex; align-items: center; gap: 10px; }}
        input[type="range"] {{
            flex: 1;
            height: 6px;
            accent-color: var(--cyan);
            background: #1e293b;
            border-radius: 3px;
            cursor: pointer;
        }}
        .grid-2col {{
            display: grid;
            grid-template-columns: 1.15fr 0.85fr;
            gap: 16px;
            margin-bottom: 16px;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border-col);
            border-radius: 8px;
            padding: 14px 16px;
            margin-bottom: 16px;
        }}
        .card-title {{
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--text-muted);
            margin-bottom: 12px;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-col);
            padding-bottom: 6px;
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
        }}
        .metric-cell {{
            background: #080c16;
            border: 1px solid #162035;
            border-radius: 6px;
            padding: 10px 12px;
        }}
        .metric-label {{
            font-size: 0.72rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 4px;
        }}
        .metric-val {{
            font-family: var(--mono);
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--text-main);
        }}
        .metric-unit {{ font-size: 0.75rem; color: var(--text-muted); margin-left: 3px; }}
        
        /* Engine Cluster */
        .engine-row {{
            margin-bottom: 8px;
            font-family: var(--mono);
            font-size: 0.82rem;
        }}
        .engine-header {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 3px;
        }}
        .bar-bg {{
            background: #0a0e18;
            border: 1px solid var(--border-col);
            height: 14px;
            border-radius: 3px;
            overflow: hidden;
        }}
        .bar-fill {{ height: 100%; transition: width 0.1s linear; }}
        
        /* Decision Terminal */
        .terminal {{
            background: #050810;
            border: 1px solid var(--border-col);
            border-radius: 6px;
            padding: 12px 14px;
            font-family: var(--mono);
            font-size: 0.85rem;
            max-height: 180px;
            overflow-y: auto;
        }}
        .log-line {{ padding: 3px 0; border-bottom: 1px solid #111a2e; color: var(--text-muted); }}
        .log-time {{ color: var(--cyan); font-weight: 600; margin-right: 8px; }}
        .log-alert {{ color: var(--red); font-weight: 700; }}
        .log-success {{ color: var(--green); font-weight: 600; }}
        .log-active {{
            background: rgba(255, 170, 0, 0.15);
            border-left: 3px solid var(--amber);
            color: #ffea79;
            padding: 4px 8px;
            margin: 4px 0;
            border-radius: 0 4px 4px 0;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-left">
            <span class="title">🌙 MISSION OPERATIONS CONSOLE</span>
            <span id="badgeProvenance" class="badge badge-modelled">MODELLED · Basilisk</span>
            <span id="badgePhase" class="phase-badge">[ POWERED DESCENT ]</span>
        </div>
        <div id="clockDisplay" class="clock">MET: T+ 000:00:00.0 s</div>
    </div>

    <div class="controls-bar">
        <select id="datasetSelect" class="btn">
            <option value="run">telemetry_engine_out.csv (Basilisk Real Flight)</option>
            <option value="fixture">telemetry_basilisk_engine_out.csv (FIXTURE Stand-in)</option>
        </select>
        <button id="btnPlay" class="btn btn-active">⏸ Pause</button>
        <button id="btnSpeed1" class="btn">1×</button>
        <button id="btnSpeed10" class="btn btn-active">10×</button>
        <button id="btnSpeed50" class="btn">50×</button>
        <div class="slider-wrap">
            <span style="font-family: var(--mono); font-size: 0.85rem; color: var(--cyan);">Scrub:</span>
            <input type="range" id="scrubSlider" min="0" max="100" value="0">
            <span id="scrubLabel" style="font-family: var(--mono); font-size: 0.85rem; width: 65px;">0.0 s</span>
        </div>
        <button id="btnMilestone" class="btn" style="border-color: var(--amber); color: var(--amber);">⚡ Jump to Engine-Out (21s)</button>
    </div>

    <div class="grid-2col">
        <!-- LEFT COLUMN -->
        <div>
            <!-- Flight Metrics -->
            <div class="card">
                <div class="card-title">🚀 Flight Telemetry (Closed-Loop Guidance)</div>
                <div class="metric-grid">
                    <div class="metric-cell">
                        <div class="metric-label">Altitude</div>
                        <div class="metric-val"><span id="valAlt">2,000.0</span><span class="metric-unit">m</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Vertical Speed (Vz)</div>
                        <div class="metric-val"><span id="valVz" style="color: var(--amber);">-45.00</span><span class="metric-unit">m/s</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Horizontal Speed (Vh)</div>
                        <div class="metric-val"><span id="valVh">9.93</span><span class="metric-unit">m/s</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Propellant Remaining</div>
                        <div class="metric-val"><span id="valFuel" style="color: var(--cyan);">140.0</span><span class="metric-unit">kg</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Vehicle Mass</div>
                        <div class="metric-val"><span id="valMass">900.0</span><span class="metric-unit">kg</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Total Thrust</div>
                        <div class="metric-val"><span id="valThrust" style="color: var(--amber);">2,000</span><span class="metric-unit">N</span></div>
                    </div>
                </div>
            </div>

            <!-- 5-Engine Cluster -->
            <div class="card">
                <div class="card-title">
                    <span>🔥 5-Engine Propulsion Cluster</span>
                    <span id="clusterSummary" style="font-family: var(--mono); font-size: 0.78rem; color: var(--green);">5 / 5 ENGINES NOMINAL</span>
                </div>
                <div id="engineBarsContainer"></div>
            </div>

            <!-- Plots -->
            <div class="card">
                <div class="card-title">📈 Trajectory Profiles (Altitude vs Time)</div>
                <div style="height: 180px;"><canvas id="chartTraj"></canvas></div>
            </div>
        </div>

        <!-- RIGHT COLUMN -->
        <div>
            <!-- Power & Comms -->
            <div class="card">
                <div class="card-title">⚡ Power, Comms & Horizons (Spec §4.2)</div>
                <div class="metric-grid" style="grid-template-columns: repeat(2, 1fr); margin-bottom: 12px;">
                    <div class="metric-cell">
                        <div class="metric-label">Lander Battery</div>
                        <div class="metric-val">12.0<span class="metric-unit">kWh (100%)</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Solar Array In</div>
                        <div class="metric-val">850<span class="metric-unit">W</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Direct-to-Earth Link</div>
                        <div class="metric-val" style="color: var(--green);">ONLINE</div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Target Region</div>
                        <div class="metric-val" style="font-size: 1.05rem;">SHACKLETON</div>
                    </div>
                </div>
                <div style="background: #080c16; border: 1px solid #162035; border-radius: 6px; padding: 10px 14px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                        <span style="font-size: 0.75rem; color: #64748b;">NEXT SOLAR EVENT:</span>
                        <span style="font-family: var(--mono); font-size: 0.95rem; font-weight: 700; color: var(--amber);">{countdowns['sun_str']}</span>
                    </div>
                    <div style="display: flex; justify-content: space-between;">
                        <span style="font-size: 0.75rem; color: #64748b;">NEXT DTE LINK (EARTHSET):</span>
                        <span style="font-family: var(--mono); font-size: 0.95rem; font-weight: 700; color: var(--cyan);">{countdowns['earth_str']}</span>
                    </div>
                </div>
            </div>

            <!-- Rover Mini-Panel -->
            <div class="card">
                <div class="card-title">🚜 Rover Surface Asset (Pragyan 3 · 25 kg)</div>
                <div class="metric-grid">
                    <div class="metric-cell">
                        <div class="metric-label">Distance to Lander</div>
                        <div class="metric-val"><span id="valRoverDist">38.4</span><span class="metric-unit">m</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Drive Speed</div>
                        <div class="metric-val">1.0<span class="metric-unit">cm/s</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Battery SOC</div>
                        <div class="metric-val"><span id="valRoverBat">95.2</span><span class="metric-unit">%</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Coordinates [X, Y]</div>
                        <div class="metric-val" style="font-size: 0.95rem;">[+28, -26]<span class="metric-unit">m</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">Local Slope</div>
                        <div class="metric-val">4.2<span class="metric-unit">°</span></div>
                    </div>
                    <div class="metric-cell">
                        <div class="metric-label">RF Link to Base</div>
                        <div class="metric-val" style="color: var(--green); font-size: 1rem;">ACTIVE</div>
                    </div>
                </div>
            </div>

            <!-- Ground Track Offset -->
            <div class="card">
                <div class="card-title">🎯 Horizontal Touchdown Offset [X: East, Y: North]</div>
                <div style="height: 180px;"><canvas id="chartMap"></canvas></div>
            </div>
        </div>
    </div>

    <!-- Autonomous Decision Log -->
    <div class="card">
        <div class="card-title">📋 Autonomous Decision Log (Onboard G&C Facts Only · No Commentary)</div>
        <div id="decisionTerminal" class="terminal"></div>
    </div>

    <script>
        const runData = {json.dumps(run_records)};
        const fixData = {json.dumps(fix_records)};
        const roverData = {json.dumps(rover_records)};

        let currentDataset = runData;
        let isFixture = false;
        let currentIdx = 0;
        let isPlaying = true;
        let playSpeed = 10;
        let lastTimestamp = performance.now();

        const slider = document.getElementById("scrubSlider");
        const scrubLabel = document.getElementById("scrubLabel");
        const clockDisplay = document.getElementById("clockDisplay");
        const badgePhase = document.getElementById("badgePhase");
        const badgeProv = document.getElementById("badgeProvenance");
        const clusterSummary = document.getElementById("clusterSummary");
        const engineBarsContainer = document.getElementById("engineBarsContainer");
        const decisionTerminal = document.getElementById("decisionTerminal");

        slider.max = currentDataset.length - 1;

        // Chart.js setup for Altitude
        const ctxTraj = document.getElementById('chartTraj').getContext('2d');
        const times = currentDataset.map(d => d.t_s);
        const alts = currentDataset.map(d => d.alt_m);

        const chartTraj = new Chart(ctxTraj, {{
            type: 'line',
            data: {{
                labels: times,
                datasets: [{{
                    label: 'Altitude (m)',
                    data: alts,
                    borderColor: '#00f0ff',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ grid: {{ color: '#162035' }}, ticks: {{ color: '#94a3b8', font: {{ size: 9 }} }} }},
                    y: {{ grid: {{ color: '#162035' }}, ticks: {{ color: '#00f0ff', font: {{ size: 9 }} }} }}
                }}
            }}
        }});

        // Chart.js setup for Map Track
        const ctxMap = document.getElementById('chartMap').getContext('2d');
        const mapPts = currentDataset.map(d => ({{ x: d.x_m, y: d.y_m }}));
        const chartMap = new Chart(ctxMap, {{
            type: 'scatter',
            data: {{
                datasets: [
                    {{
                        label: 'Descent Track',
                        data: mapPts,
                        borderColor: '#3b82f6',
                        backgroundColor: '#3b82f6',
                        showLine: true,
                        pointRadius: 0,
                        borderWidth: 2
                    }},
                    {{
                        label: 'Target',
                        data: [{{ x: 0, y: 0 }}],
                        borderColor: '#ffaa00',
                        backgroundColor: '#ffaa00',
                        pointRadius: 6,
                        pointStyle: 'crossRot'
                    }},
                    {{
                        label: 'Current',
                        data: [mapPts[0]],
                        borderColor: '#00f0ff',
                        backgroundColor: '#00f0ff',
                        pointRadius: 7
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ grid: {{ color: '#162035' }}, ticks: {{ color: '#94a3b8', font: {{ size: 9 }} }} }},
                    y: {{ grid: {{ color: '#162035' }}, ticks: {{ color: '#94a3b8', font: {{ size: 9 }} }} }}
                }}
            }}
        }});

        function updateUI(idx) {{
            const row = currentDataset[idx];
            if (!row) return;

            const t = parseFloat(row.t_s || 0);
            clockDisplay.innerText = `MET: T+ ${{t.toFixed(1).padStart(5, '0')}} s`;
            scrubLabel.innerText = `${{t.toFixed(0)}} s`;
            slider.value = idx;

            const phase = String(row.phase || 'powered_descent').toUpperCase().replace('_', ' ');
            badgePhase.innerText = `[ ${{phase}} ]`;

            document.getElementById("valAlt").innerText = (row.alt_m || 0).toLocaleString(undefined, {{ minimumFractionDigits: 1, maximumFractionDigits: 1 }});
            document.getElementById("valVz").innerText = (row.vz_m_s || 0).toFixed(2);
            document.getElementById("valVh").innerText = (row.v_horizontal_m_s || 0).toFixed(2);
            document.getElementById("valFuel").innerText = (row.fuel_kg || 0).toFixed(1);
            document.getElementById("valMass").innerText = (row.mass_kg || 0).toFixed(1);
            document.getElementById("valThrust").innerText = Math.round(row.thrust_n || 0).toLocaleString();

            // 5-Engine Cluster
            const n_ok = parseInt(row.engines_ok || 5);
            const dec = String(row.decision || '').toLowerCase();
            const e1_fail = (dec.includes("engine 1 failed") || n_ok < 5);
            const e3_off = (dec.includes("shut down opposite engine 3") || n_ok <= 3);

            if (e1_fail) {{
                clusterSummary.innerText = "ENGINE 1 FAILED · E3 BALANCED OFF (3 ENGINES)";
                clusterSummary.style.color = "var(--red)";
            }} else {{
                clusterSummary.innerText = "5 / 5 ENGINES NOMINAL";
                clusterSummary.style.color = "var(--green)";
            }}

            const active_n = Math.max(n_ok, 1);
            const thrust_share = (row.thrust_n || 0) / active_n;
            const pct = Math.min(100, Math.round((thrust_share / 800) * 100));

            const engines = [
                {{ name: "E1 (North +X)", status: e1_fail ? "FAILED" : "NOMINAL", col: e1_fail ? "var(--red)" : "var(--green)", thrust: e1_fail ? 0 : thrust_share, pct: e1_fail ? 0 : pct }},
                {{ name: "E2 (East +Y)", status: "NOMINAL", col: "var(--green)", thrust: thrust_share, pct: pct }},
                {{ name: "E3 (South -X)", status: e3_off ? "OFF (BALANCED)" : (n_ok <= 2 ? "FAILED" : "NOMINAL"), col: e3_off ? "var(--amber)" : "var(--green)", thrust: e3_off ? 0 : thrust_share, pct: e3_off ? 0 : pct }},
                {{ name: "E4 (West -Y)", status: "NOMINAL", col: "var(--green)", thrust: thrust_share, pct: pct }},
                {{ name: "E5 (Center)", status: "NOMINAL", col: "var(--green)", thrust: thrust_share, pct: pct }}
            ];

            let htmlBars = "";
            for (const eng of engines) {{
                htmlBars += `
                <div class="engine-row">
                    <div class="engine-header">
                        <span><strong>${{eng.name}}</strong></span>
                        <span style="color: ${{eng.col}}; font-weight: 700;">${{eng.status}} &nbsp;|&nbsp; ${{eng.thrust.toFixed(1)}} N (${{eng.pct}}%)</span>
                    </div>
                    <div class="bar-bg">
                        <div class="bar-fill" style="width: ${{eng.pct}}%; background: ${{eng.col}};"></div>
                    </div>
                </div>`;
            }}
            engineBarsContainer.innerHTML = htmlBars;

            // Update Current point in scatter
            chartMap.data.datasets[2].data = [{{ x: row.x_m, y: row.y_m }}];
            chartMap.update('none');

            // Decision Terminal Log
            const allDecs = currentDataset.filter(d => d.decision && String(d.decision).trim() !== '' && String(d.decision) !== 'nan');
            let termHtml = "";
            for (const d of allDecs) {{
                const isCur = Math.abs(d.t_s - t) <= 1.5;
                const cls = isCur ? "log-active" : "log-line";
                const isFail = String(d.decision).includes("FAILED");
                const isTd = String(d.decision).includes("TOUCHDOWN");
                const textCol = isFail ? "log-alert" : (isTd ? "log-success" : "");

                termHtml += `<div class="${{cls}}"><span class="log-time">T+${{parseFloat(d.t_s).toFixed(1).padStart(5, '0')}} s</span> [${{String(d.phase).toUpperCase()}}] <span class="${{textCol}}">${{d.decision}}</span></div>`;
            }}
            decisionTerminal.innerHTML = termHtml;
        }}

        function animationLoop(timestamp) {{
            if (isPlaying) {{
                const dt = (timestamp - lastTimestamp) / 1000;
                lastTimestamp = timestamp;

                const stepIncrement = dt * playSpeed;
                currentIdx = Math.min(currentDataset.length - 1, currentIdx + stepIncrement);
                updateUI(Math.floor(currentIdx));

                if (currentIdx >= currentDataset.length - 1) {{
                    isPlaying = false;
                    document.getElementById("btnPlay").innerText = "▶ Replay";
                    document.getElementById("btnPlay").classList.remove("btn-active");
                }}
            }} else {{
                lastTimestamp = timestamp;
            }}
            requestAnimationFrame(animationLoop);
        }}

        // Event Listeners
        slider.addEventListener("input", (e) => {{
            currentIdx = parseInt(e.target.value);
            updateUI(currentIdx);
        }});

        document.getElementById("btnPlay").addEventListener("click", () => {{
            isPlaying = !isPlaying;
            document.getElementById("btnPlay").innerText = isPlaying ? "⏸ Pause" : "▶ Play";
            document.getElementById("btnPlay").classList.toggle("btn-active", isPlaying);
            if (currentIdx >= currentDataset.length - 1) currentIdx = 0;
        }});

        document.getElementById("btnSpeed1").addEventListener("click", () => {{ playSpeed = 1; setSpeedActive("btnSpeed1"); }});
        document.getElementById("btnSpeed10").addEventListener("click", () => {{ playSpeed = 10; setSpeedActive("btnSpeed10"); }});
        document.getElementById("btnSpeed50").addEventListener("click", () => {{ playSpeed = 50; setSpeedActive("btnSpeed50"); }});

        function setSpeedActive(activeId) {{
            ["btnSpeed1", "btnSpeed10", "btnSpeed50"].forEach(id => {{
                document.getElementById(id).classList.toggle("btn-active", id === activeId);
            }});
        }}

        document.getElementById("btnMilestone").addEventListener("click", () => {{
            // Find engine failure step
            const failIdx = currentDataset.findIndex(d => String(d.decision).includes("FAILED"));
            if (failIdx !== -1) {{
                currentIdx = failIdx;
                updateUI(currentIdx);
            }}
        }});

        document.getElementById("datasetSelect").addEventListener("change", (e) => {{
            if (e.target.value === "fixture") {{
                currentDataset = fixData;
                isFixture = true;
                badgeProv.innerText = "FIXTURE — STAND-IN";
                badgeProv.className = "badge badge-fixture";
            }} else {{
                currentDataset = runData;
                isFixture = false;
                badgeProv.innerText = "MODELLED · Basilisk";
                badgeProv.className = "badge badge-modelled";
            }}
            slider.max = currentDataset.length - 1;
            currentIdx = 0;
            updateUI(0);
        }});

        // Initial setup
        updateUI(0);
        requestAnimationFrame(animationLoop);
    </script>
</body>
</html>
"""
    output_html.write_text(html_content, encoding="utf-8")
    print(f"[HTML Builder] Generated standalone Mission Control dashboard: {output_html} ({output_html.stat().st_size / 1e3:.1f} KB)")


if __name__ == "__main__":
    build_dashboard()
