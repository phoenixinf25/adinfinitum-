#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Show the three Adinfinitium vehicle models in Vizard.

Three spacecraft (lander, rover, propulsion module) fly side by side in a 100 km circular lunar orbit, each spinning
slowly about its own vertical axis so that every side faces the camera. Each one is drawn with its own custom OBJ model
(see ``glb_to_obj.py``). The run writes a Vizard playback file to ``_VizFiles/`` next to this script.

Everything here is MODELLED (simulated). The orbit is only a convenient place to show the models, not a mission design.

Run (needs ``bsk`` 2.12 or newer)::

    python scenario_vehicle_models.py
    open /Applications/Vizard.app --args -loadFile <path printed at the end>
"""

from pathlib import Path

from Basilisk.simulation import spacecraft
from Basilisk.utilities import SimulationBaseClass, macros, orbitalMotion, simIncludeGravBody, vizSupport

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
MOON_RADIUS_M = 1737.4e3  # [m] mean lunar radius
ALTITUDE_M = 100.0e3  # [m] circular orbit altitude
SPIN_RATE_RAD_S = 0.04  # [rad/s] spin about the body z (up) axis
SIM_TIME_S = 160.0  # [s] about one full turn at the spin rate above
STEP_S = 0.1  # [s] integration step
# name, model file, in-track offset from the orbit point [m]. The spacing keeps the 8 m wide models from overlapping.
VEHICLES = [("lander", "lander_B.obj", 0.0), ("rover", "rover_B.obj", 14.0), ("propulsion_module", "propulsion_module_B.obj", -16.0)]


def run() -> Path:
    """Run the scenario and return the path of the Vizard playback file."""
    sim = SimulationBaseClass.SimBaseClass()
    process = sim.CreateNewProcess("simProcess")
    process.addTask(sim.CreateNewTask("simTask", macros.sec2nano(STEP_S)))

    gravity = simIncludeGravBody.gravBodyFactory()
    moon = gravity.createMoon()
    moon.isCentralBody = True

    elements = orbitalMotion.ClassicElements()
    elements.a = MOON_RADIUS_M + ALTITUDE_M
    elements.e = 0.0
    elements.i = 90.0 * macros.D2R
    elements.Omega = 0.0
    elements.omega = 0.0
    elements.f = 0.0
    r_N, v_N = orbitalMotion.elem2rv(moon.mu, elements)

    craft = []
    for name, _, offset_m in VEHICLES:
        sc = spacecraft.Spacecraft()
        sc.ModelTag = name
        sc.hub.mHub = 750.0  # [kg]
        sc.hub.IHubPntBc_B = [[900.0, 0.0, 0.0], [0.0, 800.0, 0.0], [0.0, 0.0, 600.0]]  # [kg m^2]
        sc.hub.r_CN_NInit = [r_N[0] + offset_m, r_N[1], r_N[2]]  # [m]
        sc.hub.v_CN_NInit = v_N  # [m/s]
        sc.hub.sigma_BNInit = [[0.0], [0.0], [0.0]]  # [-] MRP
        sc.hub.omega_BN_BInit = [[0.0], [0.0], [SPIN_RATE_RAD_S]]  # [rad/s]
        gravity.addBodiesTo(sc)
        sim.AddModelToTask("simTask", sc)
        craft.append(sc)

    viz = vizSupport.enableUnityVisualization(sim, "simTask", craft, saveFile=str(HERE / Path(__file__).name))
    for name, model, _ in VEHICLES:
        vizSupport.createCustomModel(viz, modelPath=str(ASSETS / model), simBodiesToModify=[name])

    sim.InitializeSimulation()
    sim.ConfigureStopTime(macros.sec2nano(SIM_TIME_S))
    sim.ExecuteSimulation()
    return HERE / "_VizFiles" / f"{Path(__file__).stem}_UnityViz.bin"


if __name__ == "__main__":
    print(run())
