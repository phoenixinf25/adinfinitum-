"""
tests/test_vizard.py
====================
Unit and integration tests for Vizard 3D models, vizSupport protocol engine,
mission scenario hooks, and video assets.

Covers:
- 3D Wavefront OBJ models: original lander_body.obj, rover_body.obj, LOLA terrain meshes.
- Vizard protocol engine: custom models, pointing lines, binary .bin and JSON playback export.
- Scenario integration: orbit_release, descent (nominal + engine-out), rover traverse.
- Video hero assets: 1080p clips generation, duration, provenance and exaggeration disclosures.

Context: Spec §7.3 & KAN-47 Vizard 3D Mission Replay (Arnav).
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest

from basilisk_mods.bsk_common import out_dir
from basilisk_mods import scenario_orbit_release, scenario_descent, scenario_rover
from basilisk_mods import viz_support


class TestVizard3DModels(unittest.TestCase):
    """Verify 3D Wavefront OBJ assets in vizard/ directory."""

    def test_lander_model_geometry_and_mtl(self):
        """Lander 3D model must exist, be an original geometric design, and have valid OBJ/MTL syntax."""
        obj_file = Path("vizard/lander_body.obj")
        mtl_file = Path("vizard/lander_body.mtl")
        self.assertTrue(obj_file.exists(), f"Missing {obj_file}")
        self.assertTrue(mtl_file.exists(), f"Missing {mtl_file}")

        lines = obj_file.read_text(encoding="utf-8").splitlines()
        vertices = [l for l in lines if l.startswith("v ")]
        faces = [l for l in lines if l.startswith("f ")]
        self.assertGreaterEqual(len(vertices), 300, "Lander model must have >= 300 vertices for fidelity")
        self.assertGreaterEqual(len(faces), 200, "Lander model must have >= 200 faces")

        # Original design notice in comments
        header_comments = "\n".join(lines[:15])
        self.assertIn("Original Design", header_comments)
        self.assertIn("No branded", header_comments)

    def test_rover_model_geometry(self):
        """Pragyan 3 rover 3D model must have chassis, wheels, solar deck, and valid OBJ syntax."""
        obj_file = Path("vizard/rover_body.obj")
        self.assertTrue(obj_file.exists(), f"Missing {obj_file}")

        lines = obj_file.read_text(encoding="utf-8").splitlines()
        vertices = [l for l in lines if l.startswith("v ")]
        faces = [l for l in lines if l.startswith("f ")]
        self.assertGreaterEqual(len(vertices), 180, "Rover model must have >= 180 vertices")
        self.assertGreaterEqual(len(faces), 180, "Rover model must have >= 180 faces")

    def test_lola_terrain_meshes(self):
        """LOLA DEM terrain meshes must exist and carry vertical exaggeration label."""
        shackleton_obj = Path("vizard/terrain_shackleton.obj")
        demo_obj = Path("vizard/terrain_demo_craters.obj")
        self.assertTrue(shackleton_obj.exists(), f"Missing {shackleton_obj}")
        self.assertTrue(demo_obj.exists(), f"Missing {demo_obj}")
        self.assertGreater(shackleton_obj.stat().st_size, 5_000_000, "Shackleton terrain must be high-res (> 5MB)")

        content = demo_obj.read_text(encoding="utf-8")[:500]
        self.assertIn("vertical exaggeration", content.lower())


class TestVizardProtocolEngine(unittest.TestCase):
    """Verify basilisk_mods.viz_support protocol and binary serialization."""

    def test_viz_interface_recorder_and_export(self):
        """VizInterfaceWrapper must record frames and output valid .bin and .json files."""
        temp_dir = out_dir() / "_test_vizard"
        temp_dir.mkdir(parents=True, exist_ok=True)
        save_base = temp_dir / "test_sim"

        viz = viz_support.enableUnityVisualization(sim=None, taskName="dynTask", scList=None, saveFile=save_base)
        viz_support.createCustomModel(viz, modelPath="vizard/lander_body.obj", simBodiesToModify=["lander"])
        viz_support.createPointLine(viz, toBodyName="sun_planet_data", lineColor="yellow")
        viz_support.createPointLine(viz, toBodyName="earth_planet_data", lineColor=[0, 150, 255, 255])

        # Record 5 frames
        for t in range(5):
            viz.record_frame(
                time_s=float(t),
                bodies_state={
                    "lander": {
                        "r_m": [0.0, 0.0, 1000.0 - t * 200.0],
                        "v_m_s": [0.0, 0.0, -200.0],
                        "mrp": [0.0, 0.0, 0.0],
                    }
                },
                thrusters=[1.0, 0.8, 0.8, 0.8, 0.8],
                sun_direction=[1.0, 0.0, 0.0],
                earth_direction=[0.0, 1.0, 0.0],
            )

        bin_path, json_path = viz.save()
        self.assertTrue(bin_path.exists())
        self.assertTrue(json_path.exists())

        # Verify binary header magic
        with open(bin_path, "rb") as f:
            magic = f.read(16)
            self.assertEqual(magic, b"BSK_UNITYVIZ_v2\x00")
            n_frames, n_models, n_lines = struct.unpack("<III", f.read(12))
            self.assertEqual(n_frames, 5)
            self.assertEqual(n_models, 1)
            self.assertEqual(n_lines, 2)

        # Verify JSON manifest
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["totalFrames"], 5)
        self.assertEqual(len(data["customModels"]), 1)
        self.assertEqual(len(data["pointLines"]), 2)
        self.assertIn("verticalExaggeration", data)


class TestMissionScenarioExecution(unittest.TestCase):
    """Verify execution of orbit, descent, and rover scenarios with Vizard output."""

    def test_orbit_release_scenario_execution(self):
        """Scenario orbit release must output 15 km PDI state and Vizard binary."""
        state = scenario_orbit_release.run(viz=True, plot=False)
        self.assertAlmostEqual(state["altitude_m"] / 1e3, 15.0, delta=0.5)
        self.assertAlmostEqual(state["speed_m_s"], 1692.7, delta=10.0)
        self.assertAlmostEqual(state["deorbit_dv_m_s"], -19.5, delta=1.0)
        self.assertTrue((out_dir() / "_VizFiles/orbit_release_UnityViz.bin").exists())

    def test_descent_nominal_and_engine_out(self):
        """Descent scenario must land safely nominal and with engine-out at 20s."""
        # 1. Nominal
        rep_nom = scenario_descent.run(run_id="unit_test_nom", viz=True)
        self.assertEqual(rep_nom["outcome"], "ok")
        self.assertLessEqual(rep_nom["vertical_speed_m_s"], 2.0)
        self.assertLessEqual(rep_nom["horizontal_speed_m_s"], 0.5)
        self.assertLessEqual(rep_nom["tilt_deg"], 12.0)

        # 2. Engine out at 20s
        rep_out = scenario_descent.run(run_id="unit_test_out", engine_out_at=20.0, viz=True)
        self.assertEqual(rep_out["outcome"], "ok")
        self.assertEqual(rep_out["engine_out_at_s"], 20.0)
        self.assertLessEqual(rep_out["vertical_speed_m_s"], 2.0)

    def test_rover_scenario_full_traverse(self):
        """Rover scenario must respect limits, visit waypoints, and export Vizard playback."""
        res = scenario_rover.run_rover_scenario(rover_id="unit_test_rover", verbose=False)
        self.assertTrue(res["speed_check_passed"])
        self.assertTrue(res["slope_check_passed"])
        self.assertTrue(res["shadow_entered"])
        self.assertTrue(res["shadow_exited"])
        self.assertTrue(res["waypoints_completed"])
        self.assertTrue((out_dir() / "_VizFiles/rover_unit_test_rover_UnityViz.bin").exists())


class TestVideoAssetsGeneration(unittest.TestCase):
    """Verify the 3 recorded 1080p hero clips in video_assets/."""

    def test_three_1080p_hero_clips_exist_and_non_empty(self):
        """All 3 required video clips must exist, be > 500 KB, and have README documentation."""
        clip1 = Path("video_assets/clip1_orbit_release.mp4")
        clip2 = Path("video_assets/clip2_descent_engine_out.mp4")
        clip3 = Path("video_assets/clip3_rover_ice_traverse.mp4")
        readme = Path("video_assets/README.md")

        self.assertTrue(clip1.exists(), f"Missing {clip1}")
        self.assertTrue(clip2.exists(), f"Missing {clip2}")
        self.assertTrue(clip3.exists(), f"Missing {clip3}")
        self.assertTrue(readme.exists(), f"Missing {readme}")

        self.assertGreater(clip1.stat().st_size, 500_000, "Clip 1 must be > 500 KB")
        self.assertGreater(clip2.stat().st_size, 500_000, "Clip 2 must be > 500 KB")
        self.assertGreater(clip3.stat().st_size, 500_000, "Clip 3 must be > 500 KB")

        readme_text = readme.read_text(encoding="utf-8")
        self.assertIn("1080p", readme_text)
        self.assertIn("vertical exaggeration", readme_text)
        self.assertIn("60x", readme_text.lower())
        self.assertIn("original design", readme_text.lower())


if __name__ == "__main__":
    unittest.main()
