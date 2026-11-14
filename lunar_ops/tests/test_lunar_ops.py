#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Tests for the lunar rover simulation, the protocol and the AI-agent socket."""

from __future__ import annotations

import base64
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lunar_ops.config import MissionConfig
from lunar_ops.env import RoverEnv, run_episode
from lunar_ops.protocol import FrameBuilder, world_message
from lunar_ops.rover import Action
from lunar_ops.server import create_app


@pytest.fixture(scope="module")
def env() -> RoverEnv:
    """One shared environment (building the horizon maps takes a few seconds)."""
    e = RoverEnv(MissionConfig(), seed=1)
    _ = e.world.horizons
    return e


def test_sites_are_inside_shadow_and_landing_is_not(env: RoverEnv) -> None:
    """Candidate sites lie in the PSR and the landing point does not."""
    w = env.world
    assert len(w.targets) >= 4
    assert all(w.psr_at(t["x_m"], t["y_m"]) for t in w.targets)
    assert not w.psr_at(w.start["x_m"], w.start["y_m"])


def test_sun_azimuth_wraps_once_per_lunar_day(env: RoverEnv) -> None:
    """The Sun returns to its start azimuth after one synodic period."""
    sky = env.cfg.sky
    a0 = env.world.sun_azimuth_deg(0.0)
    a1 = env.world.sun_azimuth_deg(sky.synodic_period_s)
    assert math.isclose(a0, a1, abs_tol=1e-6)


def test_action_from_dict_clamps_untrusted_input() -> None:
    """Remote agent input is clamped and unknown modes become hold."""
    a = Action.from_dict({"v": 9, "omega": -9, "mode": "warp", "reason": "x" * 999})
    assert a.v == 1.0 and a.omega == -1.0 and a.mode == "hold" and len(a.reason) <= 240


def test_battery_drains_in_shadow_at_hold_plus_heater() -> None:
    """Holding inside a PSR drains hold load plus heater power."""
    e = RoverEnv(MissionConfig(), seed=1)
    t = e.world.targets[0]
    st = e.rover.state
    st.x_m, st.y_m = t["x_m"], t["y_m"]
    e.rover._update_environment()
    assert st.in_psr and not st.lit
    before = st.battery_wh
    e.rover.step(Action(mode="hold"), 3600.0)  # [s] one hour
    rc = e.cfg.rover
    expected = (rc.load_hold_w + rc.heater_w) * 1.0  # [Wh] over one hour
    assert math.isclose(before - st.battery_wh, expected, rel_tol=0.02)


def test_abort_latches_safe_mode() -> None:
    """After an abort the rover stops and ignores drive commands."""
    e = RoverEnv(MissionConfig(), seed=1)
    e.rover.abort("test")
    x0 = e.rover.state.x_m
    e.rover.step(Action(v=1.0, mode="drive"), 600.0)
    assert e.rover.state.aborted and e.rover.state.x_m == x0
    assert e.rover.state.mode == "sleep"


def test_world_message_roundtrips_terrain(env: RoverEnv) -> None:
    """The base64 height raster decodes to the original terrain."""
    m = world_message(env)
    h = np.frombuffer(base64.b64decode(m["height_f32"]), dtype="<f4").reshape(m["rows"], m["cols"])
    assert np.array_equal(h, env.world.height)
    assert "GENERATED" in m["provenance"]["terrain"]


def test_illumination_mask_sent_once_then_only_when_sun_moves(env: RoverEnv) -> None:
    """Frames carry the packed lit mask only when the Sun azimuth changed enough."""
    fb = FrameBuilder(env, lit_step_deg=5.0)
    obs = env.observe(with_patch=False)
    assert "lit_bits_b64" in fb.frame(obs, None, "baseline")
    assert "lit_bits_b64" not in fb.frame(obs, None, "baseline")


def test_observation_patch_shape(env: RoverEnv) -> None:
    """The egocentric patch has the configured size for every channel."""
    p = env.observe()["patch"]
    n = env.cfg.patch_size
    for key in ("height_rel_m", "slope_deg", "hazard", "ice_score", "lit", "psr"):
        assert np.array(p[key]).shape == (n, n)


def test_baseline_reaches_shadow_and_takes_a_sample() -> None:
    """The baseline policy completes at least one sample within a day of simulated time."""
    res = run_episode(seed=1, max_decisions=int(86400.0 / 30.0))
    assert res["samples"] >= 1
    assert res["outcome"] in ("running", "complete")


