# Data Formats Specification (Spec §7.2)

This document specifies the standard data formats for lunar terrain tiles, coordinate reference frames, units, interpolation models, and 3D visualization meshes used in the Basilisk simulation pipeline.

---

## 1. Lunar Terrain Tiles (`data/tiles/<region>.npz`)

Imok and data pipeline modules provide digital elevation and slope model tiles saved as compressed NumPy archives (`.npz`).

### 1.1 Array Keys & Datatypes

| Key | Type | Shape | Units | Description |
|---|---|---|---|---|
| `height_m` (or `height`) | `float32` | `(H, W)` | **metres (m)** | Surface elevation relative to the lunar reference sphere ($R_{moon} = 1737.4\text{ km} = 1737400.0\text{ m}$). |
| `slope_deg` (or `slope`) | `float32` | `(H, W)` | **degrees (deg)** | Surface slope angle relative to the local reference horizontal plane. |
| `x_m` | `float32` | `(W,)` or `(H, W)` | **metres (m)** | Polar-stereographic Easting coordinate for grid columns. |
| `y_m` | `float32` | `(H,)` or `(H, W)` | **metres (m)** | Polar-stereographic Northing coordinate for grid rows. |
| `hazard` | `float32` | `(H, W)` | **probability [0, 1]** | Landing / traverse hazard probability (slopes > 15° are considered hazardous). |
| `uncertainty` | `float32` | `(H, W)` | **metres (m)** | 1-sigma vertical elevation uncertainty. |
| `psr_mask` | `bool` | `(H, W)` | **boolean** | Permanently Shadowed Region mask (`True` = in permanent shadow). |
| `region` | `string` | scalar | string | Region identifier name (e.g., `"demo_craters"`, `"shackleton"`). |
| `meters_per_pixel` | `float32` | scalar | **metres / pixel** | Spatial resolution / grid spacing ($\Delta x = \Delta y$). |
| `center_lat_deg` | `float32` | scalar | **degrees (deg)** | Tile centre planetocentric latitude (South = negative, $[-90.0, 90.0]$). |
| `center_lon_deg` | `float32` | scalar | **degrees (deg)** | Tile centre planetocentric longitude (East = positive, $[-180.0, 180.0]$). |
| `meta` | `string` / `dict` | scalar | JSON | Full provenance metadata dictionary. |

### 1.2 Grid Alignment & Indexing Convention

- Grid dimensions: $H$ rows by $W$ columns.
- Row index $r = 0$: Northernmost row (highest $+y$).
- Row index $r = H - 1$: Southernmost row (lowest $-y$).
- Column index $c = 0$: Westernmost column (lowest $-x$).
- Column index $c = W - 1$: Easternmost column (highest $+x$).

---

## 2. Coordinate Frames & Transformations

### 2.1 Moon-Centred, Moon-Fixed Frame (`MOON_ME`)
- **Origin**: Centre of mass of the Moon.
- **Reference Sphere**: Mean lunar spherical radius $R_{moon} = 1,737,400.0\text{ metres}$ ($1737.4\text{ km}$).
- **$+Z$ axis**: Lunar rotational North Pole ($\text{lat} = +90^\circ$).
- **$+X$ axis**: Sub-Earth prime meridian intersection with the equator ($\text{lat} = 0^\circ, \text{lon} = 0^\circ$).
- **$+Y$ axis**: Completes right-handed orthogonal system ($\text{lat} = 0^\circ, \text{lon} = +90^\circ\text{E}$).
- **Units**: All position vectors $\vec{r} = [r_x, r_y, r_z]$ are in **metres**.

