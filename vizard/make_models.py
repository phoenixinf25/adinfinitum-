"""
Procedural 3D model generator for Basilisk Vizard runtime OBJ import (Spec §7.3, KAN-47).
Generates:
  vizard/lander_body.obj (+ .mtl)  : Original lunar soft-lander (box + 4 legs + 5 nozzles).
  vizard/rover_body.obj  (+ .mtl)  : Original lunar rover (box + 6 wheels + solar panel).
  vizard/terrain_<region>.obj      : Real LOLA digital elevation model terrain mesh.
"""

from pathlib import Path
from tools.build_lander_mesh import generate_lander_obj
from basilisk_mods.rover import export_rover_vizard_mesh
from basilisk_mods.lunar_terrain import export_to_obj, LunarTerrain


def make_all_vizard_models(vizard_dir: str | Path = "vizard", tiles_dir: str | Path = "data/tiles"):
    v_dir = Path(vizard_dir)
    v_dir.mkdir(parents=True, exist_ok=True)
    t_dir = Path(tiles_dir)

    print("================================================================================")
    print("VIZARD 3D ASSET GENERATOR (Spec §7.3 / KAN-47)")
    print("================================================================================")

    # 1. Lander Model
    lander_obj = v_dir / "lander_body.obj"
    lander_mtl = v_dir / "lander_body.mtl"
    generate_lander_obj(str(lander_obj), str(lander_mtl))

    # 2. Rover Model
    rover_obj = v_dir / "rover_body.obj"
    export_rover_vizard_mesh(output_obj_path=str(rover_obj))

    # 3. Terrain Meshes from LOLA tiles
    for region in ["demo_craters", "shackleton"]:
        terrain_obj = v_dir / f"terrain_{region}.obj"
        tile_file = t_dir / f"{region}.npz"
        if tile_file.exists() and not terrain_obj.exists():
            print(f"[Terrain] Exporting {region} DEM to Wavefront OBJ...")
            terrain = LunarTerrain(region, tiles_dir=str(t_dir))
            export_to_obj(
                terrain=terrain,
                output_path=str(terrain_obj),
                sample_step=4,
                vertical_exaggeration=1.5
            )
        elif terrain_obj.exists():
            print(f"[Terrain] Existing terrain mesh verified: {terrain_obj} ({terrain_obj.stat().st_size / (1024*1024):.1f} MB)")

    print("================================================================================")
    print("ALL VIZARD 3D ASSETS READY:")
    print(f"  Lander:  {lander_obj}")
    print(f"  Rover:   {rover_obj}")
    print(f"  Terrain: {v_dir / 'terrain_shackleton.obj'}")
    print("================================================================================")


if __name__ == "__main__":
    make_all_vizard_models()