def test_ai_agent_socket_takes_control_of_the_rover() -> None:
    """A fake AI model attached to /ws/agent drives the rover and the UI stream reports it."""
    app = create_app(seed=1, record=False)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ui") as ui:
            assert ui.receive_json()["type"] == "world"
            assert ui.receive_json()["type"] == "frame"
            ui.receive_json()  # state
            ui.send_json({"type": "cmd", "cmd": "speed", "value": 3000})
            with client.websocket_connect("/ws/agent") as agent:
                hello = agent.receive_json()
                assert hello["type"] == "hello" and hello["protocol"] == 1
                seen_agent = False
                answered = 0
                for _ in range(400):
                    # answer any pending observation, then read UI frames
                    try:
                        msg = agent.receive_json()
                    except Exception:  # noqa: BLE001
                        break
                    if msg["type"] == "observation":
                        agent.send_json({"type": "action", "step": msg["step"], "v": 0.0, "omega": 0.0,
                                         "mode": "hold", "phase": "AI-TEST", "reason": "fake model holds"})
                        answered += 1
                    if answered >= 3:
                        break
                assert answered >= 3
                for _ in range(100):
                    f = ui.receive_json()
                    if f.get("type") == "frame" and f["control"] == "agent":
                        seen_agent = True
                        assert f["phase"] == "AI-TEST"
                        break
                assert seen_agent


def test_keplerian_periapsis_speed_matches_the_basilisk_handbook() -> None:
    """The analytic deorbit ellipse reproduces the 1,692 m/s periapsis speed documented for Basilisk."""
    from lunar_ops.mission_timeline import speed_at_periapsis_m_s

    assert math.isclose(speed_at_periapsis_m_s(), 1692.0, abs_tol=2.0)


def test_orbit_frames_cover_orbit_then_deorbit_ending_at_15_km() -> None:
    """Orbit frames start at 100 km and the last frame is the 15 km periapsis."""
    from lunar_ops.mission_timeline import orbit_frames

    f = orbit_frames(-89.8, -20.0, {"az_deg": 20.0, "elev_deg": 1.5})
    assert f[0]["mission_phase"] == "ORBIT" and math.isclose(f[0]["orbit"]["alt_km"], 100.0)
    assert f[-1]["mission_phase"] == "DEORBIT" and math.isclose(f[-1]["orbit"]["alt_km"], 15.0, abs_tol=0.1)
    assert all(b["t_s"] >= a["t_s"] for a, b in zip(f, f[1:]))


def test_descent_frames_report_the_engine_failure_and_touchdown() -> None:
    """Real Basilisk telemetry yields an engine-failure event and a touchdown event."""
    from pathlib import Path

    from lunar_ops.mission_timeline import descent_frames

    csv_path = Path(__file__).resolve().parents[1] / "ui" / "sample" / "descent_basilisk.csv"
    f = descent_frames(csv_path, 1000.0, (10.0, 20.0), {"az_deg": 0.0, "elev_deg": 1.5})
    msgs = [e["msg"] for fr in f for e in fr["events"]]
    assert any("Engine failure" in m for m in msgs) and any("Touchdown" in m for m in msgs)
    assert f[0]["t_s"] > 1000.0 and f[-1]["lander"]["alt_m"] < 5.0
    assert min(fr["lander"]["engines_ok"] for fr in f) == 3


def test_world_message_carries_site_models_and_provenance(env: RoverEnv) -> None:
    """The world message has the site, the AI-stack registry and a provenance map."""
    m = world_message(env)
    assert -90.0 <= m["site"]["lat_deg"] <= -80.0
    assert {x["id"] for x in m["models"]} >= {"pilot", "meta", "rover", "light", "hazard", "terrain"}
    assert "terrain" in m["provenance"]


def test_ingest_socket_relays_external_telemetry_to_the_ui() -> None:
    """A producer on /ws/ingest (e.g. a Basilisk bridge) has its world and frames relayed to a connected UI."""
    app = create_app(seed=1, record=False)
    world = {"type": "world", "protocol": 1, "region": "ingest-test", "site": {"lat_deg": -89.0, "lon_deg": 0.0}}
    frame = {"type": "frame", "t_s": 5.0, "mission_phase": "DESCENT", "phase": "DESCENT", "control": "autonomy",
             "lander": {"x_m": 1.0, "y_m": 2.0, "alt_m": 300.0, "vx_m_s": 0.0, "vy_m_s": 0.0, "vz_m_s": -3.0,
                        "mass_kg": 900.0, "fuel_kg": 100.0, "thrust_n": 1500.0, "engines_ok": 5}, "events": []}
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ui") as ui:
            for _ in range(4):  # world, frame, state, models from the built-in simulator
                ui.receive_json()
            with client.websocket_connect("/ws/ingest") as producer:
                producer.send_json(world)
                producer.send_json(frame)
                got = []
                for _ in range(20):
                    m = ui.receive_json()
                    if m.get("region") == "ingest-test" or m.get("mission_phase") == "DESCENT":
                        got.append(m)
                    if len(got) == 2:
                        break
                assert got[0]["type"] == "world" and got[1]["lander"]["alt_m"] == 300.0


def test_training_endpoint_returns_rows_list() -> None:
    """/api/training answers with a (possibly empty) list of rows, never an error, when no log exists."""
    with TestClient(create_app(seed=1, record=False)) as client:
        body = client.get("/api/training").json()
    assert isinstance(body["rows"], list) and body["path"].endswith("train_log.jsonl")


