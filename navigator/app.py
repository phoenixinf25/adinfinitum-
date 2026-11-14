"""Lunar Landing Site Navigator (KAN-35). Streamlit, port 8501:

    streamlit run navigator/app.py --server.port 8501

Compares landing sites and dates on Sun, Earth contact (radio) and darkness, with countdowns, a lunar-day timeline
and a sky view over the real terrain horizon. Exact physics only: no AI is needed to answer the brief.
Reads only files in the contract formats: data/light/*_points.npz, data/tiles/*.npz, sites/sites.json.
"""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from contracts.provenance import Provenance
from navigator import figures as fig
from navigator.data import Entry, display_name, latlon, list_entries, load_tile_or_none, site_names
from navigator.metrics import earth_countdown, earth_up, format_hours, step_hours, summarize, sun_countdown

MAX_COMPARE = 4

st.set_page_config(page_title="Lunar Landing Site Navigator", page_icon="🌙", layout="wide")


@st.cache_resource(show_spinner=False)
def _series(path: str):
    from pathlib import Path

    from contracts.light import load_points
    return load_points(Path(path))


@st.cache_resource(show_spinner=False)
def _tile(region: str):
    return load_tile_or_none(region)


def _banner(prov: Provenance) -> str:
    return {Provenance.GENERATED: ":red[**GENERATED — NOT OBSERVED**]", Provenance.MODELLED: ":orange[**MODELLED**]",
            Provenance.OBSERVED: ":green[**OBSERVED**]", Provenance.UNKNOWN: ":gray[**UNKNOWN**]"}[prov]


entries = list_entries()
if not entries:
    st.title("🌙 Lunar Landing Site Navigator")
    st.error("No light data found in `data/light/`. Create the stand-in files with "
             "`python -m data_tools.make_demo_light` (needs tiles in `data/tiles/`), or copy Imok's real files there.")
    st.stop()

names = site_names()
label_of: dict[str, Entry] = {}
for e in entries:
    lab = f"{display_name(e.region, _tile(e.region), names)} · window from {e.date}"
    if lab in label_of:                      # two regions with the same display name must not hide each other
        lab = f"{display_name(e.region, _tile(e.region), names)} [{e.region}] · window from {e.date}"
    label_of[lab] = e

with st.sidebar:
    st.header("Choose sites and dates")
    defaults, seen = [], set()
    for lab, e in label_of.items():
        if e.region not in seen and len(defaults) < MAX_COMPARE:
            defaults.append(lab)
            seen.add(e.region)
    chosen = st.multiselect(f"Up to {MAX_COMPARE} site + date combinations", list(label_of), default=defaults, max_selections=MAX_COMPARE)
    first = _series(str(label_of[chosen[0]].path)) if chosen else None
    n_steps = len(first.times_utc) if first else 709
    clock = st.slider("Time into the window (hours)", 0, int((n_steps - 1) * (step_hours(first) if first else 1.0)),
                      0, step=int(step_hours(first)) if first else 1,
                      help="Every date starts at hour 0. The window is one lunar day + night (29.5 days).")
    st.caption("Sun and Earth positions are for the chosen hour in every combination.")
    explainer = st.toggle("Plain-language explanations", value=True)

st.title("🌙 Lunar Landing Site Navigator")
st.caption("Where and when can a lander keep sunlight and a radio link to Earth? Compare sites and dates, then watch the sky.")

if not chosen:
    st.info("Pick at least one site and date in the sidebar.")
    st.stop()

combos = []
for lab in chosen:
    e = label_of[lab]
    ps = _series(str(e.path))
    combos.append({"label": lab, "entry": e, "ps": ps, "tile": _tile(e.region)})

provs = {c["ps"].meta.provenance for c in combos}
if Provenance.GENERATED in provs:
    st.warning("**GENERATED — NOT OBSERVED.** The Sun and Earth positions on this screen are an analytic stand-in "
               "(not SPICE, not checked against JPL Horizons) and the horizon only reaches the edge of a 5 km terrain window. "
               "Use it to explore the tool, not to plan a mission. Real data replaces it when the light-field files (KAN-23) arrive.", icon="⚠️")

