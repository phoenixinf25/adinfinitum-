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
    """The served mission-control page loads no 3D engine: 3D is left to Basilisk / Vizard."""
    from pathlib import Path

    ui = Path(__file__).resolve().parents[1] / "ui"
    text = (ui / "index.html").read_text(encoding="utf-8") + (ui / "app.js").read_text(encoding="utf-8")
    assert "three" not in text.lower() and not (ui / "vendor").exists()