def test_ui_is_two_dimensional_only() -> None:
    """The served mission-control page loads no 3D engine (3D is left to Basilisk / Vizard); only 2D chart libraries are vendored."""
    from pathlib import Path

    ui = Path(__file__).resolve().parents[1] / "ui"
    own = [ui / "index.html", *sorted(ui.glob("*.js"))]  # our own files; ui/vendor holds third-party chart and number libraries
    text = "".join(p.read_text(encoding="utf-8") for p in own)
    assert "three" not in text.lower()
    assert not [p for p in (ui / "vendor").rglob("*") if p.is_file() and "three" in p.name.lower()]


def _tiny_ghost_bytes() -> bytes:
    from pathlib import Path

    return (Path(__file__).parent / "fixtures" / "ghost_rover_tiny.json").read_bytes()


def test_tiny_ghost_fixture_is_valid_and_summarised() -> None:
    """The 3-run fixture (one best, one battery death, one timeout) validates and is summarised correctly."""
    import json

    from lunar_ops.ghosts import validate_ghost

    rep = validate_ghost(json.loads(_tiny_ghost_bytes()))
    assert rep["ok"] and not rep["errors"]
    assert rep["summary"]["n_runs"] == 3 and rep["summary"]["best"] == "best"
    assert rep["summary"]["outcomes"] == {"returned": 1, "died_battery": 1, "timeout": 1}


def test_ghost_validation_rejects_malformed_files_without_repairing_them() -> None:
    """Missing or mismatched fields are reported as errors; the file is never fixed up."""
    import json

    from lunar_ops.ghosts import validate_ghost

    g = json.loads(_tiny_ghost_bytes())
    g["runs"][1]["xyz_m"] = g["runs"][1]["xyz_m"][:-1]  # one sample short
    del g["runs"][2]["outcome"]
    rep = validate_ghost(g)
    assert not rep["ok"]
    assert any("xyz_m" in e for e in rep["errors"]) and any("outcome" in e for e in rep["errors"])
    assert not validate_ghost({"kind": "boat"})["ok"] and not validate_ghost([1, 2])["ok"]


def test_ghost_upload_endpoint_saves_valid_rejects_invalid_and_blocks_bad_names(tmp_path) -> None:
    """POST /api/ghosts/<name> stores a valid ghost, answers 422 for an invalid one and 400 for a path-like name."""
    import json

    app = create_app(seed=1, record=False, ghost_dir=tmp_path)
    with TestClient(app) as client:
        ok = client.post("/api/ghosts/rover_test_2027-09-01.json", content=_tiny_ghost_bytes())
        assert ok.status_code == 200 and ok.json()["saved"] and (tmp_path / "rover_test_2027-09-01.json").is_file()
        bad = json.loads(_tiny_ghost_bytes())
        bad["runs"][0]["t_s"] = []
        r = client.post("/api/ghosts/bad.json", content=json.dumps(bad).encode())
        assert r.status_code == 422 and not r.json()["saved"] and not (tmp_path / "bad.json").exists()
        assert client.post("/api/ghosts/..%2Fevil.json", content=b"{}").status_code in (400, 404, 405)
        assert not (tmp_path.parent / "evil.json").exists() and not (tmp_path / "evil.json").exists()
        assert client.post("/api/ghosts/notes.exe", content=b"x").status_code == 400
        listing = client.get("/api/ghosts").json()
        assert [f["name"] for f in listing] == ["rover_test_2027-09-01.json"] and listing[0]["summary"]["n_runs"] == 3
        assert client.get("/api/ghosts/rover_test_2027-09-01.json").json()["kind"] == "rover"


def test_glb_to_obj_rotates_gltf_axes_into_the_body_frame(tmp_path) -> None:
    """glTF (Y up, front -Z) becomes the simulator body frame (Z up, front +x): height lands on z, front on +x."""
    import importlib.util
    from pathlib import Path

    import pytest

    trimesh = pytest.importorskip("trimesh")
    spec = importlib.util.spec_from_file_location("glb_to_obj", Path(__file__).resolve().parents[1] / "vizard" / "glb_to_obj.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert math.isclose(float(np.linalg.det(mod.GLTF_TO_BODY)), 1.0)  # a proper rotation, no mirroring
    box = trimesh.creation.box(extents=[2.0, 6.0, 4.0])  # glTF x = 2 (sideways), y = 6 (up), z = 4 (front/back)
    box.apply_translation([0.0, 3.0, -2.0])  # sits on y = 0..6, reaches 2 m to the front (-z)
    glb = tmp_path / "box.glb"
    trimesh.Scene(box).export(str(glb))
    info = mod.convert(glb, tmp_path / "box.obj")
    assert info["min_m"] == [0.0, -1.0, 0.0] and info["max_m"] == [4.0, 1.0, 6.0]  # front +x, sideways y, up z
    assert (tmp_path / "box.mtl").is_file()


def test_server_serves_the_3d_showcase_next_to_the_2d_mission_control() -> None:
    """/showcase/ serves the 3D film page; the Mission Control page at / stays the 2D one."""
    with TestClient(create_app(seed=1, record=False)) as client:
        show = client.get("/showcase/")
        assert show.status_code == 200 and "showcase.js" in show.text
        assert client.get("/showcase/models/lander_B.glb").status_code == 200
        assert "three" not in client.get("/").text.lower()
