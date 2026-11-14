---
title: "Simulation Team Handbook — Basilisk, Vizard, Mission Control"
subtitle: "Adinfinitium · for Tanush and Arnav · everything you need, in one place"
date: "v1 · Sat 14 Nov 2026"
---

# 0. Read this first (5 minutes)

**You don't need to open Jira.** Every task is written out in full below. The task IDs
(KAN-41 and so on) are only used to name your git branches.

**Your job in one sentence:** take what the AI swarm decides and fly it in **Basilisk**, a real
spacecraft simulator. Then show it in **Vizard** (3D) and on the **mission-control window**. That
gives the judges proof that it isn't just our own toy simulator.

**Good news: the hardest Basilisk parts already run.** Imok tested them with Basilisk 2.12.2:

| Starter (already in the repo) | Result when run |
|---|---|
| `basilisk_mods/scenario_orbit_release.py` | 100 km polar orbit (117.8 min period) → release → −19.5 m/s deorbit burn → 15.00 km PDI at 1,692 m/s. Writes `pdi_state.json`, a plot and a Vizard file |
| `basilisk_mods/scenario_descent.py` | 5 × 800 N engines + fuel tank + attitude control + classic guidance. Lands at 1.2 m/s vertical, 0.02 m/s horizontal, 0.4° tilt, 0.2 m from target. Writes a telemetry CSV and a Vizard file |
| `scenario_descent.py --engine-out-at 20` | Engine 1 fails, the opposite engine is shut down for balance, and it still lands within limits |
| `basilisk_mods/lunar_terrain.py` | Height/slope lookup on a tile, map projection, OBJ mesh export for Vizard |
| `tests/fixtures/telemetry_basilisk_engine_out.csv` | A **real** Basilisk telemetry file, so the mission-control window can be built **now** |

You **extend** these. You don't start from a blank page.

## Rules (your AI agent reads these automatically from `AGENTS.md`)
1. **Never commit to `main`.** Each task gets its own branch: `tanush/KAN-42-descent`, `arnav/KAN-48-mission-control`.
2. **No C++.** Basilisk modules are written in **Python** (template: `basilisk_mods/py_module_template.py`).
3. **No invented numbers.** Masses, thrust and limits come from `config/mission.yaml`.
4. **Label everything:** observed / modelled / generated / unknown. Basilisk output is **modelled**.
5. **Don't tune results to look good.** If Basilisk and the JAX simulator disagree, report the difference honestly. That *is* the validation.
6. **Big files never go in git** (`runs/`, `data/`, videos). They travel by pen drive.
7. **Stuck for more than 30 minutes?** Message Imok with: what you ran, the full error, and what you expected.

## Deadlines (IST)
| When | What you must have |
|---|---|
| **Sat 21:00, Checkpoint 1** | Tanush: orbit → release → descent runs end to end. Arnav: one Vizard replay opens, and the mission-control window plays a telemetry CSV |
| Sun 12:00, cut rule | Anything not working gets swapped for its simple version |
| Sun 17:00, code freeze | Only bug fixes, video and submission after this |
| Sun 22:00 | Submit |

# 1. One-time setup (≈ 45 min, do it together on a call)

## 1.1 Linux shell
Basilisk works best on Linux. On Windows use **WSL2 Ubuntu 24.04** (the same steps as the 4090 PC,
`docs/plan/02_4090_SETUP_AND_PENDRIVE.md`, Part B). Open the "Ubuntu" app for every command below.

## 1.2 Get the code
```bash
sudo apt update && sudo apt install -y git python3-venv python3-pip
git clone https://github.com/Imok282/Adinfinitium.git ~/adinfinitium
cd ~/adinfinitium
python3 -m venv ~/venvs/adi-bsk
source ~/venvs/adi-bsk/bin/activate            # do this in every new terminal
pip install -U pip
pip install -e ".[basilisk,apps,dev]"          # installs bsk (Basilisk), streamlit, pytest, jax (CPU)
```

## 1.3 Check it works (all must pass)
```bash
python -c "from Basilisk.utilities import SimulationBaseClass; print('basilisk ok')"
python -m contracts.mission                            # prints "mission.yaml OK"
python -m data_tools.make_demo_tile                    # makes a test terrain tile (GENERATED)
python -m basilisk_mods.scenario_orbit_release         # prints PDI altitude 15.00 km
python -m basilisk_mods.scenario_descent               # prints "outcome": "ok"
pytest                                                 # all green
```
If `import Basilisk` fails: run `pip install bsk pytest` and try again. If it still fails, check your
Python version (3.11–3.13 work) and tell Imok.

