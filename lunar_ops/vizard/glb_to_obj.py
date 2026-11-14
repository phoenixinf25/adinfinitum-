#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Convert a glTF binary (``.glb``) model to the OBJ + MTL pair that Vizard's custom models need.

``vizSupport.createCustomModel`` only loads OBJ files. glTF is Y up with the vehicle front along -Z; the simulator body
frame is Z up with the front along +x (right-handed), so every vertex and normal is rotated with

    x_body = -z_gltf,  y_body = -x_gltf,  z_body = y_gltf

Materials keep their names, base colours and a rough specular term. Vizard's runtime OBJ importer ignores plain MTL
colours, so each material also gets a tiny solid-colour PNG (``map_Kd``) and every vertex one texture coordinate.
Nothing else about the model is changed.

Usage::

    python glb_to_obj.py lander_B.glb assets/lander_B.obj
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import numpy as np
import trimesh

TEXTURE_PX = 4  # [px] edge of the solid-colour texture written for each material
GLTF_TO_BODY = np.array([[0.0, 0.0, -1.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])  # [-] proper rotation, det = +1


def _solid_png(path: Path, rgb: tuple[float, float, float]) -> None:
    """Write a small opaque PNG of one colour. ``rgb`` is linear (glTF); the PNG stores sRGB."""
    def to_srgb(c: float) -> int:
        c = min(max(c, 0.0), 1.0)
        return round(255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055))
    px = bytes(to_srgb(c) for c in rgb)
    raw = b"".join(b"\x00" + px * TEXTURE_PX for _ in range(TEXTURE_PX))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", TEXTURE_PX, TEXTURE_PX, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def convert(glb: Path, obj: Path) -> dict[str, object]:
    """Write ``obj`` (and ``obj`` with ``.mtl``) from ``glb`` and return a short summary.

    :param glb: input glTF binary file.
    :param obj: output OBJ path; the MTL gets the same stem.
    """
    scene = trimesh.load(str(glb), force="scene")
    mtl_path = obj.with_suffix(".mtl")
    materials: dict[str, tuple[float, float, float, float, float]] = {}
    lines = [f"# converted from {glb.name}: glTF (Y up, front -Z) -> body frame (Z up, front +x)", f"mtllib {mtl_path.name}", "vt 0.5 0.5"]
    v_off = 1
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    tris = 0
    for node in sorted(scene.graph.nodes_geometry):
        transform, geom_name = scene.graph[node]
        g = scene.geometry[geom_name].copy()
        g.apply_transform(transform)
        v = g.vertices @ GLTF_TO_BODY.T
        n = g.vertex_normals @ GLTF_TO_BODY.T
        mat = getattr(g.visual, "material", None)
        name = (getattr(mat, "name", None) or "default").replace(" ", "_")
        base = getattr(mat, "baseColorFactor", None)
        rgba = [c / 255.0 for c in base] if base is not None else [0.7, 0.7, 0.7, 1.0]
        metallic = float(getattr(mat, "metallicFactor", 0.0) or 0.0)
        rough = float(getattr(mat, "roughnessFactor", 0.5) or 0.5)
        materials.setdefault(name, (rgba[0], rgba[1], rgba[2], metallic, rough))
        lines.append(f"o {node.replace(' ', '_')}")
        lines.append(f"usemtl {name}")
        lines.extend(f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in v)
        lines.extend(f"vn {x:.5f} {y:.5f} {z:.5f}" for x, y, z in n)
        lines.extend(f"f {a + v_off}/1/{a + v_off} {b + v_off}/1/{b + v_off} {c + v_off}/1/{c + v_off}" for a, b, c in g.faces)
        v_off += len(v)
        tris += len(g.faces)
        lo = np.minimum(lo, v.min(axis=0))
        hi = np.maximum(hi, v.max(axis=0))
    obj.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mtl = []
    for name, (r, gg, b, metallic, rough) in materials.items():
        spec = 0.15 + 0.6 * metallic
        tex = f"{obj.stem}_{name}.png"
        _solid_png(obj.parent / tex, (r, gg, b))
        mtl += [f"newmtl {name}", f"Kd {r:.4f} {gg:.4f} {b:.4f}", f"Ka {r * 0.2:.4f} {gg * 0.2:.4f} {b * 0.2:.4f}", f"Ks {spec:.3f} {spec:.3f} {spec:.3f}", f"Ns {max(2.0, (1.0 - rough) * 200.0):.1f}", "d 1.0", "illum 2", f"map_Kd {tex}", ""]
    mtl_path.write_text("\n".join(mtl), encoding="utf-8")
    return {"obj": obj.name, "triangles": tris, "materials": len(materials), "min_m": lo.round(3).tolist(), "max_m": hi.round(3).tolist()}


if __name__ == "__main__":
    print(convert(Path(sys.argv[1]), Path(sys.argv[2])))