### 2.2 Lunar South Polar Stereographic Frame
- **Projection**: Polar Stereographic (Moon 2000, conformal azimuthal).
- **Standard Latitude of True Scale**: $\phi_{ts} = -90.0^\circ$ (South Pole).
- **Central Meridian**: $\lambda_0 = 0.0^\circ$.
- **Origin $(0, 0)$**: South Pole ($\phi = -90.0^\circ$).
- **$+X$ axis**: Points towards East longitude $\lambda = +90^\circ\text{E}$.
- **$+Y$ axis**: Points towards longitude $\lambda = 180.0^\circ$ (away from Earth).
- **$-Y$ axis**: Points towards longitude $\lambda = 0.0^\circ$ (towards Earth).
- **Units**: Polar-stereographic coordinates $(x, y)$ are in **metres**.

### 2.3 Forward Conversion (`ps_from_moon_fixed`)
Given spacecraft position $\vec{r}_{ME} = [r_x, r_y, r_z]$ in metres:
1. Spherical distance from Moon center:
   $$r = \sqrt{r_x^2 + r_y^2 + r_z^2}\text{ [m]}$$
2. Altitude above reference sphere:
   $$\text{alt\_sphere} = r - R_{moon}\text{ [m]}$$
3. Unit vector $\hat{u} = \vec{r}_{ME} / r = [u_x, u_y, u_z]$.
4. Colatitude $\chi$ from South Pole:
   $$\chi = \frac{\pi}{2} + \arcsin(u_z) = \arccos(-u_z)$$
   Planar radial distance:
   $$\rho = 2 R_{moon} \tan\left(\frac{\chi}{2}\right) = 2 R_{moon} \frac{\sqrt{u_x^2 + u_y^2}}{1 - u_z}\text{ [m]}$$
5. Polar stereographic coordinates:
   $$x = \rho \sin(\lambda) = 2 R_{moon} \frac{u_y}{1 - u_z}\text{ [m]}$$
   $$y = -\rho \cos(\lambda) = -2 R_{moon} \frac{u_x}{1 - u_z}\text{ [m]}$$

### 2.4 Inverse Conversion (`moon_fixed_from_ps`)
Given $(x, y)$ in metres and altitude above sphere $\text{alt\_sphere}$ in metres:
1. Planar radius $\rho = \sqrt{x^2 + y^2}\text{ [m]}$.
2. If $\rho = 0$: $\phi = -90.0^\circ, \lambda = 0.0^\circ$.
   Else:
   $$\chi = 2 \arctan\left(\frac{\rho}{2 R_{moon}}\right)$$
   $$\phi = \chi - \frac{\pi}{2}$$
   $$\lambda = \text{atan2}(x, -y)$$
3. Cartesian position in MOON_ME:
   $$r = R_{moon} + \text{alt\_sphere}\text{ [m]}$$
   $$r_x = r \cos(\phi) \cos(\lambda)\text{ [m]}$$
   $$r_y = r \cos(\phi) \sin(\lambda)\text{ [m]}$$
   $$r_z = r \sin(\phi)\text{ [m]}$$

---

## 3. Ground Height and Clearance Definitions

- **Ground Height** $h_{ground}(x, y)$: Terrain surface elevation in **metres** above the reference sphere at polar-stereographic coordinates $(x, y)$.
- **Spacecraft Altitude Above Ground** $h_{clearance}$:
  $$h_{clearance} = \text{alt\_sphere} - h_{ground}(x, y)\text{ [m]}$$
- **Touchdown Condition**:
  Spacecraft touchdown occurs when $h_{clearance} \le 0\text{ m}$.

---

## 4. Vizard 3D Terrain Mesh Format (`vizard/terrain_<region>.obj`)

Wavefront OBJ mesh standard for Basilisk Vizard 3D visualization:
- **Geometry Coordinates**: $X$ (East, m), $Y$ (North, m), $Z$ (Elevation $h_{ground} \times \text{vertical\_exaggeration}$, m).
- **Vertical Exaggeration**: Default $1.0\times$ (true scale), clearly labelled in OBJ header comments.
- **Normals**: Vertex normals calculated from local terrain gradients for smooth lighting in Vizard.
- **Texture Coordinates**: Normalized UV coordinates in $[0.0, 1.0]$.
