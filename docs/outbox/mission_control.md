# Mission Control → orchestrator: questions to make Basilisk run live

Date: 2026-11-14. From: the Mission Control / 3D showcase session (Ojas's Mac, Basilisk fork
`phoenixinf25/adinfinitum-`, branch `feat/mission-control-2d`).

## Goal (decided by the user)

One live run: **Basilisk simulates orbit → deorbit → powered descent in real time**, streamed at the same
time to **Vizard** and to our **web 3D view + Mission Control** (side by side). After touchdown the rover
simulation takes over. Judges get a video only, so nothing needs hosting.

## What already works here

- bsk **2.12.2** (pip wheel, macOS arm64) and **Vizard 2.4** run on this Mac.
- The team's models `lander_B.glb`, `rover_B.glb`, `propulsion_module_B.glb` load in Vizard (converted to
  OBJ, Z up, front +x) and in the web 3D view.
- Mission Control accepts live telemetry on `ws://<host>:8600/ws/ingest` (`world` / `frame` messages; format
  in `lunar_ops/PROTOCOL.md`, sections 1–1d). The `lander` block matches `TELEMETRY_COLUMNS` of
  `contracts/runs.py` as far as we know.
- Vizard 2.4 + bsk 2.12 cannot draw a Moon-only scene (it errors in `GetAbsolutePlanetPositionUnityCS`);
  adding the Earth with a fixed ephemeris message fixes it.

## Questions (blocking)

1. **Where is the descent scenario?** Repo, branch and commit of `basilisk_mods/scenario_descent.py` (and
   the orbit/deorbit scenario, KAN-41/42). Which bsk version does it need?
2. **Start and end states.** Our recorded CSV starts at 1,955 m. Does Basilisk also fly the braking phase from
   the 15 km periapsis, or does the descent start at ~2 km? What ends the run (touchdown event, alt < x)?
3. **Can it run step by step in real time?** We would call `ExecuteSimulation` in small slices (or use
   `liveStream=True`) and read states each slice. Anything in it that blocks that (e.g. post-processing
   at the end, plotting)?
4. **Which outputs can we read each step?** We need position and velocity (which frame?), attitude, mass,
   fuel, thrust per engine, engines working, and the engine-failure time and indices.
5. **Coordinates.** How do Basilisk positions map to the tile frame (x east, y north, metres from the tile
   centre)? Which site and tile does the descent target: Site01 (our sample) or Site23 (master plan)?
6. **Thruster layout.** Engine positions and directions, and which engine fails / which is shut down for
   balance, so the 3D view shows the right flames on the right nozzles of `lander_B`.
7. **Models.** Are `lander_B`, `rover_B` and `propulsion_module_B` final? Is the propulsion module part of the
   real concept (lander docked on it in orbit, separating before deorbit)?
8. **Rover after touchdown.** Is there a rover policy (PPO driver or a baseline) we should plug into
   `/ws/agent`, or do we keep the built-in baseline for the live demo?
9. **Branch.** Which branch should this live integration go to (we never commit to `main`)?

## Not blocking, but useful

- The intended mission epoch (date/time), so Sun and Earth directions come from SPICE instead of fixed values.
- Expected real-time factor for the demo (1×, 10×, 60×).
