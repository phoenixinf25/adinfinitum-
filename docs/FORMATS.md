# Data Formats Specification

This document defines the standard data interfaces and telemetry schemas across the Adinfinitum lunar simulation pipeline.

---

## 1. Lunar Descent Telemetry CSV (`runs/basilisk/telemetry_<id>.csv`)

Generated each second ($1\text{ Hz}$) by `scenario_descent.py` / `basilisk_mods/lander_descent.py`. Consumed by Mission Control telemetry monitors.

### Column Definitions

| Column | Type | Unit | Description |
| :--- | :--- | :--- | :--- |
| `time` | Float | `s` | Mission Elapsed Time from Powered Descent Initiation ($t=0$ at PDI) |
| `altitude_m` | Float | `m` | Altitude above lunar terrain surface ($R - R_{moon}$) |
| `v_vertical_mps` | Float | `m/s` | Velocity along local vertical (negative = descending, positive = ascending) |
| `v_horizontal_mps` | Float | `m/s` | Horizontal ground speed relative to lunar surface |
| `total_velocity_mps` | Float | `m/s` | Total magnitude of inertial velocity $\sqrt{v_x^2 + v_y^2 + v_z^2}$ |
| `fuel_mass_kg` | Float | `kg` | Remaining usable propellant mass inside the lander tanks |
| `thrust_1_N` | Float | `N` | Actual thrust output of Engine 1 (Center Thruster) |
| `thrust_2_N` | Float | `N` | Actual thrust output of Engine 2 (Outer +X Thruster) |
| `thrust_3_N` | Float | `N` | Actual thrust output of Engine 3 (Outer -X Thruster) |
| `thrust_4_N` | Float | `N` | Actual thrust output of Engine 4 (Outer +Y Thruster) |
| `thrust_5_N` | Float | `N` | Actual thrust output of Engine 5 (Outer -Y Thruster) |
| `total_thrust_N` | Float | `N` | Total combined thrust force delivered by all active engines |
| `tilt_deg` | Float | `deg` | Body axis tilt angle relative to local vertical ($0^\circ$ = upright) |
| `phase` | String | - | Guidance phase: `MAIN_BRAKING`, `COARSE_APPROACH`, `VERTICAL_HOVER`, `TERMINAL_DESCENT`, `TOUCHDOWN` |
| `decision` | String | - | Guidance decision/engine health: `NOMINAL_5_ENGINE_FIRING`, `ENGINE_OUT_COMPENSATION`, `TOUCHDOWN_SUCCESS`, `TOUCHDOWN_FAILED` |

### Touchdown Criteria Limits (from `config/mission.yaml`)
* **Vertical Speed:** $\le 2.0\text{ m/s}$
* **Horizontal Speed:** $\le 0.5\text{ m/s}$
* **Tilt Angle:** $\le 12.0^\circ$

---

## 2. Powered Descent Initiation State (`runs/basilisk/pdi_state.json`)

Saved at periapsis by `basilisk_mods/scenario_orbit_release.py`.

```json
{
  "mission": "Adinfinitum Lunar Lander",
  "event": "Powered Descent Initiation (PDI)",
  "time_epoch_sec": 5211.84,
  "time_from_burn_sec": 3411.84,
  "periapsis_altitude_km": 15.0,
  "spacecraft_mass_kg": 800.0,
  "position_inertial_m": [48127.5, 0.0, -1751739.4],
  "velocity_inertial_mps": [1691.69, 0.0, 46.73],
  "target_region": { "name": "Shackleton Crater Rim", "lat_deg": -89.66, "lon_deg": 129.2 },
  "delta_v_deorbit_mps": 19.45,
  "vizard_file": "runs/basilisk/scenario_orbit_release_UnityViz.bin"
}
```
