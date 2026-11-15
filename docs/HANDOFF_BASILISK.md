# JAX Swarm Optimizer to Basilisk Handoff Specification

**Document Version:** 1.0  
**Context:** NASA Space Apps Challenge 2026 - Project Adinfinitum (Spec §7.2, §10)  
**Author:** Flight Dynamics & Swarm Optimization Team  
**Intended Consumers:** `basilisk_mods/refly_champion.py`, Basilisk simulation pipeline, Mission Control  

---

## 1. Overview & Architectural Role

In the Adinfinitum lunar landing pipeline, trajectory optimization is performed using a high-throughput, GPU-accelerated **JAX Swarm Simulator**. The JAX simulator evaluates thousands of candidate descent trajectories using GPU-parallelized differential evolution and PPO/swarm policy refinement over a local topocentric frame.

Once the optimizer identifies champion trajectories (Pareto-optimal in propellant mass, divert capability, and landing precision), they are exported as JSON profiles in `runs/swarm/champion_XXX.json`.

These champion profiles are subsequently **handed off to Basilisk** for high-precision 6-DOF / 3-DOF verification in a Moon-centered inertial frame with full planetary ephemeris, non-spherical gravity potentials, and continuous thruster/fuel tank dynamics.

```
+---------------------------+       champion_XXX.json        +---------------------------+
|    JAX Swarm Optimizer    |  ============================> |  Basilisk High-Fidelity   |
| (Local Topocentric Frame, |    Throttles, Attitude,        | (Moon-Centered Inertial,  |
|  GPU parallel batched sim)|    Initial State, Injections   |  Continuous Dynamics)     |
+---------------------------+                                +---------------------------+
                                                                           |
                                                                           v
                                                             +---------------------------+
                                                             |   runs/basilisk/compare   |
                                                             |   docs/VALIDATION.md      |
                                                             |   Honest Physical Delta   |
                                                             +---------------------------+
```

---

## 2. Coordinate Frame Conversions

### 2.1 Coordinate Definitions

1. **JAX Frame (Local Topocentric East-North-Up / ENU):**
   - Origin: Touchdown target on lunar surface at $(\phi_0, \lambda_0)$ (e.g., Shackleton Crater Rim: $\phi_0 = -89.66^\circ, \lambda_0 = 129.20^\circ, R_{moon} = 1,737,400\text{ m}$).
   - $\hat{\mathbf{x}}_{jax}$ (East): Tangent to lunar parallel pointing East.
   - $\hat{\mathbf{y}}_{jax}$ (North): Tangent to lunar meridian pointing North.
   - $\hat{\mathbf{z}}_{jax}$ (Up): Local surface normal (zenith) pointing radially away from Moon center.

2. **Basilisk Frame (Moon-Centered Inertial Frame $MCI$):**
   - Origin: Center of mass of the Moon.
   - $\hat{\mathbf{X}}_I$: Direction of J2000 Moon vernal equinox / reference longitude at epoch $t_0$.
   - $\hat{\mathbf{Z}}_I$: Moon spin axis (lunar north pole).
   - $\hat{\mathbf{Y}}_I = \hat{\mathbf{Z}}_I \times \hat{\mathbf{X}}_I$: Completes right-handed Cartesian coordinate system.

### 2.2 Mathematical Transformation

Given target surface latitude $\phi_0$ and longitude $\lambda_0$, the target position in Moon-fixed frame is:

$$\mathbf{r}_{site} = R_{moon} \begin{bmatrix} \cos\phi_0 \cos\lambda_0 \\ \cos\phi_0 \sin\lambda_0 \\ \sin\phi_0 \end{bmatrix}$$

The rotation matrix $\mathbf{R}_{enu \to mci}$ converting local ENU unit vectors into Moon-centered coordinates is:

$$\mathbf{R}_{enu \to mci} = \begin{bmatrix}
-\sin\lambda_0 & -\sin\phi_0 \cos\lambda_0 & \cos\phi_0 \cos\lambda_0 \\
\cos\lambda_0  & -\sin\phi_0 \sin\lambda_0 & \cos\phi_0 \sin\lambda_0 \\
0                 & \cos\phi_0                 & \sin\phi_0
\end{bmatrix}$$

