# navigator/

**Owner:** Nimansh · **Jira:** KAN-35 / KAN-36 (tests)

Streamlit app (port 8501) that answers the challenge brief: where and when can a lander keep **sunlight** and a **radio
link to Earth**? Exact physics only, no AI. Compare up to 4 site + date combinations, with countdowns, a lunar-day
timeline, the sky over the real terrain horizon, and the terrain / hazard map.

```bash
pip install -e ".[apps,hazard,dev]"
python -I -m data_tools.make_demo_light      # GENERATED stand-in light data (until Imok's real KAN-23 files exist)
streamlit run navigator/app.py --server.port 8501
```

| | |
|---|---|
| Reads | `data/light/<region>_<date>_points.npz` (light contract v2 `PointSeries`), `data/tiles/<region>.npz`, `sites/sites.json` (optional) |
| Writes | Screens only |

| File | What |
|---|---|
| `metrics.py` | Sun up / Earth up / blackout hours, longest darkness, countdowns (sunset, Earthset, ...). Pure numpy |
| `data.py` | Finds light files, site names |
| `figures.py` | Timeline, sky panorama + dome, comparison bars, terrain map (Plotly) |
| `app.py` | The Streamlit app |

**Definitions** (see `metrics.py`): *Sun up* = `sun_fraction > 0`. *Earth up* = Earth elevation above the terrain horizon in
Earth's azimuth (`horizon_elev_deg`). *Blackout* = neither. Countdowns have the file's 1 h resolution.

**Honest limits.** Today's light files are a GENERATED analytic stand-in (arbitrary phases, not SPICE, not checked
against JPL Horizons) and the banner says so on screen. Horizons only reach the edge of a 5 km terrain window. Ice and
PSR layers are UNKNOWN until KAN-39. Azimuth is in the terrain-tile frame, not true north.

Rules: talk to other folders only through the files in `contracts/`; label outputs observed/modelled/generated/unknown;
physics backup before AI. See `docs/SYSTEM_DESIGN.md`.
