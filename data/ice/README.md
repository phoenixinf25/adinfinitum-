# Lunar Ice-Target Data Layer Documentation

This dataset provides processed multi-instrument evidence layers for lunar water-ice prospecting,
conforming to polar-stereographic DEM tiles for mission planning and navigation (Spec §4.3).

---

## 1. Layers & Provenance

| Layer | Type | Provenance | Source / Instrument | Thresholds & Standards |
|---|---|---|---|---|
| `psr` | `bool` | `observed` | NASA GSFC PGDA `LPSR_80S_20MPP_ADJ_1km2` / LROC PSR Atlas | Permanently shadowed regions poleward of 80°S; areas ≥ 1 km² |
| `tmax` | `float32 (K)` | `observed` | LRO Diviner (DLRE) PDS Geosciences Node / Williams et al. (2019) | Maximum summer bolometric surface temperature |
| `cold_trap` | `bool` | `modelled` | Derived from Diviner $T_{max}$ | **$T_{max} < 110\text{ K}$** (Critical sublimation stability limit) |
| `neutron_h` | `float32 (0..1)` | `observed` | LRO LEND / Lunar Prospector LP-NS | Epithermal neutron suppression likelihood index |
| `m3_ice` | `float32 (0..1)` | `observed` / future | Moon Mineralogy Mapper (M3) / Li et al. (2018, PNAS) | Diagnostic 1.3, 1.5, 2.0 µm absorption bands |
| `ice_score` | `float32 (0..1)` | `modelled` | Weighted Composite Multi-Criteria Model | Documented weighted sum |
| `candidate_targets` | `bool` | `modelled` | Rover Mobility Constraint Filter | Top-scoring sites within **≤300 m** of sunlit terrain |

---

## 2. Thresholds and Physical Assumptions

### Cold Trap Definition ($T_{max} < 110\text{ K}$)
- Under lunar ultra-high vacuum conditions, the sublimation loss rate of exposed water ice depends exponentially on surface temperature:
  $$\dot{E} \propto \exp\left(-\frac{\Delta H}{R T}\right)$$
- At temperatures below **110 K**, the sublimation loss rate is less than 1 millimeter per billion years, permitting water ice to persist on geological timescales.
- Regions with $T_{max} \ge 110\text{ K}$ experience rapid volatile loss.

### Rover Operational Constraint (Traverse ≤ 300 m)
- Context: **Spec §4.3 Rover Mobility Model**.
- Rover class: ~25 kg (Pragyan / VIPER class) with solar array (~50 W) and internal battery.
- Nominal traverse speed: **~1 cm/s**. Over an operational day, total drive distance is limited to a few hundred meters.
- The rover operates from a sunlit landing site and performs short scientific "dips" into adjacent permanently shadowed cold traps on battery reserve before retreating to sunlight for recharge.
- Therefore, candidate ice drill targets are filtered to those located within **300 meters** of sunlit terrain (`dist_to_sunlit_m <= 300.0`).

### Ice Score Formulation
$$\text{ice\_score} = w_{\text{psr}} \cdot \text{psr} + w_{\text{cold}} \cdot \text{cold\_trap} + w_{\text{h}} \cdot \text{neutron\_h} + w_{\text{m3}} \cdot \text{m3\_ice}$$

Configured Weights:
- $w_{\text{psr}} = 0.40$
- $w_{\text{cold}} = 0.35$
- $w_{\text{h}} = 0.25$
- $w_{\text{m3}} = 0.00$ (*future expansion*)

---

## 3. Strict Phrasing Guidelines

> [!IMPORTANT]
> Orbital remote sensing provides surface temperatures, shadow boundaries, and neutron suppression data.
> **Never claim "ice is here"**.
> All documentation, UI displays, and navigator logs must use **"ice evidence"** or **"ice-favourable indicators"**.

---

## 4. File Outputs
- `data/ice/<region>_ice.npz`: Complete raster layers and metadata aligned to the tile polar stereographic grid.
- `data/ice/psr_outlines.geojson`: Vector GeoJSON polygon boundaries of permanently shadowed regions.
- `data/ice/<region>_ice_preview.png`: 4-panel diagnostic visualization.
