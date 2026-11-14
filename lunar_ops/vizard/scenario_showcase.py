#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Vizard showcase: the lander docked on the propulsion module in lunar orbit, then separating.

Two spacecraft share one 100 km polar lunar orbit. The lander starts docked on top of the propulsion module (body +z)
and leaves it with a small push of ``SEPARATION_SPEED_M_S`` along +z, so the stack visibly comes apart. Both are drawn
with the team's own models (``assets/*.obj``, made by ``glb_to_obj.py``) instead of Vizard's default spacecraft.

Vizard 2.4 with bsk 2.12 cannot draw a Moon-centred scene unless another planet with an ephemeris is present, so the
Earth is added at its mean distance with a fixed state message. It does not pull on the spacecraft here.

Everything shown is MODELLED (simulated): this is a visual of the vehicles, not a flown separation manoeuvre.

Run (needs ``bsk`` 2.12 or newer)::

    python scenario_showcase.py
    open /Applications/Vizard.app --args -loadFile <path printed at the end>
"""

from pathlib import Path

from Basilisk.architecture import messaging
from Basilisk.simulation import spacecraft
from Basilisk.utilities import SimulationBaseClass, macros, orbitalMotion, simIncludeGravBody, vizSupport

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
MOON_RADIUS_M = 1737.4e3  # [m] mean lunar radius
ALTITUDE_M = 100.0e3  # [m] circular orbit altitude
EARTH_DISTANCE_M = 384400.0e3  # [m] mean Earth-Moon distance
DOCK_OFFSET_M = 1.66  # [m] lander centre above the propulsion-module centre when docked (model geometry)
SEPARATION_SPEED_M_S = 0.06  # [m/s] relative push along +z at separation
SIM_TIME_S = 240.0  # [s] scenario length
STEP_S = 0.25  # [s] integration step
_keep = []  # message payload objects must outlive the simulation


def run() -> Path:
    """Run the scenario and return the path of the Vizard playback file."""
    sim = SimulationBaseClass.SimBaseClass()
    process = sim.CreateNewProcess("simProcess")
    process.addTask(sim.CreateNewTask("simTask", macros.sec2nano(STEP_S)))

    gravity = simIncludeGravBody.gravBodyFactory()
    moon = gravity.createMoon()
    moon.isCentralBody = True
    earth = gravity.createEarth()
    state = messaging.SpicePlanetStateMsgPayload()
    state.PlanetName = "earth"
    state.PositionVector = [EARTH_DISTANCE_M, 0.0, 0.0]  # [m]
    state.J20002Pfix = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]  # [-]
    earth_msg = messaging.SpicePlanetStateMsg().write(state)
    earth.planetBodyInMsg.subscribeTo(earth_msg)
    _keep.extend([state, earth_msg])

    elements = orbitalMotion.ClassicElements()
    elements.a = MOON_RADIUS_M + ALTITUDE_M  # [m]
    elements.e = 0.0
    elements.i = 90.0 * macros.D2R  # [rad]
    elements.Omega = 0.0  # [rad]
    elements.omega = 0.0  # [rad]
    elements.f = 0.0  # [rad]
    r_N, v_N = orbitalMotion.elem2rv(moon.mu, elements)

    def vehicle(name: str, mass_kg: float, dz_m: float, dvz_m_s: float) -> spacecraft.Spacecraft:
        sc = spacecraft.Spacecraft()
        sc.ModelTag = name
        sc.hub.mHub = mass_kg  # [kg]
        sc.hub.IHubPntBc_B = [[900.0, 0.0, 0.0], [0.0, 800.0, 0.0], [0.0, 0.0, 600.0]]  # [kg m^2]
        sc.hub.r_CN_NInit = [r_N[0], r_N[1], r_N[2] + dz_m]  # [m]
        sc.hub.v_CN_NInit = [v_N[0], v_N[1], v_N[2] + dvz_m_s]  # [m/s]
        gravity.addBodiesTo(sc)
        sim.AddModelToTask("simTask", sc)
        return sc

    stage = vehicle("propulsion_module", 1400.0, 0.0, 0.0)
    lander = vehicle("lander", 900.0, DOCK_OFFSET_M, SEPARATION_SPEED_M_S)

    viz = vizSupport.enableUnityVisualization(sim, "simTask", [lander, stage], saveFile=str(HERE / Path(__file__).name))
    vizSupport.createCustomModel(viz, modelPath=str(ASSETS / "lander_B.obj"), simBodiesToModify=["lander"])
    vizSupport.createCustomModel(viz, modelPath=str(ASSETS / "propulsion_module_B.obj"), simBodiesToModify=["propulsion_module"])
    s = viz.settings
    s.mainCameraTarget = "lander"
    s.forceStartAtSpacecraftLocalView = 1
    s.ambient = 0.18  # [-] fill light so shadowed sides keep some detail
    s.sunIntensity = 1.4  # [-]
    s.spacecraftShadowBrightness = 0.25  # [-]
    s.orbitLinesOn = -1
    s.trueTrajectoryLinesOn = -1
    s.showSpacecraftLabels = 1
    s.showCelestialBodyLabels = -1
    s.showMissionTime = 1
    s.showDataRateDisplay = -1

    sim.InitializeSimulation()
    sim.ConfigureStopTime(macros.sec2nano(SIM_TIME_S))
    sim.ExecuteSimulation()
    return HERE / "_VizFiles" / f"{Path(__file__).stem}_UnityViz.bin"


if __name__ == "__main__":
    print(run())
