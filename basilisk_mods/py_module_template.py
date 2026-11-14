"""TEMPLATE — copy this file to make a new Basilisk Python module. No C++ needed.

How a Python module works:
  * subclass sysModel.SysModel
  * declare input readers (messaging.<Type>MsgReader) and output messages (messaging.<Type>Msg)
  * Reset(t_ns) runs once at InitializeSimulation(); UpdateState(t_ns) runs every task step
  * add it to a task:  sim.AddModelToTask("fswTask", module)
  * connect messages:  module.scStateInMsg.subscribeTo(spacecraft.scStateOutMsg)

Find message types in the Basilisk docs ("Message Definitions") — e.g. SCStatesMsgPayload has
r_BN_N, v_BN_N, sigma_BN, omega_BN_B.

This example: an altitude watcher that reads the spacecraft state and publishes nothing,
but keeps the latest altitude + a flag other code can read.
"""

from __future__ import annotations

import numpy as np
from Basilisk.architecture import messaging, sysModel
from Basilisk.utilities import macros

R_MOON_M = 1737.4e3


class AltitudeWatcher(sysModel.SysModel):
    def __init__(self, alarm_altitude_m: float = 100.0):
        super().__init__()
        self.ModelTag = "altitudeWatcher"
        # inputs
        self.scStateInMsg = messaging.SCStatesMsgReader()
        # settings
        self.alarm_altitude_m = alarm_altitude_m
        # results other code may read
        self.altitude_m = float("nan")
        self.alarm = False

    def Reset(self, CurrentSimNanos):
        if not self.scStateInMsg.isLinked():
            self.bskLogger.bskLog(sysModel.BSK_ERROR, "AltitudeWatcher.scStateInMsg is not linked")

    def UpdateState(self, CurrentSimNanos):
        state = self.scStateInMsg()                      # read the latest message payload
        r = np.array(state.r_BN_N)
        self.altitude_m = float(np.linalg.norm(r) - R_MOON_M)
        self.alarm = self.altitude_m < self.alarm_altitude_m
        if self.alarm:
            t = CurrentSimNanos * macros.NANO2SEC
            self.bskLogger.bskLog(sysModel.BSK_INFORMATION, f"t={t:.1f}s altitude {self.altitude_m:.1f} m")
