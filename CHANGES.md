# CHANGES.md -- New-World Day Epoch Updates

This repository is based on [AVSLab/Basilisk](https://github.com/AVSLab/basilisk).
Simulation start epochs have been updated to the current real-world date: 2026 November 14.

All changes are confined to examples/ scenario files only. No core modules were touched.

## Updated Scenario Files (27 files)

| File | Old Epoch | New Epoch |
|------|-----------|-----------|
| scenarioOrbitManeuver.py | 2024 September 21 TDB | 2026 November 14 TDB |
| scenarioOrbitMultiBody.py | 2012 MAY 1 | 2026 NOV 14 |
| scenarioPowerDemo.py | 2021 MAY 04 UTC | 2026 NOV 14 UTC |
| scenarioQuadMaps.py | 2000 November 26 TDB | 2026 November 14 TDB |
| scenarioRendezVous.py | 2022 MAY 1 | 2026 NOV 14 |
| scenarioRoboticArm.py | 2012 MAY 1 | 2026 NOV 14 |
| scenarioImpact.py | 2012 MAY 1 | 2026 NOV 14 |
| scenarioSatelliteConstellation.py | 2029 June 12 | 2026 November 14 |
| scenarioSepMomentumManagement.py | 2023 OCTOBER 22 | 2026 NOVEMBER 14 |
| scenarioSpiceSpacecraft.py | 2015 February 10 TDB | 2026 November 14 TDB |
| scenarioMomentumDumping.py | 2022 JUNE 27 | 2026 NOVEMBER 14 |
| scenarioLagrangePointOrbit.py | 2022 August 31 | 2026 November 14 |
| scenarioHohmann.py | 2021 MAY 04 UTC | 2026 NOV 14 UTC |
| scenarioOrbitConsistencyVerification.py | 2020 DEC 04 | 2026 NOV 14 |
| scenarioSpiceReconstruction.py | 2025 NOVEMBER 15 | 2026 NOVEMBER 14 |
| scenarioVestaOrientation.py | 2025 NOVEMBER 15 | 2026 NOVEMBER 14 |
| scenarioVizPoint.py | 2018 OCT 23 UTC | 2026 NOV 14 UTC |
| scenarioAerocapture.py | 2020 MAY 21 UTC | 2026 NOV 14 UTC |
| scenarioStochasticDragSpacecraft.py | 2020 MAY 21 UTC | 2026 NOV 14 UTC |
| scenarioTAM.py | 2019 June 27 UTC | 2026 November 14 UTC |
| scenarioTAMcomparison.py | 2019 June 27 UTC | 2026 November 14 UTC |
| scenarioMtbMomentumManagement.py | 2019 June 27 UTC | 2026 November 14 UTC |
| scenarioMtbMomentumManagementSimple.py | 2019 June 27 UTC | 2026 November 14 UTC |
| scenarioMagneticFieldWMM.py | 2019 June 27 UTC | 2026 November 14 UTC |
| scenarioAsteroidArrival.py | 2011 January 1 | 2026 November 14 |
| scenarioHelioTransSpice.py | 2028 February 24 | 2026 November 14 |
| scenarioFlybySpice.py | 2028/2029/2031 per planet | 2026 equivalents |

## Unchanged (intentional)
- scenarioOrbitFromOmm.py -- epoch is read dynamically from live OMM records.

## Notes
- Each changed line is tagged: # Updated: new-world day (2026-11-14)
- WMM magnetic model is valid through 2030; 2026 epoch is fully covered.