## 1.4 Vizard (3D viewer, Windows app)
1. Download **Vizard for Windows** from the Basilisk Vizard download page: <https://avslab.github.io/basilisk/Vizard/VizardDownload.html>. Unzip it to the Desktop.
2. Start Vizard, click **Select**, and open a Basilisk `.bin` file. From Windows, your WSL files are at
   `\\wsl$\Ubuntu\home\<your-linux-user>\adinfinitium\runs\basilisk\_VizFiles\`.
3. Open `orbit_release_UnityViz.bin` and `descent_demo_UnityViz.bin` (made by step 1.3). Use the GUI to switch cameras.

## 1.5 Your AI agent
Open Claude Code / Codex / Codebuff **inside `~/adinfinitium`**. It reads `AGENTS.md` and `CLAUDE.md` by itself.
For each task below, paste the **"Prompt for your agent"** box, then ask it to **explain every step**.
Check every number it writes against this handbook.

## 1.6 Git in 6 commands
```bash
git checkout main && git pull                      # get latest
git checkout -b tanush/KAN-42-descent              # new branch for a task
# ... work, run pytest ...
git add -A && git commit -m "KAN-42: terrain touchdown"
git push -u origin tanush/KAN-42-descent           # then open a Pull Request on GitHub
```
Ask Imok or Nimansh to merge your pull request once `pytest` is green.

# 2. Basilisk in 10 minutes

| Concept | What it means | Where you see it |
|---|---|---|
| **Simulation, process, task** | A task runs its modules every `dt` seconds. We use `dynTask` (physics, 0.01–5 s) and `fswTask` (guidance, 0.2 s) | `bsk_common.new_sim({"dynTask": 0.01, "fswTask": 0.2})` |
| **Module** | One piece of the simulation (spacecraft, thrusters, fuel tank, guidance…) | `sim.AddModelToTask("dynTask", module)` |
| **Message** | How modules talk. An output message is *subscribed to* by an input | `thr.cmdsInMsg.subscribeTo(guid.thrOnTimeOutMsg)` |
| **Python module** | Your own module: subclass `sysModel.SysModel`, write `Reset()` and `UpdateState()` | `py_module_template.py`, `DescentGuidance` |
| **Recorder** | Saves a message every step so you can plot it | `rec = sc.scStateOutMsg.recorder()` |
| **Vizard file** | `vizSupport.enableUnityVisualization(..., saveFile=...)` writes a `.bin` that Vizard plays | both scenarios |

**Frames (most bugs come from mixing these):**

- **N**: Moon-centred inertial, metres. In the starters the Moon is a non-rotating sphere (1737.4 km).
- **B**: lander body. +z_B points up, and the engines push along +z_B.
- **Local target frame**: east, north, up, in metres from the landing target. Telemetry `x_m`, `y_m` and `alt_m` use this.
- **Tile frame**: x east, y north, origin at the tile centre (polar-stereographic). Terrain lookups use this.

**Things we learned by testing (so you don't have to):**

- **Throttle = pulse-width.** Each 0.2 s the guidance asks every engine to fire for `throttle × 0.2 s`. The physics step **must be small (0.01 s)**. At 0.05 s the engines delivered only ~37% of the command and the lander crashed.
- **Engine-out needs balance.** The outer engines are canted 5°, so losing one pushes the lander sideways (it drifted 112 m and touched down at 7 m/s). The fix, like real landers: shut down the opposite engine (`OPPOSITE` map in `lander_descent.py`).
- **Last 10 m: stop chasing the target.** Only cancel the drift and keep the tilt ≤ 15°. Otherwise it touches down tilted 33° and sliding at 0.9 m/s.
- `unitTestSupport` needs `pytest` installed. Use `simHelpers.EigenVector3d2np` (the old helper is deprecated).
- `tank.r_TB_B = ...` is deprecated, so use `tank.setR_TB_B([...])`.

# 3. Tanush's tasks (in this order)

| # | Task | Branch | Needs | Time |
|---|---|---|---|---|
| T1 | KAN-41 Orbit → release → deorbit | `tanush/KAN-41-orbit` | nothing (starter ready) | 1 h |
| T2 | KAN-42 Powered descent on real terrain + engine-out | `tanush/KAN-42-descent` | Arnav's terrain (A2) | 3 h |
| T3 | KAN-38 Site library `sites/sites.json` | `tanush/KAN-38-sites` | web research | 2 h |
| T4 | KAN-39 Ice-target layers | `tanush/KAN-39-ice` | data downloads | 3 h |
| T5 | KAN-40 Chandrayaan-3 replay | `tanush/KAN-40-ch3` | Imok's light field | 2 h |
| T6 | KAN-43 Re-fly swarm champions | `tanush/KAN-43-refly` | Imok's champions (Sun AM) | 3 h |
| T7 | KAN-50 Submission page | `tanush/KAN-50-submission` | everything (Sun PM) | 2 h |

## T1 · KAN-41 · Orbit → release → deorbit → PDI
**Goal:** a believable start to the mission in Basilisk, saved for the descent and for Vizard.
**Already done by the starter:** everything except the plot check and the "propulsion module after release" visual.

Steps:

1. Run `python -m basilisk_mods.scenario_orbit_release` and open `runs/basilisk/orbit_altitude.png`.
2. Open the `.bin` in Vizard (setup 1.4) and check the orbit looks polar and drops to 15 km.
3. Optional, for the video: simulate the propulsion module as a second `Spacecraft` after release, so both objects appear in Vizard.
4. Move `PROPULSION_MODULE_MASS_KG` (900 kg) into `config/mission.yaml` under `lander:` as `propulsion_module_mass_kg`, and add it to `contracts/mission.py` (model + test).

**Done when:** the script prints PDI ≈ 15 km, the plot is saved, and Vizard shows the orbit.

> **Prompt for your agent:** "Read AGENTS.md and basilisk_mods/scenario_orbit_release.py. Move PROPULSION_MODULE_MASS_KG into config/mission.yaml (lander.propulsion_module_mass_kg) and contracts/mission.py with a test. Then add the propulsion module as a second Basilisk Spacecraft that continues in the 100 km orbit after release, so both appear in the Vizard file. Keep everything else the same. Run the scenario and pytest and show me the output. Explain each change."

## T2 · KAN-42 · Powered descent on real terrain + engine-out + telemetry
**Starter:** `lander_descent.py` + `scenario_descent.py` (already lands on flat ground, nominal and engine-out).

Steps:

1. **Terrain.** With Arnav (A2), set `guidance.ground_height_fn` to a function that returns the ground height under the lander. Use `Terrain.ground_height(x, y)` from `lunar_terrain.py`, where `x`/`y` are the lander's east/north offsets from the target plus the target's tile position. Use the same function in the touchdown check, and pass `slope_deg = terrain.slope(x, y)` to `touchdown_report`.
2. **Target on a real tile.** Choose a target in the clear middle of `demo_craters` (and later a real LOLA tile). Pass its height as `target_point_N(height_m=...)`.
3. **Engine-out demo.** Run `--engine-out-at 5`, `20` and `60` and keep all three telemetry files for the video.
4. **Telemetry is already in contract format** (`runs/basilisk/telemetry_<id>.csv`). Don't change the columns. Arnav's window reads them.
5. **(Stretch) start from PDI.** Read `runs/basilisk/pdi_state.json` (15 km, ~1.7 km/s) and add a **braking phase** before the existing law. Hint: the current time-to-go estimate uses vertical speed, which is ~0 at PDI, so for braking use `tgo ≈ |v| / (0.9 × max_thrust / mass)` and aim at a point ~500 km downrange. If this isn't working by **Sun 12:00**, keep the descent starting at 2 km (the same as the swarm) and show orbit → PDI as a separate clip. That's the cut rule.
6. Save a Vizard file for each run (default on).

**Done when:** it lands within limits on the terrain tile with all 5 engines, an engine-out run is logged honestly, and the CSV opens in the mission-control window.
**Don't:** change touchdown limits to make it pass, or write C++.

> **Prompt for your agent:** "Read AGENTS.md, basilisk_mods/lander_descent.py, basilisk_mods/scenario_descent.py and basilisk_mods/lunar_terrain.py. Make the descent land on a terrain tile: add a --tile option (default data/tiles/demo_craters.npz) and a --target-x/--target-y option in tile metres. Use lunar_terrain.Terrain for ground height in DescentGuidance.ground_height_fn and in the touchdown check, and pass the terrain slope to touchdown_report. Keep the telemetry CSV columns exactly as contracts/runs.py TELEMETRY_COLUMNS. Add a pytest that lands on the demo tile. Run nominal and --engine-out-at 20, and show me the touchdown reports. Explain each step and don't change any limits in config/mission.yaml."

## T3 · KAN-38 · Site library `sites/sites.json`
**Goal:** at least 15 real landing sites with official sources. The challenge brief asks for past Apollo missions, future CLPS targets, other commercial missions and other countries' programs.

Include:

- Apollo 11, 12, 14, 15, 16, 17
- Chandrayaan-3 (Shiv Shakti point), Chang'e 3/4/5/6, SLIM
- Intuitive Machines IM-1, IM-2 (near Mons Mouton), Firefly Blue Ghost 1, and any later confirmed CLPS landing
- NASA Artemis III candidate **regions**. Use NASA's latest list, give a centre point and mark it `"region"`.
- Shackleton rim, connecting ridge, de Gerlache rim

Format: copy `sites/sites.example.json`. Every entry has `id` (snake_case), `name`, `lat_deg` (south is negative), `lon_deg` (east), `source` (the URL), `provenance: "observed"` (for a region centre, use `"modelled"`) and `notes`. Validate with `python -m data_tools.validate_formats sites/sites.json`.

**Done when:** 15+ sites, every one with a working official URL (NASA, ISRO, JAXA, CNSA, the company, or a paper), and Imok or Nimansh have spot-checked 3 of them.
**Don't:** take coordinates from memory or blogs, or mark a region as a landing point.

> **Prompt for your agent (browser AI is fine):** "Find official coordinates (NASA/ISRO/JAXA/CNSA/company press release or peer-reviewed paper) for these lunar landing sites: [paste the list]. For each give lat (south negative), lon (east), and the exact source URL. If sources disagree, give both. Don't guess. Output JSON matching this example: [paste sites.example.json]."

## T4 · KAN-39 · Ice-target layers
**Goal:** `data_tools/ice_layers.py` → `data/ice/<region>_ice.npz` (same grid as the tiles) + `data/ice/psr_outlines.geojson` + `data/ice/README.md`.

Layers, in order (skip one if you can't find it within ~1 h, and write "future" in the README):

1. **Permanently shadowed regions:** `LPSR_80S_20MPP_ADJ_1km2` from <https://pgda.gsfc.nasa.gov/products/90>, rasterised onto each tile grid, plus GeoJSON outlines.
2. **Diviner max temperature:** from the PDS Geosciences node. `cold_trap = Tmax < 110 K` (state that threshold as an assumption).
3. **Neutron hydrogen:** LRO LEND or Lunar Prospector, coarse. Treat it as a "likelihood".
4. **M3 surface-ice detections:** Li et al. 2018 (PNAS), if downloadable.

Then compute `ice_score` (weights documented in the README), and pick candidate ice targets = the highest scores within ~300 m of sunlit ground (the rover only drives ~1 cm/s). Save a preview PNG per region.
**Don't:** say "ice is here" (say "ice evidence" or "ice-favourable"), or mix map projections.

> **Prompt for your agent:** "Read AGENTS.md, contracts/tiles.py and docs/FORMATS.md. Write data_tools/ice_layers.py that loads a tile from data/tiles/<region>.npz and rasterises the LOLA PSR shapefile (path as argument) onto the same polar-stereographic grid, then (optionally) resamples a Diviner Tmax GeoTIFF onto the grid and computes cold_trap = Tmax < 110 K. Save data/ice/<region>_ice.npz with a Meta (provenance observed for PSR/Diviner, modelled for derived layers) and a preview PNG. Add a test using a tiny synthetic shapefile. Explain each step."

## T5 · KAN-40 · Chandrayaan-3 replay
**Goal:** run Vikram's real site and dates through our tools, as a strong story for the judges.

1. Verify from **ISRO** sources and save the URLs: landing 23 Aug 2023 ~12:33 UTC, Shiv Shakti point ~69.37°S 32.32°E, and the rover/lander sleep in early September 2023 (they did not wake after the lunar night).
2. Ask Imok for the light field (Sun/Earth over the local horizon) for a tile around the site, 20 Aug – 10 Oct 2023.
3. Plot the Sun elevation and sunlight timeline, sunset time, night length and Earth visibility.
4. Compare our predicted sunset with when ISRO put Vikram and Pragyan to sleep.
5. Write `docs/CHANDRAYAAN3_REPLAY.md`, two plots and a 3-sentence summary, and record a short screen clip.

**Don't:** criticise ISRO. Frame it as "what conditions were" and "what our tool shows". Every fact needs a source.

## T6 · KAN-43 · Re-fly swarm champions in Basilisk (Sunday morning)
**Input:** `runs/<run>/champion_XXX.json` from Imok (format: `contracts/runs.py → Champion`).

- `initial_state.pos_m` / `vel_m_s` are in the **tile frame** (x east, y north, z = height on the tile datum), metres.
- `controls` is a list of `{t_s, thrust_n:[x,y,z]}` in the same frame, every 0.1 s.

Steps:

1. Write `basilisk_mods/refly_champion.py --champion <file>`.
2. Convert the initial state: `r0 = target + x·E + y·N + (z − ground_at_target)·U`, and likewise for velocity, using `local_frame()`.
3. Write a `ReplayGuidance` Python module (copy `DescentGuidance`) that **doesn't compute guidance**. It reads the thrust vector for the current time from the log and outputs (a) the attitude reference along that vector and (b) on-times = |thrust| / (healthy engines × 800 N) × 0.2 s.
4. Record the touchdown speeds, position, fuel and pass/fail. Write `runs/basilisk/compare_<id>.json` and add a row to `docs/VALIDATION.md`: JAX vs Basilisk.
5. Re-fly 3 champions (one with engine-out) and save a Vizard file for each.

**Expect differences:** JAX is 3-DOF (thrust points instantly), while Basilisk is 6-DOF (attitude takes time). **Report them as they are. Don't tune.**

## T7 · KAN-50 · Submission page (Sunday evening, decisions already made)
- **Demo link:** a 30-second video with **English subtitles**, on YouTube or Google Drive, publicly viewable.
- **Final project link:** a hub that links the hosted web app, the GitHub repo and the Google Drive folder. The repo goes **public on Sunday** before submitting. **Imok owns the Drive and tests every link in an incognito window.**
- Fields: name, summary, demo link, final link, detailed description, NASA data, other data, **use of AI** (we used Claude/Codex for code; any AI image or video must carry a visible "AI-generated" watermark, and no NASA logos may appear in AI-generated content).
- Credit the data (LOLA/PGDA, SPICE/NAIF, LRO Diviner/LEND, M3) and tools (Basilisk, Vizard, TensorNEAT, JAX, Streamlit).
- Team read-through **Sun 21:00**. "Submit for Judging" is final.

# 4. Arnav's tasks (in this order)

| # | Task | Branch | Needs | Time |
|---|---|---|---|---|
| A1 | KAN-48 Mission-control window | `arnav/KAN-48-mission-control` | fixture CSV (ready) | 3 h |
| A2 | KAN-44 Terrain module + OBJ | `arnav/KAN-44-terrain` | starter ready | 1.5 h |
| A3 | KAN-47 Vizard: terrain, models, clips | `arnav/KAN-47-vizard` | A2, Tanush's runs | 3 h + recording |
| A4 | KAN-46 Power + comms | `arnav/KAN-46-power` | Imok's light field (constant until then) | 2.5 h |
| A5 | KAN-45 Rover | `arnav/KAN-45-rover` | A2, A4 | 3 h |

## A1 · KAN-48 · Mission-control window (Streamlit, port 8502)
**Run:** `streamlit run mission_control/app.py --server.port 8502`
**Input now:** `tests/fixtures/telemetry_basilisk_engine_out.csv`, a real Basilisk engine-out landing. Later, any `runs/basilisk/telemetry_<id>.csv`.
Columns (fixed, from `contracts/runs.py`): `t_s, phase, x_m, y_m, alt_m, vx_m_s, vy_m_s, vz_m_s, mass_kg, fuel_kg, thrust_n, engines_ok, battery_wh, solar_w, earth_visible, decision`.

Layout (dark mission-control look):

1. **Header:** mission phase + mission clock + a provenance badge ("MODELLED · Basilisk"; show "FIXTURE" if the file is from `tests/fixtures`).
2. **Flight:** altitude, vertical and horizontal speed, fuel left, total thrust, and 5 engine indicators (red = off). `engines_ok` 5 → 3 means one failed and one was balanced off. Show which ones from the decision text.
3. **Power and comms:** battery, solar input, Earth link, **countdowns to sunset and Earthset**. Show "—" while the columns are empty; they fill in after A4.
4. **Decision log:** timestamped lines from `decision` (e.g. `21.0 s engine 1 FAILED; shut down opposite engine 3 for balance -> 3 engines`).
5. **Replay controls:** play / pause / speed (1×, 10×, 100×) / scrub slider.
6. **File picker:** any CSV in `runs/basilisk/` plus the fixture.

**Rules:** this window **only reads and displays files**. No physics here. Read files with `contracts.runs.read_telemetry`.

**Done when:** it plays the fixture and a fresh run from Tanush, and you've made a screen recording.

> **Prompt for your agent:** "Read AGENTS.md, contracts/runs.py (TELEMETRY_COLUMNS, read_telemetry) and tests/fixtures/telemetry_basilisk_engine_out.csv. Build mission_control/app.py, a Streamlit app (port 8502) with a dark mission-control look: header with phase, mission clock and a provenance badge (FIXTURE if the file is under tests/fixtures, else MODELLED · Basilisk); flight panel (altitude, vertical/horizontal speed, fuel, total thrust, 5 engine lights from engines_ok and the decision text); power and comms panel (battery, solar, Earth link, countdowns, showing '—' when empty); decision log; replay controls (play/pause, 1x/10x/100x, scrub slider); file picker over runs/basilisk/*.csv plus the fixture. Use plotly for charts. Only read files, no physics. Add a small pytest that loads the fixture through the same function the app uses. Explain each step."

## A2 · KAN-44 · Terrain module + OBJ for Vizard
**Starter:** `basilisk_mods/lunar_terrain.py` (lookup, projection and OBJ export are already tested).

1. Run `python -m basilisk_mods.lunar_terrain data/tiles/demo_craters.npz` → `vizard/terrain_demo_craters.obj`. Open it in Blender or an online OBJ viewer and check that craters look like craters.
2. **Verify the projection** (important): ask Imok for 3 known points (lat, lon → expected x, y from the LOLA label) and add them as a test. If the sign or axis convention differs, fix `ps_from_latlon` and say so in the commit.
3. With Tanush, plug `Terrain.ground_height` and `Terrain.slope` into the descent (T2 step 1). Agree the function names.
4. Once Imok's real tiles exist, export OBJs for the demo regions with `--step 2` or `--step 4` to keep files small.

**Don't:** mix metres and kilometres (every function says its units), or use vertical exaggeration without a visible "vertical exaggeration ×N" label in the video.

## A3 · KAN-47 · Vizard: terrain, models, 3 clips
1. Vizard is installed (setup 1.4). Open Tanush's `.bin` files.
2. **Terrain in Vizard:** Basilisk can import an OBJ at runtime with `vizSupport.createCustomModel(viz, modelPath=..., simBodiesToModify=[...], offset=..., rotation=..., scale=...)`. One approach: add a static "terrain" Spacecraft at the landing target (no gravity added, zero velocity) and apply the terrain OBJ to it. **This hasn't been tested yet.** If it looks wrong after ~1 h, record the terrain fly-over in Blender instead and show Vizard for orbit and descent.
3. **Models:** make simple **original** OBJs in Blender. Lander: box + 4 legs + 5 nozzles. Rover: box + 6 wheels + panel. Apply them with `createCustomModel` to `"lander"` and the rover. No copied or branded models.
4. Higher-quality custom models use Unity Addressables bundles. These must be built with the same Unity version as your Vizard (see File → About Vizard). **Only on Sunday, and only if time allows.**
5. **Record 3 clips (1080p screen recording):** (a) orbit → release, (b) descent with engine-out + touchdown, (c) rover to the ice edge and back at sunset (speed up playback, not the rover). Copy them to the pen drive under `video_assets/`.

## A4 · KAN-46 · Power + comms (Sun/Earth from our data)
**Goal:** `basilisk_mods/power_comms.py` sets the lander's **solar input** and **Earth link yes/no** every step from our light data, and tracks the battery over ~30 days.

1. **Input:** `data/light/<region>_<date>.npz` (`contracts/light.py`: `sun_fraction`, `sun_elev_deg`, `earth_elev_deg` over time). Earth link = `earth_elev_deg > 0`. **Until Imok delivers it**, use a clearly labelled synthetic day/night cycle (`provenance: "generated"`) so you can build the rest.
2. Power in = `panel_area_m2 × solar_constant_w_m2 × panel_efficiency × sun_fraction × cos(incidence)`. Constants are in `config/mission.yaml → power`. Assume near-vertical panels (low polar Sun). Check Basilisk's `simpleSolarPanel` / `simpleBattery` / `simplePowerSink` modules first and reuse them if they fit. Otherwise write a Python module.
3. Loads: avionics (`survival_load_w`), heaters (higher at night), radio when the link is up, rover charging.
4. Battery over ~30 days. Night survival = battery > 0 until sunrise. **Label: simplified thermal model.**
5. Fill the telemetry columns `battery_wh`, `solar_w`, `earth_visible`, and put countdowns in `decision` (e.g. `sunset in 3d 4h`).

**Done when:** a 30-day run prints sunrise/sunset, Earth windows and the battery curve, and the numbers match the Navigator for the same site and date (check with Nimansh).
**Don't:** invent Sun times. They must come from our SPICE/light data.

## A5 · KAN-45 · Rover on terrain
**Goal:** `basilisk_mods/rover.py` + `scenario_rover.py`: a ~25 kg rover drives from the lander through waypoints (ice targets) and back.

1. State: tile x, y (height from `Terrain`), heading, battery.
2. Motion: kinematic, 0.01 m/s (`rover.speed_m_s`). Stop if the slope exceeds `rover.max_slope_deg`. Follow waypoints from a list (later from Tanush's ice targets).
3. Power: 50 W panel × `sun_fraction` at its position (constant until A4/Imok are ready). Drive and standby power are design assumptions; add them to `config/mission.yaml` with a comment.
4. Comms: the rover can only send data with **line of sight to the lander**. Sample terrain heights along the line and block the link if the ground rises above the sight line.
5. Time step 10–60 s. Log every minute to `runs/basilisk/rover_<id>.csv` with columns `t_s, x_m, y_m, height_m, heading_deg, battery_wh, sun_fraction, link_to_lander, activity`. **First add `ROVER_COLUMNS` to `contracts/runs.py` with a test.**
6. In Vizard (A3), show it as a small body moving on the terrain.

**Done when:** it reaches 2 waypoints and returns, logging battery and link, and it respects the speed and slope limits (print the checks).
**Don't:** make it faster for the video. Speed up playback instead.

# 5. Who gives you what (hand-offs)

| You need | From | File | When |
|---|---|---|---|
| Terrain tiles (real LOLA) | Imok | `data/tiles/<region>.npz` (pen drive) | Sat afternoon; use `demo_craters` until then |
| Light field (Sun/Earth) | Imok | `data/light/<region>_<date>.npz` | Sat evening |
| Swarm champions | Imok | `runs/<run>/champion_XXX.json` | Sun morning |
| Sites | Tanush → everyone | `sites/sites.json` | Sat |
| Telemetry | Tanush → Arnav | `runs/basilisk/telemetry_<id>.csv` | now (starter) |
| Ground height function | Arnav → Tanush | `lunar_terrain.Terrain` | Sat |
| Vizard clips | Arnav → Imok (video) | pen drive `video_assets/` | Sun 15:00 |

# 6. Troubleshooting
| Problem | Fix |
|---|---|
| `ModuleNotFoundError: contracts` | Run from `~/adinfinitium` with the venv active, and `pip install -e .` |
| `ModuleNotFoundError: pytest` when importing Basilisk utilities | `pip install pytest` |
| Lander crashes at high speed, engines weak | dynTask step too big. Keep `dyn_dt = 0.01` |
| Lander drifts sideways after engine-out | Make sure the opposite engine is shut down (`OPPOSITE`) |
| Vizard shows nothing | Open the `_UnityViz.bin` from `runs/basilisk/_VizFiles/`, and check that the script ran without `--no-viz` |
| Streamlit page blank | Check the terminal for the Python error; run `python -c "from contracts.runs import read_telemetry; print(len(read_telemetry('tests/fixtures/telemetry_basilisk_engine_out.csv')))"` |
| Numbers look "too good" | Re-check limits and units. Never change limits to pass |

# 7. Honesty checklist for anything you show
- [ ] Every screen shows provenance (MODELLED · Basilisk / GENERATED / FIXTURE)
- [ ] Simplifications named: ideal attitude torque (not RCS thrusters), non-rotating Moon in the starters, simplified thermal model
- [ ] Any vertical exaggeration labelled
- [ ] No AI-generated imagery without a visible "AI-generated" watermark; no NASA logos in generated content
- [ ] JAX vs Basilisk differences reported, not tuned away