i_now = min(int(clock // step_hours(combos[0]["ps"])), n_steps - 1)

tab_cmp, tab_time, tab_sky, tab_terrain, tab_about = st.tabs(
    ["Compare", "Timeline and countdowns", "Sky over the horizon", "Terrain and ice", "About the data"])

# ------------------------------------------------------------------------------------------------ Compare
with tab_cmp:
    rows = []
    for c in combos:
        s = summarize(c["ps"])
        rows.append({"label": c["label"], "Sun hours": s.sun_hours, "Earth hours": s.earth_hours, "Both hours": s.both_hours,
                     "Blackout hours": s.blackout_hours, "summary": s})
    table = pd.DataFrame({
        r["label"]: {
            "Data": c["ps"].meta.provenance.banner,
            "Sun up (hours)": round(r["summary"].sun_hours),
            "Earth visible (hours)": round(r["summary"].earth_hours),
            "Sun and Earth together (hours)": round(r["summary"].both_hours),
            "Blackout: no Sun, no Earth (hours)": round(r["summary"].blackout_hours),
            "Longest darkness (hours)": f"{r['summary'].longest_dark_hours:.0f}" + ("+" if r["summary"].longest_dark_is_lower_bound else ""),
            "Longest blackout (hours)": round(r["summary"].longest_blackout_hours),
            "Mean Sun elevation while up (deg)": "never up" if r["summary"].mean_sun_elev_deg != r["summary"].mean_sun_elev_deg else round(r["summary"].mean_sun_elev_deg, 1),
            "Sunsets in window": r["summary"].n_sunsets,
            "Earthsets in window": r["summary"].n_earthsets,
        } for r, c in zip(rows, combos)
    })
    st.dataframe(table.astype(str), width="stretch")
    st.plotly_chart(fig.compare_bars(rows), width="stretch")
    if explainer:
        with st.expander("How to read this", expanded=True):
            st.markdown(
                "- **Sun up**: hours when any part of the Sun is above the terrain horizon. Solar panels need this.\n"
                "- **Earth visible**: hours when Earth is above the terrain horizon, so a lander antenna can talk to Earth directly.\n"
                "- **Blackout**: neither Sun nor Earth. The lander runs on battery and cannot call home.\n"
                "- **Longest darkness**: the longest unbroken stretch without sunlight; the battery and heater must last this long. "
                "A **+** means the stretch touches the edge of the 29.5-day window, so the real one may be longer.\n"
                "- Small changes in date can move these numbers a lot near the poles, where the Sun skims the horizon.\n"
                "- These are for the cell at the centre of each terrain window, with the horizon from real LOLA heights where available.")

# ------------------------------------------------------------------------------------------ Timeline + countdowns
with tab_time:
    st.caption(f"Hour {clock} of the window. Move the slider in the sidebar to change the moment; resolution is "
               f"{step_hours(combos[0]['ps']):.0f} h, so countdowns are 'by the next sample'.")
    cols = st.columns(len(combos))
    for col, c in zip(cols, combos):
        sc, ec = sun_countdown(c["ps"], i_now), earth_countdown(c["ps"], i_now)
        with col:
            st.markdown(f"**{c['label'].split(' · ')[0]}**  \n{c['entry'].date}")
            st.metric("Sun", "up" if sc.state == "up" else "down",
                      f"{sc.event} in {format_hours(sc.hours)}" if sc.event else "no change in window", delta_color="off")
            st.metric("Earth", "visible" if ec.state == "up" else "hidden",
                      f"{ec.event} in {format_hours(ec.hours)}" if ec.event else "no change in window", delta_color="off")
    for c in combos:
        st.plotly_chart(fig.timeline_figure(c["ps"], i_now, title=f"{c['label']}  ·  {c['ps'].meta.provenance.banner}"), width="stretch")

# ---------------------------------------------------------------------------------------------- Sky
with tab_sky:
    pick = st.selectbox("Site and date", [c["label"] for c in combos])
    c = next(x for x in combos if x["label"] == pick)
    ps = c["ps"]
    k = st.selectbox("Cell", list(range(len(ps.cells))), format_func=lambda j: "candidate landing cell" if j == 0 else f"neighbour {j}",
                     help="The candidate cell and its 8 neighbours, each with its own terrain horizon.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sun elevation", f"{ps.sun_elev_deg[i_now, k]:.1f}°")
    m2.metric("Sun visible", f"{ps.sun_fraction[i_now, k]:.0%}")
    m3.metric("Earth elevation", f"{ps.earth_elev_deg[i_now, k]:.1f}°")
    m4.metric("Earth line of sight", "yes" if earth_up(ps, k)[i_now] else "no")
    left, right = st.columns([3, 2])
    pano, dome = left.empty(), right.empty()
    pano.plotly_chart(fig.panorama_figure(ps, i_now, k, f"{pick}  ·  {ps.meta.provenance.banner}"), width="stretch")
    dome.plotly_chart(fig.dome_figure(ps, i_now, k, "Sky dome (top-down)"), width="stretch")
    if st.button("▶ Play the whole window"):
        for j in range(0, len(ps.times_utc), 12):
            pano.plotly_chart(fig.panorama_figure(ps, j, k, f"{pick}  ·  {ps.times_utc[j]}"), width="stretch", key=f"p{j}")
            dome.plotly_chart(fig.dome_figure(ps, j, k, "Sky dome (top-down)"), width="stretch", key=f"d{j}")
            time.sleep(0.05)
    if explainer:
        st.caption("Grey = terrain skyline seen from the site. At the poles the Sun never climbs high: it circles near the horizon, "
                   "so a hill can hide it for days. Azimuth is in the terrain-tile frame (0° = top of the terrain map), not true north.")

# ---------------------------------------------------------------------------------------------- Terrain & ice
with tab_terrain:
    pick_t = st.selectbox("Site", sorted({c["entry"].region for c in combos}), format_func=lambda r: display_name(r, _tile(r), names))
    tile = _tile(pick_t)
    if tile is None:
        st.info("No terrain tile for this site in `data/tiles/`.")
    else:
        cell = next(c["ps"].cells[0] for c in combos if c["entry"].region == pick_t)
        layer = st.radio("Layer", ["hazard", "slope", "height"], horizontal=True)
        st.plotly_chart(fig.tile_map_figure(tile, layer, (int(cell[0]), int(cell[1]))), width="stretch")
        model = tile.extra.get("hazard_model") or tile.extra.get("hazard_source", "unknown")
        st.caption(f"Terrain: **{tile.meta.provenance.banner}** LOLA height, {tile.meters_per_pixel:g} m/pixel, {latlon(tile)}; "
                   f"hazard grid from: {model} (a probability, never a safety proof). Laser coverage "
                   f"{tile.extra.get('laser_coverage', float('nan')):.0%}: the rest of the map is interpolated.")
        st.warning("**Ice and permanently shadowed regions: UNKNOWN.** The ice-evidence layers (KAN-39) and the shadow atlas "
                   "are not loaded yet, so none are drawn. Nothing here says where ice is.", icon="❓")

# ---------------------------------------------------------------------------------------------- About
with tab_about:
    st.markdown("""
**What is exact and what is not**
- Exact physics, no AI: Sun and Earth directions against the terrain horizon, sunlight and Earth-contact hours, countdowns.
- Every number carries a label: *observed*, *modelled*, *generated* or *unknown*. Generated data is always shown as **GENERATED — NOT OBSERVED**.
- This is an educational, low-fidelity tool, not flight software.

**Data credits.** LOLA terrain: NASA PGDA (Barker et al. 2021). Planned for real light data: SPICE/NAIF kernels, checked against JPL Horizons.
Hazard map: our U-Net / slope rule on LOLA. Tools: Streamlit, Plotly. Code written with Claude.
""")
    st.write({c["label"]: {"file": c["entry"].path.name, "provenance": c["ps"].meta.provenance.value, "source": c["ps"].meta.source}
              for c in combos})
