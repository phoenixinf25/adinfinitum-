# Drop your vehicle models here

The UI loads these automatically if present (otherwise it shows labelled markers):

| File | Used for |
|---|---|
| `lander.glb` (or `lander.obj`) | lander in orbit, descent and on the surface |
| `rover.glb` (or `rover.obj`) | rover on the surface |
| `models.json` (optional) | `{"lander": {"scale": 1.0, "rotation_deg": [0,0,0]}, "rover": {"scale": 1.0, "rotation_deg": [0,0,0]}}` |

Model axes: +Y up, the vehicle's front points to -Z. Real size: lander about 3 m, rover about 1 m;
the UI scales it up automatically when viewed from far away.
Tripo exports GLB: use that format.
