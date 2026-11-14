<!-- Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in ui/index.html. -->
# Attaching a backend to the mission-control UI

The user interface in `lunar_ops/ui/` is a pure viewer. It draws whatever it is
sent. There are two ways to attach intelligence:

1. **Drive the UI** with any simulator: speak the `world` / `frame` messages below on `/ws/ui`.
2. **Drive the rover** with your AI model: connect to `/ws/agent`, receive observations, return actions.

```
 your AI model ──/ws/agent──►  lunar_ops.server  ──/ws/ui──►  browser UI
 (any language)  observation ▲   simulator + baseline   world, frame ▲  commands (abort, override)
                 action     ─┘
```

Start the reference backend with `python -m lunar_ops.server` and open
`http://127.0.0.1:8600`. If no backend is reachable the UI plays the recorded
sample in `ui/sample/` and says so in the top bar.

All numbers use SI units unless the field name says otherwise (`_deg`, `_wh`, `_w`).
Tile frame: `x` east, `y` north, metres from the tile centre; headings and
azimuths are degrees clockwise from `+y`; raster row 0 is the northern edge.

## 1. UI socket `/ws/ui`

Server to UI:

| `type` | When | Content |
|---|---|---|
| `world` | on connect and after reset | terrain rasters (`height_f32`, `slope_u8`, `psr_u8`, `ice_u8`, `hazard_u8` as base64, row-major), `rows`, `cols`, `mpp`, `half_x`, `half_y`, `targets[]`, `start`, `limits`, `sky`, `provenance` |
| `frame` | every tick | pose, battery, power, mode, `phase`, `reason`, `control` (`baseline`, `agent`, `operator`), `targets[].sampled`, `samples`, `events[]`, optional `path` (planned route), optional `lit_bits_b64` (packed illumination mask, sent when the Sun has moved) |
| `state` | on connect | `playing` |

`events[]` items are `{t_s, kind, msg}`. Kinds the UI colours: `decision`, `agent`,
`event`, `sample`, `abort`, `dead`. Messages must be **facts only** (what, when, why).

UI to server (`{"type":"cmd", ...}`): `play`, `pause`, `speed` (`value`), `reset`,
`abort`, `override` (`on`), `drive` (`v` 0..1, `omega` -1..1).

The exact field list is in `lunar_ops/protocol.py` (`world_message`, `FrameBuilder.frame`).


## 1b. Mission phases and vehicle fields

`frame.mission_phase` is one of `ORBIT`, `DEORBIT`, `DESCENT`, `LANDED`, `ROVER OPS`. The UI picks the 3D scene
from it: orbit scene for `ORBIT` / `DEORBIT`, surface scene for the rest. Include only the block that applies:

| Block | Phases | Fields |
|---|---|---|
| `orbit` | `ORBIT`, `DEORBIT` | `lat_deg`, `lon_deg`, `alt_km`, `speed_m_s`, `orbit_no` |
| `lander` | `DESCENT` | `x_m`, `y_m` (tile frame, metres), `alt_m` (above the landing point), `vx_m_s`, `vy_m_s`, `vz_m_s`, `mass_kg`, `fuel_kg`, `thrust_n`, `engines_ok` |
| rover fields (`pose`, `battery_*`, `targets`, ...) | `LANDED`, `ROVER OPS` | as in section 1 |

The `world` message carries `site: {lat_deg, lon_deg}` (landing region centre) for the orbit scene.
`lunar_ops/mission_timeline.py` shows a reference producer; the team's Basilisk telemetry CSV
(`contracts/runs.py`, `TELEMETRY_COLUMNS`) maps directly onto the `lander` block.

## 1c. Vehicle models and 3D

The mission-control page is **2D only**. All 3D (vehicle models, orbit, descent and surface views) belongs to
Basilisk / Vizard. The earlier Three.js page is kept, unserved, in `lunar_ops/ui_3d_legacy/`.

## 1d. Live telemetry from another producer (`/ws/ingest`)

A producer, for example a Basilisk bridge, connects to `/ws/ingest` and sends the same `world`, `frame` and `models`
messages as above. The server relays them to every UI and pauses its built-in simulator while the producer is
connected; when the producer disconnects the simulator restarts. Commands from the UI (play, abort, ...) are **not**
forwarded to the producer yet.

`GET /api/training` returns the tail of `runs/rover/train_log.jsonl` (if present) for the Training desk.

## 2. Agent socket `/ws/agent` (your AI model)

1. Connect. The server sends `hello` with the action schema, `decision_dt_s` and `world_url` (`GET /api/world` returns the maps).
2. For every decision period the server sends
   `{"type":"observation","step":N,"obs":{...}}`.
