// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Data model: every frame is stored as columns so any panel can draw any time series.
// Source tags used in the panel headers:  feed = straight from the mission data,  derived = computed from the feed,
// simulated = a simple physical model driven by the feed (not measured).
(function () {
'use strict';
const MC = (window.MC = window.MC || {});

MC.PH = ['ORBIT', 'DEORBIT', 'DESCENT', 'LANDED', 'ROVER OPS'];
MC.PH_NAME = ['Orbit', 'Deorbit', 'Descent', 'Landed', 'Rover ops'];
MC.MODES = ['drive', 'hold', 'sleep', 'drill'];
MC.GRAVITY_MOON = 1.62; // [m/s^2] standard lunar surface gravity
MC.LIGHT_TIME_S = 1.28; // [s] mean one-way light time Earth-Moon (384,400 km)
MC.EARTH_MOON_KM = 384400; // [km] mean distance
const FIELDS = ['t', 'ph', 'orbAlt', 'orbSpd', 'lat', 'lon', 'alt', 'vz', 'vh', 'fuel', 'mass', 'thrust', 'eng', 'soc', 'wh', 'solar', 'load', 'speed', 'slope', 'haz', 'ice', 'h', 'lit', 'earth', 'psr', 'sunEl', 'sunAz', 'earthEl', 'dist', 'used', 'x', 'y', 'hd', 'mode', 'drill'];

// Simulated thermal channels: first-order lag towards a steady-state temperature that depends on light, load and speed.
const THERMAL = [
  { k: 'battery', name: 'Battery', tau: 7200, t0: 10, tss: (x) => Math.max(-10, 0.06 * x.amb + 8 + 0.35 * x.load) },
  { k: 'avionics', name: 'Avionics', tau: 3600, t0: 15, tss: (x) => 12 + 0.45 * x.load + 0.04 * x.amb },
  { k: 'panel', name: 'Solar panel', tau: 600, t0: -60, tss: (x) => (x.lit ? x.amb + 90 : x.amb) },
  { k: 'wheels', name: 'Wheel motors', tau: 900, t0: -20, tss: (x) => 0.12 * x.amb + 10 + 3 * x.spd },
  { k: 'drill', name: 'Drill head', tau: 1200, t0: -30, tss: (x) => 0.1 * x.amb + (x.drill ? 60 : 2) },
  { k: 'radiator', name: 'Radiator', tau: 1800, t0: -50, tss: (x) => 0.5 * x.amb + 0.6 * x.load },
];
MC.THERMAL = THERMAL;

MC.reset = function () {
  MC.cols = {}; for (const k of FIELDS) MC.cols[k] = [];
  MC.events = []; MC.evKeys = new Set(); MC.simN = 0; MC.sim = { temp: {} }; for (const c of THERMAL) MC.sim.temp[c.k] = [];
  MC.cur = -1;
};
MC.n = () => MC.cols.t.length;
MC.push = function (f) {
  const c = MC.cols, N = NaN, o = f.orbit, l = f.lander, p = f.pose, mi = MC.MODES.indexOf(f.mode);
  c.t.push(f.t_s); c.ph.push(Math.max(0, MC.PH.indexOf(f.mission_phase || 'ROVER OPS')));
  c.orbAlt.push(o ? o.alt_km : N); c.orbSpd.push(o ? o.speed_m_s : N); c.lat.push(o ? o.lat_deg : N); c.lon.push(o ? o.lon_deg : N);
  c.alt.push(l ? l.alt_m : N); c.vz.push(l ? l.vz_m_s : N); c.vh.push(l ? Math.hypot(l.vx_m_s, l.vy_m_s) : N); c.fuel.push(l ? l.fuel_kg : N); c.mass.push(l ? l.mass_kg : N); c.thrust.push(l ? l.thrust_n : N); c.eng.push(l ? l.engines_ok : N);
  c.soc.push(f.battery_frac ?? N); c.wh.push(f.battery_wh ?? N); c.solar.push(f.solar_w ?? N); c.load.push(f.load_w ?? N); c.speed.push(f.speed_m_s !== undefined ? f.speed_m_s * 100 : N);
  c.slope.push(f.slope_deg ?? N); c.haz.push(f.hazard ?? N); c.ice.push(f.ice_score ?? N); c.h.push(f.height_m ?? N);
  c.lit.push(f.lit === undefined ? N : f.lit ? 1 : 0); c.earth.push(f.earth_visible === undefined ? N : f.earth_visible ? 1 : 0); c.psr.push(f.in_psr === undefined ? N : f.in_psr ? 1 : 0);
  c.sunEl.push(f.sun ? f.sun.elev_deg : N); c.sunAz.push(f.sun ? f.sun.az_deg : N); c.earthEl.push(f.earth_elev_deg ?? N);
  c.dist.push(f.distance_m ?? N); c.used.push(f.energy_used_wh ?? N);
  c.x.push(p ? p.x_m : l ? l.x_m : N); c.y.push(p ? p.y_m : l ? l.y_m : N); c.hd.push(p ? p.heading_deg : N);
  c.mode.push(mi >= 0 ? mi : N); c.drill.push(f.drill_left_s ?? N);
  for (const e of f.events || []) { const key = `${e.t_s}|${e.kind}|${e.msg}`; if (!MC.evKeys.has(key)) { MC.evKeys.add(key); MC.events.push(e); } }
};
MC.simUpdate = function () {
  const c = MC.cols;
  for (let i = MC.simN; i < MC.n(); i++) {
    const dt = i ? Math.max(1, c.t[i] - c.t[i - 1]) : 60, lit = c.lit[i], psr = c.psr[i];
    const x = { amb: psr === 1 ? -170 : lit === 1 ? -35 : Number.isNaN(lit) ? -60 : -150, load: Number.isNaN(c.load[i]) ? 8 : c.load[i], spd: Number.isNaN(c.speed[i]) ? 0 : c.speed[i], lit: lit === 1, drill: c.drill[i] > 0 };
    for (const ch of THERMAL) { const arr = MC.sim.temp[ch.k], prev = i ? arr[i - 1] : ch.t0; arr.push(prev + (ch.tss(x) - prev) * (1 - Math.exp(-dt / ch.tau))); }
  }
  MC.simN = MC.n();
};
// -- helpers -------------------------------------------------------------------------------------------------
MC.at = (k, i = MC.cur) => (i >= 0 && MC.cols[k] ? MC.cols[k][i] : NaN);
MC.fin = (v) => Number.isFinite(v);
MC.has = (k) => MC.cols[k].some(Number.isFinite);
MC.lastFinite = (k, i = MC.cur) => { const a = MC.cols[k]; for (let j = Math.min(i, a.length - 1); j >= 0; j--) if (Number.isFinite(a[j])) return a[j]; return NaN; };
MC.range = (k) => { let a = Infinity, b = -Infinity; for (const v of MC.cols[k]) if (Number.isFinite(v)) { if (v < a) a = v; if (v > b) b = v; } return a <= b ? [a, b] : [NaN, NaN]; };
MC.derive = {
  twr: (i) => { const th = MC.cols.thrust[i], m = MC.cols.mass[i]; return Number.isFinite(th) && m > 0 ? th / (m * MC.GRAVITY_MOON) : NaN; },
  burn: (i) => { const f = MC.cols.fuel, t = MC.cols.t; if (i < 1 || !Number.isFinite(f[i]) || !Number.isFinite(f[i - 1])) return NaN; const dt = t[i] - t[i - 1]; return dt > 0 ? (f[i - 1] - f[i]) / dt : NaN; },
};
MC.series = (fn) => { const out = new Array(MC.n()); for (let i = 0; i < out.length; i++) out[i] = fn(i); return out; };
// Simulated per-wheel values (6 wheels): spread around the wheel-motor temperature and current from speed and slope.
MC.WHEELS = ['Front left', 'Front right', 'Middle left', 'Middle right', 'Rear left', 'Rear right'];
MC.wheel = (w, i = MC.cur) => {
  const T = MC.sim.temp.wheels[i] ?? NaN, spd = MC.at('speed', i) || 0, sl = MC.at('slope', i) || 0, d = MC.lastFinite('dist', i) || 0, off = [1.5, -1.2, 0.6, -0.4, -1.4, 1.1][w];
  return { temp: T + off, amps: 0.15 + 1.2 * spd + 0.04 * sl + 0.03 * off, wear: Math.min(99, d * 0.004 * (1 + 0.08 * off)) };
};
// Simulated link margin (dB) from the Earth elevation; zero when Earth is hidden.
MC.link = (i = MC.cur) => { const e = MC.at('earth', i), el = MC.at('earthEl', i); if (!(e === 1)) return { up: false, margin: 0, kbps: 0 }; const m = Math.max(0, Math.min(14, 2 + 2.2 * Math.abs(el) + 4)); return { up: true, margin: m, kbps: m > 8 ? 256 : m > 4 ? 64 : 16 }; };
// Simulated split of the electrical load by what the rover is doing (fractions add up to 1).
MC.SPLIT = { drive: { Mobility: 0.6, Avionics: 0.2, Heaters: 0.15, Comms: 0.05, Drill: 0 }, hold: { Mobility: 0, Avionics: 0.5, Heaters: 0.35, Comms: 0.15, Drill: 0 }, sleep: { Mobility: 0, Avionics: 0.3, Heaters: 0.65, Comms: 0.05, Drill: 0 }, drill: { Mobility: 0, Avionics: 0.2, Heaters: 0.25, Comms: 0.05, Drill: 0.5 } };
MC.reset();
})();
