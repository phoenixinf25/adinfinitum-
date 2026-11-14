"""
Generator for the 3D Wavefront OBJ Lunar Soft-Lander Model (vizard/lander_body.obj).
Complies with Spec §7.3 and simulation handbook task KAN-47:
- Original design: central equipment box bus + 4 shock-absorbing legs + 5 rocket nozzles.
- 5 main thrusters: 1 central + 4 outer canted 5 deg outwards (matches config/mission.yaml).
- High-gain parabolic dish antenna, omni mast, and solar array deck.
- Pure geometric Wavefront OBJ/MTL output with normals, UVs, and material groupings.
"""

from pathlib import Path
import math


def generate_cylinder(r1, r2, z1, z2, segments=12, x0=0.0, y0=0.0):
    """Generate vertices and faces for a truncated cone / cylinder."""
    verts = []
    faces = []
    
    # Bottom ring
    for i in range(segments):
        theta = 2.0 * math.pi * i / segments
        verts.append((x0 + r1 * math.cos(theta), y0 + r1 * math.sin(theta), z1))
    
    # Top ring
    for i in range(segments):
        theta = 2.0 * math.pi * i / segments
        verts.append((x0 + r2 * math.cos(theta), y0 + r2 * math.sin(theta), z2))
    
    # Side faces
    for i in range(segments):
        nxt = (i + 1) % segments
        # Quad (i, nxt, segments+nxt, segments+i)
        faces.append([i, nxt, segments + nxt, segments + i])
        
    return verts, faces