3. Reply within `agent_timeout_s` (2 s) with
   `{"type":"action","step":N,"v":0..1,"omega":-1..1,"mode":"drive|hold|sleep|drill","phase":"TRAVERSE","reason":"facts only"}`.
   `step` must echo the observation. Optional `{"type":"log","text":"..."}` lines appear in the decision log.
4. While connected the UI badge reads `CONTROL · AGENT`. If the agent is slow, the baseline
   policy acts for that step and the log says so. If the agent disconnects, the baseline resumes.
   Operator override and ABORT always win.

`obs` contains: `t_s`, `pose{x_m,y_m,heading_deg}`, `battery_wh`, `battery_frac`, `solar_w`, `load_w`,
`lit`, `earth_visible`, `in_psr`, `mode`, `slope_deg`, `hazard`, `ice_score`, `sun`, `targets[]`
(`id`, `x_m`, `y_m`, `ice_score`, `depth_m`, `sampled`, `dist_m`), `samples[]`, `alive`, `aborted`, `outcome`,
and an egocentric 15 x 15 `patch` (height, slope, hazard, ice score, lit, PSR; north up, 10 m spacing).

Minimal agent (Python):

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8600/ws/agent") as ws:
        print(json.loads(await ws.recv())["type"])          # hello
        async for raw in ws:
            m = json.loads(raw)
            if m["type"] == "observation":
                action = my_model(m["obs"])                 # your network goes here
                await ws.send(json.dumps({"type": "action", "step": m["step"], **action}))

asyncio.run(main())
```

## 3. In-process policy

Implement `lunar_ops.policies.Policy` (`reset(prior, cfg)`, `act(obs) -> Action`) and run
`python -m lunar_ops.server --policy mypkg.mymodule:MyPolicy`.

## 4. Provenance (required by the project rules)

Terrain is **GENERATED**, ice layers are **MODELLED** evidence, and the rover parameters in
`lunar_ops/config.py` are **ASSUMED**. The UI shows these labels permanently. A backend that
supplies real data should change the `provenance` map in its `world` message; the UI displays it.
Never describe a layer as showing where ice *is*; say *ice evidence*.


## 5. Ghost files (replay of recorded, simulated runs)

The **Ghosts** tab replays recorded attempts side by side: which one won, and where the others failed. Drop files on the
page (or use *Add files*) and they are checked, shown at once and stored in `runs/ghosts/` by the server
(`POST /api/ghosts/<name>` with the raw file, `GET /api/ghosts` to list, `GET /api/ghosts/<name>` to read).
Mission control only replays what a file contains: nothing is invented, tuned or repaired. A file with missing or wrong
fields is rejected with a list of what is wrong (HTTP 422) so the producer can fix it.

```json
{"kind": "rover" | "lander", "region": "lola5m_site23", "frame": "tile ENU metres, origin = tile centre, z up",
 "dt_s": 3600.0, "terrain_obj": "<path>", "models": {"rover": "rover.glb", "lander": "lander.glb"},
 "runs": [{"id": "...", "policy": "...", "outcome": "returned", "best": true, "fail_t_s": null,
           "t_s": [0.0, ...], "xyz_m": [[x, y, z], ...], "heading_deg": [...]}]}
```

Required: `kind`, `region`, `dt_s` (> 0), and per run `id` (unique), `policy`, `outcome`, `best` (boolean), `fail_t_s`
(number or `null`), `t_s` (non-decreasing), `xyz_m` (one `[x, y, z]` per `t_s`). `heading_deg` is optional, one value per
`t_s` when present. Known outcomes: `returned, reached_ice_only, died_battery, blocked, timeout, ok, hard_vertical,
hard_horizontal, steep_slope, hazard_cell, out_of_fuel, out_of_bounds`; other strings load with a warning and are drawn
as a failure. A run with `fail_t_s` is frozen there with its outcome written next to it. At most 12 runs are drawn by
default (always the best, and at least 2 of each failure type); *Show all runs* draws every run.
Open question for the producer: the direction convention of `heading_deg` (the page does not rotate markers by it).

Everything shown is MODELLED (simulated). The checks live in `lunar_ops/ghosts.py` (server) and `ui/ghosts.js` (page).

## 6. Site imagery

The **Imagery** tab draws the observed LROC mosaic of the site (`ui/assets/<site>/photo_1m.jpg`, 1 m/px, and the 2 m/px
context image) with the lander and rover on top. The tile photo is assumed to cover exactly the tile (x east, y north,
row 0 north). Where the photo is black (permanent shadow) the LOLA elevation hillshade is blended in, and the caption says so.

## 7. Third-party code

`ui/vendor/` holds MIT-licensed code copied from npm (see `ui/vendor/README.md`): OpenUI's browser bundle (the **Charts**
tab) and NumberFlow (rolling numbers). The **Colour / Black & white** switch in the top bar applies a greyscale filter to the whole page.