#### Position Conversion:
$$\mathbf{r}_{mci}(t) = \mathbf{r}_{site} + \mathbf{R}_{enu \to mci} \, \mathbf{r}_{jax}(t)$$

#### Velocity Conversion:
Accounting for lunar sidereal angular velocity $\mathbf{\omega}_{moon} = [0, 0, 2.6617 \times 10^{-6}]^T\text{ rad/s}$:
$$\mathbf{v}_{mci}(t) = \mathbf{R}_{enu \to mci} \, \mathbf{v}_{jax}(t) + \mathbf{\omega}_{moon} \times \mathbf{r}_{mci}(t)$$

#### Commanded Thrust Direction Conversion:
Given normalized thrust unit vector $\mathbf{u}_{thrust, jax} = [u_x, u_y, u_z]^T$:
$$\mathbf{u}_{thrust, mci} = \mathbf{R}_{enu \to mci} \, \mathbf{u}_{thrust, jax}$$

---

## 3. Champion JSON Data Schema (`runs/swarm/champion_XXX.json`)

Each exported champion file adheres strictly to the following specification:

| Field | Type | Description |
| :--- | :--- | :--- |
| `version` | string | Format version (e.g. `1.0.0`) |
| `champion_id` | string | Unique champion identifier (`champion_001`, `champion_002`, `champion_003`) |
| `mission` | string | Mission title (`Adinfinitum Lunar Lander`) |
| `type` | string | Trajectory type (`nominal`, `divert`, `engine_out`) |
| `description` | string | Human readable profile description |
| `dt_sec` | float | Control sample period (default: `0.5` seconds) |
| `target` | object | Target coordinates: `name`, `lat_deg`, `lon_deg`, `radius_m` |
| `initial_state` | object | Initial conditions at PDI: `pos_jax_m`, `vel_jax_mps`, `pos_mci_m`, `vel_mci_mps`, `fuel_mass_kg`, `dry_mass_kg` |
| `failure_injection`| object/null | Simulated hardware failure (e.g., `{"failed_engine": 2, "time_sec": 120.0}`) |
| `jax_metrics` | object | Benchmark results computed in JAX simulator |
| `control_log` | array | High-resolution array of commands: `time_sec`, `throttles` [5], `attitude_u_jax`, `attitude_u_mci` |

---

## 4. Open-Loop Replay Protocol

To test the physical validity of trajectories optimized in JAX:
1. `basilisk_mods/refly_champion.py` initializes the Basilisk lander model with `initial_state.pos_mci_m`, `initial_state.vel_mci_mps`, and `initial_state.fuel_mass_kg`.
2. At every integration time step $t$, the replay module interpolates `throttles` and `attitude_u_mci` from the `control_log`.
3. If `failure_injection` is defined (e.g., `failed_engine: 2` at `time_sec: 120.0`), the simulator forces the specified thruster to 0 thrust from that time onward.
4. **No closed-loop feedback or trajectory retuning is applied.** Basilisk integrates the actual 3-body / spherical gravity equations, exact mass depletion, and thruster dynamics open-loop.
5. The replay terminates at $alt \le 0\text{ m}$ (touchdown).
6. Output comparison metrics are saved to `runs/basilisk/compare_<id>.json` and documented in `docs/VALIDATION.md`.

---

## 5. Physical Modeling Differences (Honest Physics)

| Feature | JAX Swarm Simulator | Basilisk Engine Re-fly |
| :--- | :--- | :--- |
| **Coordinate Frame** | Local flat-Moon topocentric ENU | Moon-Centered Inertial (MCI) Cartesian |
| **Gravity Model** | Uniform spherical $g = \mu / R^2$ | Exact 3D inverse-square lunar central gravity |
| **Thruster Dynamics** | Instantaneous throttle hold $\Delta t$ | Dynamic effector with cant angles & continuous fuel burn |
| **Coriolis & Centrifugal** | Approximated or zero in local box | Exact full non-inertial kinematics in rotating lunar frame |
| **Integration Scheme** | Discrete fixed-step RK4 | Continuous Basilisk simulation executive |

Because of these honest physical differences, re-flying the open-loop control log will naturally show small discrepancies in touchdown velocity, final position, and fuel consumption. **Per project guidelines, Basilisk will not be artificially tuned to match JAX.**