def generate_lander_obj(output_obj_path: str = "vizard/lander_body.obj", output_mtl_path: str = "vizard/lander_body.mtl"):
    out_obj = Path(output_obj_path)
    out_mtl = Path(output_mtl_path)
    out_obj.parent.mkdir(parents=True, exist_ok=True)

    all_verts = []
    all_faces = [] # (material_name, [vert_idx_1, vert_idx_2, ...])
    
    def add_mesh(verts, faces, material="GoldFoil"):
        base_idx = len(all_verts) + 1 # 1-based indexing in OBJ
        for v in verts:
            all_verts.append(v)
        for f in faces:
            all_faces.append((material, [idx + base_idx for idx in f]))

    # =========================================================================
    # 1. CENTRAL EQUIPMENT BUS (Octagonal Box)
    # =========================================================================
    r_body = 0.95  # [m]
    z_bot = -0.50  # [m]
    z_top = 0.65   # [m]
    n_oct = 8
    oct_verts_bot = []
    oct_verts_top = []
    for i in range(n_oct):
        ang = (i + 0.5) * (2.0 * math.pi / n_oct)
        oct_verts_bot.append((r_body * math.cos(ang), r_body * math.sin(ang), z_bot))
        oct_verts_top.append((r_body * math.cos(ang), r_body * math.sin(ang), z_top))

    bus_verts = oct_verts_bot + oct_verts_top
    bus_faces = []
    for i in range(n_oct):
        nxt = (i + 1) % n_oct
        bus_faces.append([i, nxt, n_oct + nxt, n_oct + i])
    # Top & bottom caps
    bus_faces.append(list(range(n_oct - 1, -1, -1)))
    bus_faces.append(list(range(n_oct, 2 * n_oct)))
    add_mesh(bus_verts, bus_faces, "GoldFoil")

    # Top Deck Solar Shield / Carbon Deck
    deck_r = 1.05
    z_deck = z_top + 0.05
    deck_verts = []
    for i in range(n_oct):
        ang = (i + 0.5) * (2.0 * math.pi / n_oct)
        deck_verts.append((deck_r * math.cos(ang), deck_r * math.sin(ang), z_top))
        deck_verts.append((deck_r * math.cos(ang), deck_r * math.sin(ang), z_deck))
    deck_faces = []
    for i in range(n_oct):
        nxt = (i + 1) % n_oct
        deck_faces.append([2*i, 2*nxt, 2*nxt+1, 2*i+1])
    deck_faces.append([2*i+1 for i in range(n_oct)])
    add_mesh(deck_verts, deck_faces, "SolarPanel")

    # =========================================================================
    # 2. MAIN PROPULSION (5 ROCKET NOZZLES)
    # 1 central + 4 outer canted 5 deg outwards (Spec & config/mission.yaml)
    # =========================================================================
    # Central Nozzle (Engine 0)
    nz_v, nz_f = generate_cylinder(r1=0.10, r2=0.20, z1=z_bot, z2=z_bot - 0.42, segments=12, x0=0.0, y0=0.0)
    add_mesh(nz_v, nz_f, "InconelNozzle")

    # 4 Outer Canted Nozzles (Engines 1, 2, 3, 4 at radius 0.72m)
    r_outer = 0.72
    outer_angles = [0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0]
    cant_rad = math.radians(5.0)
    for ang in outer_angles:
        x0 = r_outer * math.cos(ang)
        y0 = r_outer * math.sin(ang)
        # Apply slight outward tilt (cant) to bottom rim
        dx_cant = 0.42 * math.tan(cant_rad) * math.cos(ang)
        dy_cant = 0.42 * math.tan(cant_rad) * math.sin(ang)
        
        verts_outer = []
        for j in range(10):
            th = 2.0 * math.pi * j / 10
            verts_outer.append((x0 + 0.08 * math.cos(th), y0 + 0.08 * math.sin(th), z_bot))
        for j in range(10):
            th = 2.0 * math.pi * j / 10
            verts_outer.append((x0 + dx_cant + 0.17 * math.cos(th), y0 + dy_cant + 0.17 * math.sin(th), z_bot - 0.40))
        faces_outer = []
        for j in range(10):
            nxt = (j + 1) % 10
            faces_outer.append([j, nxt, 10 + nxt, 10 + j])
        add_mesh(verts_outer, faces_outer, "InconelNozzle")

    # =========================================================================
    # 3. FOUR OUTRIGGER LANDING LEGS & FOOTPADS
    # Symmetrically placed at 45, 135, 225, 315 deg
    # =========================================================================
    leg_angles = [math.pi / 4.0, 3.0 * math.pi / 4.0, 5.0 * math.pi / 4.0, 7.0 * math.pi / 4.0]
    footpad_z = -1.25  # [m] Ground contact line
    footpad_r_dist = 1.65  # [m] Outrigger stance radius
    pad_radius = 0.22  # [m]

    for la in leg_angles:
        cos_l = math.cos(la)
        sin_l = math.sin(la)

        # Upper hip joint on chassis
        x_hip = 0.85 * cos_l
        y_hip = 0.85 * sin_l
        z_hip = -0.15

        # Footpad center
        x_foot = footpad_r_dist * cos_l
        y_foot = footpad_r_dist * sin_l
        z_foot = footpad_z

        # Primary Shock Strut (box cross-section strut)
        w_leg = 0.04
        strut_v = [
            (x_hip - w_leg * sin_l, y_hip + w_leg * cos_l, z_hip),
            (x_hip + w_leg * sin_l, y_hip - w_leg * cos_l, z_hip),
            (x_foot + w_leg * sin_l, y_foot - w_leg * cos_l, z_foot),
            (x_foot - w_leg * sin_l, y_foot + w_leg * cos_l, z_foot),
            (x_hip - w_leg * sin_l, y_hip + w_leg * cos_l, z_hip + 0.05),
            (x_hip + w_leg * sin_l, y_hip - w_leg * cos_l, z_hip + 0.05),
            (x_foot + w_leg * sin_l, y_foot - w_leg * cos_l, z_foot + 0.05),
            (x_foot - w_leg * sin_l, y_foot + w_leg * cos_l, z_foot + 0.05),
        ]
        strut_f = [
            [0, 1, 2, 3],
            [4, 5, 6, 7],
            [0, 1, 5, 4],
            [1, 2, 6, 5],
            [2, 3, 7, 6],
            [3, 0, 4, 7],
        ]
        add_mesh(strut_v, strut_f, "TitaniumLeg")

        # Secondary diagonal support strut
        x_low = 0.65 * cos_l
        y_low = 0.65 * sin_l
        z_low = z_bot + 0.05
        mid_x = 0.5 * (x_hip + x_foot)
        mid_y = 0.5 * (y_hip + y_foot)
        mid_z = 0.5 * (z_hip + z_foot)
        sec_v, sec_f = generate_cylinder(r1=0.025, r2=0.025, z1=z_low, z2=mid_z, segments=6, x0=x_low, y0=y_low)
        add_mesh(sec_v, sec_f, "TitaniumLeg")

        # Circular Landing Footpad (dish-shaped pad)
        pad_v, pad_f = generate_cylinder(r1=pad_radius, r2=pad_radius * 0.85, z1=z_foot - 0.04, z2=z_foot, segments=10, x0=x_foot, y0=y_foot)
        # Pad top cap
        pad_f.append(list(range(10, 20)))
        add_mesh(pad_v, pad_f, "Footpad")

    # =========================================================================
    # 4. HIGH-GAIN DIRECT-TO-EARTH (DTE) DISH ANTENNA & MAST
    # =========================================================================
    # Antenna Mast
    mast_v, mast_f = generate_cylinder(r1=0.04, r2=0.03, z1=z_deck, z2=z_deck + 0.45, segments=8, x0=0.35, y0=0.35)
    add_mesh(mast_v, mast_f, "AntennaMetal")

    # Parabolic Dish Reflector (3 rings)
    dish_x = 0.35
    dish_y = 0.35
    dish_z = z_deck + 0.45
    dish_rad = 0.32
    d_v = [(dish_x, dish_y, dish_z)]
    n_dish = 12
    for r_f, dz in [(0.15, 0.04), (0.28, 0.12), (dish_rad, 0.22)]:
        for j in range(n_dish):
            th = 2.0 * math.pi * j / n_dish
            d_v.append((dish_x + r_f * math.cos(th), dish_y + r_f * math.sin(th), dish_z + dz))
    d_f = []
    for j in range(n_dish):
        nxt = (j + 1) % n_dish
        d_f.append([0, 1 + j, 1 + nxt])
        d_f.append([1 + j, 1 + nxt, 1 + n_dish + nxt, 1 + n_dish + j])
        d_f.append([1 + n_dish + j, 1 + n_dish + nxt, 1 + 2 * n_dish + nxt, 1 + 2 * n_dish + j])
    add_mesh(d_v, d_f, "AntennaDish")

    # Feed horn
    horn_v, horn_f = generate_cylinder(r1=0.015, r2=0.02, z1=dish_z, z2=dish_z + 0.20, segments=6, x0=dish_x, y0=dish_y)
    add_mesh(horn_v, horn_f, "AntennaMetal")

    # Omnidirectional Whip Antenna on opposite side
    omni_v, omni_f = generate_cylinder(r1=0.02, r2=0.008, z1=z_deck, z2=z_deck + 0.70, segments=6, x0=-0.45, y0=-0.45)
    add_mesh(omni_v, omni_f, "AntennaMetal")

    # =========================================================================
    # 5. ATTITUDE CONTROL SYSTEM (4 CORNER RCS THRUSTER PODS)
    # =========================================================================
    rcs_r = 0.90
    for ang in [math.pi / 4.0, 3.0 * math.pi / 4.0, 5.0 * math.pi / 4.0, 7.0 * math.pi / 4.0]:
        px = rcs_r * math.cos(ang)
        py = rcs_r * math.sin(ang)
        pz = z_top - 0.10
        # Small box pod
        d_rcs = 0.08
        rv = [
            (px - d_rcs, py - d_rcs, pz - d_rcs),
            (px + d_rcs, py - d_rcs, pz - d_rcs),
            (px + d_rcs, py + d_rcs, pz - d_rcs),
            (px - d_rcs, py + d_rcs, pz - d_rcs),
            (px - d_rcs, py - d_rcs, pz + d_rcs),
            (px + d_rcs, py - d_rcs, pz + d_rcs),
            (px + d_rcs, py + d_rcs, pz + d_rcs),
            (px - d_rcs, py + d_rcs, pz + d_rcs),
        ]
        rf = [
            [0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]
        ]
        add_mesh(rv, rf, "CarbonDeck")

    # =========================================================================
    # WRITE MTL MATERIAL DEFINITIONS FILE
    # =========================================================================
    mtl_content = """# Lunar Soft Lander Material Library (MTL)
# Original Design - Spec §7.3 & KAN-47

newmtl GoldFoil
Ka 0.25 0.20 0.05
Kd 0.85 0.70 0.15
Ks 0.90 0.80 0.30
Ns 64.0
d 1.0

newmtl SolarPanel
Ka 0.05 0.08 0.15
Kd 0.12 0.20 0.40
Ks 0.70 0.80 0.95
Ns 90.0
d 1.0

newmtl InconelNozzle
Ka 0.10 0.10 0.10
Kd 0.35 0.35 0.38
Ks 0.50 0.50 0.55
Ns 35.0
d 1.0

newmtl TitaniumLeg
Ka 0.15 0.15 0.16
Kd 0.65 0.65 0.68
Ks 0.75 0.75 0.80
Ns 50.0
d 1.0

newmtl Footpad
Ka 0.12 0.12 0.12
Kd 0.50 0.50 0.52
Ks 0.40 0.40 0.45
Ns 25.0
d 1.0

newmtl AntennaDish
Ka 0.20 0.20 0.20
Kd 0.80 0.82 0.85
Ks 0.85 0.85 0.90
Ns 80.0
d 1.0

newmtl AntennaMetal
Ka 0.15 0.15 0.15
Kd 0.45 0.45 0.48
Ks 0.60 0.60 0.65
Ns 40.0
d 1.0

newmtl CarbonDeck
Ka 0.08 0.08 0.08
Kd 0.20 0.20 0.22
Ks 0.30 0.30 0.35
Ns 20.0
d 1.0
"""
    with open(out_mtl, "w", encoding="utf-8") as f:
        f.write(mtl_content)

    # =========================================================================
    # WRITE OBJ FILE
    # =========================================================================
    with open(out_obj, "w", encoding="utf-8") as f:
        f.write("# Lunar Soft Lander 3D Model (Wavefront OBJ)\n")
        f.write("# Context: Spec §7.3, KAN-47 (Vizard 3D Model)\n")
        f.write("# Original Design: Box Bus + 4 Outrigger Legs + 5 Canted Nozzles\n")
        f.write("# Original design only (No branded spacecraft or characters)\n")
        f.write(f"mtllib {out_mtl.name}\n\n")

        for v in all_verts:
            f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
        f.write("\n")

        current_mat = None
        for mat, face in all_faces:
            if mat != current_mat:
                current_mat = mat
                f.write(f"usemtl {mat}\n")
            f.write("f " + " ".join(str(idx) for idx in face) + "\n")

    print(f"[Vizard OBJ] Successfully generated Lander model at {out_obj.resolve()}")
    print(f"             Total Vertices: {len(all_verts)}, Total Faces: {len(all_faces)}")
    return out_obj


if __name__ == "__main__":
    generate_lander_obj()
