// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Adinfinitium Mission Control: 2D viewer. Draws whatever lunar_ops/PROTOCOL.md messages it receives.
// All 3D (vehicle models, descent and surface views) belongs to Basilisk / Vizard, not to this page.
// Palette: midnight black, electric blue, cantaloupe orange. Blue = fine, cantaloupe = needs attention.
'use strict';

const $ = (id) => document.getElementById(id);
const Q = new URLSearchParams(location.search);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const pad = (n, k = 2) => String(Math.floor(n)).padStart(k, '0');
const fmtMET = (t) => { t = Math.max(0, t); return `${Math.floor(t / 86400)} d ${pad(t % 86400 / 3600)}:${pad(t % 3600 / 60)}:${pad(t % 60)}`; };
const fmtHMS = (t) => `${pad(t % 86400 / 3600)}:${pad(t % 3600 / 60)}:${pad(t % 60)}`;
const DEG = Math.PI / 180;
const SPEEDS = [1, 60, 600, 3000, 12000];
const C = { blue: '#2f7dff', blueL: '#8db9ff', blueD: '#14357a', orange: '#ffa566', orangeD: '#5e3a1f', dim: '#8393ad', grid: '#14203a', black: '#02040a' };

const STEPS = [
  { id: 'ORBIT', name: 'Orbit', what: 'Circle the Moon' },
  { id: 'DEORBIT', name: 'Deorbit', what: 'Lower the orbit' },
  { id: 'DESCENT', name: 'Descent', what: 'Land with engines' },
  { id: 'LANDED', name: 'Landed', what: 'Touch the ground' },
  { id: 'ROVER OPS', name: 'Rover work', what: 'Look for ice' },
];
const VIEWS = ['overview', 'map', 'landing', 'rover', 'sun', 'ice', 'ai', 'log', 'real'];
const LAYERS = {
  terrain: ['Ground', 'The ground as the Sun lights it. Dark patches are in shadow.'],
  light: ['Sunlight', 'Orange is where the Sun shines right now. Dark blue is shadow.'],
  shadow: ['Dark craters', 'Blue areas are craters that never see the Sun. This is a computer estimate.'],
  ice: ['Signs of ice', 'Brighter orange means stronger signs of ice. A computer estimate, not proof.'],
  hazard: ['Danger', 'Orange spots are dangerous ground: too steep or too rocky to drive on.'],
};
const KIND_WORD = { decision: 'Decision', event: 'Event', agent: 'AI', sample: 'Sample', abort: 'Stop', dead: 'Problem' };
const CONTROL_WORD = { baseline: 'Backup helper (simple rules)', agent: 'The AI is driving', operator: 'You are driving', autonomy: 'Autopilot' };
const MODE_WORD = { drive: 'Driving', hold: 'Waiting', sleep: 'Sleeping to save power', drill: 'Drilling' };
const PROV_NAMES = { terrain: 'The ground', psr: 'Dark craters', ice_evidence: 'Signs of ice', illumination: 'Sunlight', earth_link: 'Talking to Earth', rover: 'The rover' };

function b64(s) { const bin = atob(s), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a; }
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

const S = {
  mode: 'none', ws: null, W: null, worldMsg: null, last: null, lit: null, view: 'overview',
  layer: 'terrain', speed: 600, playing: true, override: false, keys: {},
  frames: [], idx: -1, T0: 0, T1: 1, simT: 0,
  trail: [], path: null, hist: [], orbitPts: [], orbitAll: [], desc: [], descAll: [],
  phaseNow: 'ORBIT', lander: null, orbit: null, models: [], training: null, logs: [], logDirty: true, dirty: true,
};

// ---------------------------------------------------------------- canvas helpers
function fit(c) {
  const cw = c.clientWidth, ch = c.clientHeight; if (!cw || !ch) return null;
  const dpr = window.devicePixelRatio || 1, w = Math.round(cw * dpr), h = Math.round(ch * dpr);
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  const g = c.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); return { g, w: cw, h: ch };
}
function ramp(stops, v) {
  v = clamp(v, 0, 1) * (stops.length - 1); const i = Math.min(Math.floor(v), stops.length - 2), f = v - i, a = stops[i], b = stops[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}
const ICE_RAMP = [[2, 4, 10], [14, 40, 110], [47, 125, 255], [141, 185, 255], [255, 165, 102]];
function text(g, t, x, y, col = C.dim, align = 'left', size = 13) { g.fillStyle = col; g.font = `${size}px -apple-system, "Segoe UI", Helvetica, Arial, sans-serif`; g.textAlign = align; g.fillText(t, x, y); }
function hgrid(g, w, h, m) { g.strokeStyle = C.grid; g.lineWidth = 1; g.beginPath(); for (let i = 0; i <= 4; i++) { const y = m.t + (h - m.t - m.b) * i / 4; g.moveTo(m.l, y); g.lineTo(w - m.r, y); } g.stroke(); }

// ---------------------------------------------------------------- map
let layerCanvas = null;
function buildLayer() {
  const W = S.W; if (!W) return;
  const { rows, cols } = W;
  if (!layerCanvas) layerCanvas = document.createElement('canvas');
  layerCanvas.width = cols; layerCanvas.height = rows;
  const g = layerCanvas.getContext('2d'), img = g.createImageData(cols, rows), d = img.data, h = W.height, L = S.layer;
  const at = (r, c) => h[clamp(r, 0, rows - 1) * cols + clamp(c, 0, cols - 1)];
  const lx = Math.cos(45 * DEG) * Math.sin(315 * DEG), ly = Math.cos(45 * DEG) * Math.cos(315 * DEG), lz = Math.sin(45 * DEG);
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const i = r * cols + c, o = i * 4;
      const dzdx = (at(r, c + 1) - at(r, c - 1)) / (2 * W.mpp), dzdy = (at(r - 1, c) - at(r + 1, c)) / (2 * W.mpp); // north = up = row-1
      const nl = Math.sqrt(dzdx * dzdx + dzdy * dzdy + 1), shade = clamp((-dzdx * lx - dzdy * ly + lz) / nl, 0, 1);
      let R, G, B;
      if (L === 'terrain') { const lit = S.lit ? S.lit[i] : 1, k = (0.1 + 0.8 * shade) * (lit ? 1 : 0.3); R = 150 * k; G = 168 * k; B = 205 * k + (lit ? 0 : 8); }
      else if (L === 'light') { const lit = S.lit ? S.lit[i] : 1, k = 0.25 + 0.75 * shade; R = lit ? 255 * k : 6; G = lit ? 165 * k : 12; B = lit ? 102 * k : 36; }
      else if (L === 'shadow') { const k = 0.1 + 0.55 * shade; R = 150 * k; G = 168 * k; B = 205 * k; if (W.psr[i]) { R = R * 0.3 + 6; G = G * 0.4 + 30; B = B * 0.5 + 120; } }
      else if (L === 'ice') { [R, G, B] = ramp(ICE_RAMP, W.ice[i] / 255); }
      else { const k = 0.1 + 0.5 * shade, hz = W.hazard[i] / 255; R = 150 * k * (1 - hz) + 255 * hz; G = 168 * k * (1 - hz) + 165 * hz; B = 205 * k * (1 - hz) + 102 * hz; }
      d[o] = R; d[o + 1] = G; d[o + 2] = B; d[o + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0); S.dirty = true;
}
const view = { x0: 0, y0: 0, s: 1 };
function worldToPx(x, y) { return [view.x0 + (x + S.W.half_x) * view.s, view.y0 + (S.W.half_y - y) * view.s]; }
function pxToWorld(px, py) { return [(px - view.x0) / view.s - S.W.half_x, S.W.half_y - (py - view.y0) / view.s]; }

function drawMap(id, big) {
  const c = $(id), fc = fit(c); if (!fc) return; const { g, w, h } = fc; g.fillStyle = C.black; g.fillRect(0, 0, w, h);
  const W = S.W; if (!W || !layerCanvas) return;
  const pad8 = big ? 14 : 4, s = Math.min((w - 2 * pad8) / (2 * W.half_x), (h - 2 * pad8) / (2 * W.half_y)), vx = (w - 2 * W.half_x * s) / 2, vy = (h - 2 * W.half_y * s) / 2;
  if (big) { view.s = s; view.x0 = vx; view.y0 = vy; }
  const P = (x, y) => [vx + (x + W.half_x) * s, vy + (W.half_y - y) * s], f = S.last, r = big ? 7 : 4;
  g.imageSmoothingEnabled = true; g.drawImage(layerCanvas, vx, vy, 2 * W.half_x * s, 2 * W.half_y * s);
  if (S.path && S.path.length > 1) { g.strokeStyle = C.blueL; g.setLineDash([6, 5]); g.lineWidth = big ? 2 : 1.5; g.beginPath(); S.path.forEach((p, i) => { const [x, y] = P(p[0], p[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); g.setLineDash([]); }
  if (S.trail.length > 1) { g.strokeStyle = C.blue; g.lineWidth = big ? 3 : 2.5; g.beginPath(); S.trail.forEach((p, i) => { const [x, y] = P(p[0], p[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); }
  for (const t of W.targets || []) {
    const [x, y] = P(t.x_m, t.y_m), st = f?.targets?.find((q) => q.id === t.id), done = st?.sampled, act = f?.drill_target === t.id, col = done ? C.blue : act ? C.blueL : C.orange;
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 2; g.beginPath(); g.arc(x, y, r, 0, 7); done || act ? g.fill() : g.stroke(); if (big) text(g, t.id, x + 11, y - 9, col, 'left', 14);
  }
  if (W.start) { const [x, y] = P(W.start.x_m, W.start.y_m); g.strokeStyle = C.blueL; g.lineWidth = 2; g.strokeRect(x - r + 1, y - r + 1, 2 * r - 2, 2 * r - 2); }
  if (S.phaseNow === 'DESCENT' && f?.lander) { const [x, y] = P(f.lander.x_m, f.lander.y_m); g.fillStyle = C.orange; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill(); if (big) text(g, `${f.lander.alt_m.toFixed(0)} m up`, x + 12, y + 5, C.orange, 'left', 14); }
  if (f?.pose) { const [x, y] = P(f.pose.x_m, f.pose.y_m), hd = f.pose.heading_deg * DEG, k = big ? 1 : 0.7; g.save(); g.translate(x, y); g.rotate(hd); g.fillStyle = f.aborted ? C.orange : '#fff'; g.beginPath(); g.moveTo(0, -11 * k); g.lineTo(8 * k, 9 * k); g.lineTo(-8 * k, 9 * k); g.closePath(); g.fill(); g.restore(); }
  if (big) { const m100 = 100 * s; g.strokeStyle = '#fff'; g.lineWidth = 3; g.beginPath(); g.moveTo(vx + 14, h - 16); g.lineTo(vx + 14 + m100, h - 16); g.stroke(); }
}
function mapHover(e) {
  if (!S.W) return; const r = $('map').getBoundingClientRect(), [x, y] = pxToWorld(e.clientX - r.left, e.clientY - r.top);
  const col = Math.floor((x + S.W.half_x) / S.W.mpp), row = Math.floor((S.W.half_y - y) / S.W.mpp), tip = $('maptip');
  if (col < 0 || row < 0 || col >= S.W.cols || row >= S.W.rows) { tip.textContent = 'Point at the map to read the ground there.'; return; }
  const i = row * S.W.cols + col;
  tip.textContent = `East ${x.toFixed(0)} m · North ${y.toFixed(0)} m · tilt ${S.W.slope[i]}° · signs of ice ${(S.W.ice[i] / 255).toFixed(2)} · dark crater: ${S.W.psr[i] ? 'yes' : 'no'} · danger ${(S.W.hazard[i] / 255).toFixed(2)}`;
}

// ---------------------------------------------------------------- plots
function drawOrbit() {
  const c = $('orbit'), fc = fit(c); if (!fc) return; const { g, w, h } = fc, m = { l: 12, r: 12, t: 12, b: 28 }; g.fillStyle = C.black; g.fillRect(0, 0, w, h); hgrid(g, w, h, m);
  const X = (lon) => m.l + (((lon + 180) % 360 + 360) % 360) / 360 * (w - m.l - m.r), Y = (lat) => m.t + (90 - lat) / 180 * (h - m.t - m.b);
  const seg = (pts, col, wd) => { g.strokeStyle = col; g.lineWidth = wd; g.beginPath(); let prev = null; for (const p of pts) { const x = X(p.lon), y = Y(p.lat); if (prev === null || Math.abs(x - prev) > 0.25 * (w - m.l - m.r)) g.moveTo(x, y); else g.lineTo(x, y); prev = x; } g.stroke(); };
  seg(S.orbitAll, C.blueD, 1.5); seg(S.orbitPts, C.blue, 3);
  if (S.W?.site) { const x = X(S.W.site.lon_deg), y = Y(S.W.site.lat_deg); g.strokeStyle = C.orange; g.lineWidth = 2; g.beginPath(); g.arc(x, y, 7, 0, 7); g.stroke(); text(g, 'landing spot', x + 12, y - 6, C.orange); }
  const p = S.orbitPts[S.orbitPts.length - 1]; if (p) { g.fillStyle = '#fff'; g.beginPath(); g.arc(X(p.lon), Y(p.lat), 5, 0, 7); g.fill(); }
  text(g, 'top = North Pole · bottom = South Pole · left to right = around the Moon', m.l, h - 8);
  if (!S.orbitAll.length) text(g, 'No orbit information has arrived yet.', w / 2, h / 2, C.dim, 'center', 15);
}
function drawDescent() {
  const c = $('descent'), fc = fit(c); if (!fc) return; const { g, w, h } = fc, m = { l: 12, r: 12, t: 24, b: 28 }; g.fillStyle = C.black; g.fillRect(0, 0, w, h); hgrid(g, w, h, m);
  const A = S.descAll; if (A.length < 2) { text(g, 'No landing information has arrived yet.', w / 2, h / 2, C.dim, 'center', 15); return; }
  const t0 = A[0].t, t1 = A[A.length - 1].t, aMax = Math.max(...A.map((p) => p.alt)), vMin = Math.min(...A.map((p) => p.vz)), vMax = Math.max(...A.map((p) => p.vz), 0.5);
  const X = (t) => m.l + (t - t0) / Math.max(t1 - t0, 1) * (w - m.l - m.r), YA = (a) => h - m.b - a / aMax * (h - m.t - m.b), YV = (v) => h - m.b - (v - vMin) / (vMax - vMin) * (h - m.t - m.b);
  const line = (pts, fy, col, wd) => { g.strokeStyle = col; g.lineWidth = wd; g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.t), fy(p)) : g.moveTo(X(p.t), fy(p)))); g.stroke(); };
  line(A, (p) => YA(p.alt), C.blueD, 1.5); line(A, (p) => YV(p.vz), C.orangeD, 1.5);
  if (S.desc.length > 1) { line(S.desc, (p) => YA(p.alt), C.blue, 3); line(S.desc, (p) => YV(p.vz), C.orange, 2.5); }
  text(g, `Blue: height (starts at ${aMax.toFixed(0)} m)`, m.l, 16, C.blue); text(g, 'Orange: speed', w - m.r, 16, C.orange, 'right'); text(g, 'time goes left to right', m.l, h - 8);
}
function drawBattery() {
  const c = $('battery'), fc = fit(c); if (!fc) return; const { g, w, h } = fc, m = { l: 12, r: 12, t: 14, b: 30 }; g.fillStyle = C.black; g.fillRect(0, 0, w, h); hgrid(g, w, h, m);
  const H = S.hist; if (H.length < 2 || S.last?.battery_frac === undefined) { text(g, 'The rover has not started yet.', w / 2, h / 2, C.dim, 'center', 15); return; }
  const t0 = H[0][0], t1 = H[H.length - 1][0], X = (t) => m.l + (t - t0) / Math.max(t1 - t0, 1) * (w - m.l - m.r), Y = (v) => h - m.b - v * (h - m.t - m.b);
  g.strokeStyle = C.orange; g.setLineDash([6, 5]); g.lineWidth = 1.5; g.beginPath(); g.moveTo(m.l, Y(0.2)); g.lineTo(w - m.r, Y(0.2)); g.stroke(); g.setLineDash([]); text(g, 'save-power level (20 %)', w - m.r, Y(0.2) - 6, C.orange, 'right');
  g.fillStyle = 'rgba(47,125,255,.16)'; g.strokeStyle = C.blue; g.lineWidth = 3; g.beginPath(); H.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1])))); g.stroke(); g.lineTo(X(t1), h - m.b); g.lineTo(X(t0), h - m.b); g.fill();
  g.fillStyle = C.orange; for (const p of H) if (p[2]) g.fillRect(X(p[0]), h - m.b + 6, 2, 6); text(g, 'orange ticks = the rover was in sunlight', m.l, h - 6);
}
function drawSky() {
  const c = $('sky'), fc = fit(c); if (!fc) return; const { g, w, h } = fc, m = { l: 16, r: 16, t: 14, b: 32 }; g.fillStyle = C.black; g.fillRect(0, 0, w, h); const f = S.last;
  if (!f?.sun) { text(g, 'Waiting for the Sun and Earth positions…', w / 2, h / 2, C.dim, 'center', 15); return; }
  const X = (az) => m.l + ((az % 360 + 360) % 360) / 360 * (w - m.l - m.r), Y = (el) => m.t + (30 - clamp(el, -10, 30)) / 40 * (h - m.t - m.b);
  g.fillStyle = '#0b1424'; g.fillRect(m.l, Y(0), w - m.l - m.r, h - m.b - Y(0)); g.strokeStyle = C.blueD; g.lineWidth = 2; g.beginPath(); g.moveTo(m.l, Y(0)); g.lineTo(w - m.r, Y(0)); g.stroke();
  text(g, 'ground (flat horizon assumed)', m.l + 8, Y(0) + 20);
  const sx = X(f.sun.az_deg), sy = Y(f.sun.elev_deg); g.fillStyle = C.orange; g.beginPath(); g.arc(sx, sy, 10, 0, 7); g.fill(); text(g, 'Sun', sx + 16, sy + 5, C.orange, 'left', 15);
  const eaz = S.W?.sky?.earth_azimuth_deg ?? 180, ex = X(eaz), ey = Y(f.earth_elev_deg ?? 0); g.fillStyle = C.blue; g.beginPath(); g.arc(ex, ey, 8, 0, 7); g.fill(); text(g, 'Earth', ex + 14, ey + 5, C.blue, 'left', 15);
  text(g, 'compass direction 0° to 360° →', m.l, h - 9);
}
function drawTrain() {
  const T = S.training, card = $('traincard'); card.hidden = !(T && T.rows?.length); if (card.hidden) return;
  const c = $('train'), fc = fit(c); if (!fc) return; const { g, w, h } = fc; g.fillStyle = C.black; g.fillRect(0, 0, w, h);
  const rows = T.rows, pick = (keys) => keys.find((k) => typeof rows[rows.length - 1][k] === 'number'), kr = pick(['reward', 'mean_reward', 'return', 'ep_return', 'mean_return']), kl = pick(['loss', 'policy_loss', 'value_loss']);
  const plot = (key, col) => { if (!key) return; const v = rows.map((r) => r[key]).filter((x) => typeof x === 'number'), lo = Math.min(...v), hi = Math.max(...v);
    g.strokeStyle = col; g.lineWidth = 2.5; g.beginPath(); v.forEach((y, i) => { const px = 12 + i / Math.max(v.length - 1, 1) * (w - 24), py = h - 14 - (y - lo) / Math.max(hi - lo, 1e-9) * (h - 28); i ? g.lineTo(px, py) : g.moveTo(px, py); }); g.stroke(); };
  plot(kr, C.blue); plot(kl, C.orange);
}

// ---------------------------------------------------------------- plain-language text
function nowSentence(f) {
  if (!f) return ['—', 'Waiting for the mission to start…', false];
  const i = Math.max(0, STEPS.findIndex((s) => s.id === S.phaseNow)), step = `Step ${i + 1} of ${STEPS.length} · ${STEPS[i].name}`;
  if (f.aborted) return [step, 'Safe mode: the rover has stopped and is keeping itself safe.', true];
  if (f.alive === false) return [step, 'The rover has run out of power and cannot move any more.', true];
  let s;
  if (f.orbit) s = S.phaseNow === 'ORBIT' ? `The lander is circling the Moon, ${f.orbit.alt_km.toFixed(0)} km up, getting ready to come down.` : `The lander is lowering its orbit to get close to the ground. It is now ${f.orbit.alt_km.toFixed(0)} km up.`;
  else if (f.lander) { const l = f.lander; s = `The lander is landing. It is ${l.alt_m.toFixed(0)} metres above the ground and slowing down.` + (l.engines_ok < 5 ? ` Only ${l.engines_ok} of 5 engines are working, and it is staying balanced.` : ''); }
  else if (S.phaseNow === 'LANDED') s = 'The lander has touched down. The rover is getting ready to roll out.';
  else if (f.pose) { const mode = f.mode || 'hold', pct = Math.round((f.battery_frac ?? 0) * 100);
    s = { drive: 'The rover is driving across the ground.', hold: 'The rover is waiting and thinking.', sleep: 'The rover is sleeping to save power.', drill: `The rover is drilling${f.drill_target ? ' at ' + f.drill_target : ''}.` }[mode] || 'The rover is working.';
    s += ` Its battery is ${pct} % full.` + (pct < 25 ? ' That is low.' : ''); return [step, s, pct < 25]; }
  else s = 'The mission is running.';
  return [step, s, false];
}
function tile(label, value, note = '', cls = '') { return `<div class="tile"><small>${label}</small><b class="${cls}">${value}</b><i>${note || '&nbsp;'}</i></div>`; }
function compass(az) { return ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'][Math.round(((az % 360) + 360) % 360 / 45) % 8]; }
function check(label, value, cls) { return `<li><span>${label}</span><span class="v ${cls}">${value}</span></li>`; }

function renderNow() {
  const [step, sent, alert] = nowSentence(S.last); $('nowstep').textContent = step; $('nowtext').textContent = sent; $('nowtext').className = alert ? 'alert' : '';
  const f = S.last; if (!f) return;
  const c = $('control'); c.textContent = f.aborted ? 'Safe mode: stopped' : CONTROL_WORD[f.control] || '—'; c.className = f.aborted ? 'safe' : 'dim';
}
function renderOverview() {
  const f = S.last, W = S.W; if (!f || !W) return; const cur = STEPS.findIndex((s) => s.id === S.phaseNow);
  $('steps').innerHTML = STEPS.map((s, i) => `<li class="${i === cur ? 'on' : i < cur ? 'done' : ''}"><b>${i + 1}. ${s.name}</b><span>${s.what}</span></li>`).join('');
  const rows = [], rover = f.battery_frac !== undefined;
  rows.push(rover ? check('Battery', `${Math.round(f.battery_frac * 100)} % · ${f.battery_frac < 0.25 ? 'low' : 'good'}`, f.battery_frac < 0.25 ? 'warn' : 'ok') : check('Battery', 'not on the Moon yet', 'na'));
  rows.push(rover ? check('Sunlight on the rover', f.lit ? 'yes' : 'no, in shadow', f.lit ? 'ok' : 'warn') : check('Sunlight on the rover', 'not on the Moon yet', 'na'));
  rows.push(rover ? check('Can talk to Earth', f.earth_visible ? 'yes' : 'no', f.earth_visible ? 'ok' : 'warn') : check('Can talk to Earth', '—', 'na'));
  rows.push(rover ? check('Ground is safe here', f.slope_deg <= W.limits.slope_limit_deg && f.hazard < 0.5 ? 'yes' : 'careful', f.slope_deg <= W.limits.slope_limit_deg && f.hazard < 0.5 ? 'ok' : 'warn') : check('Ground is safe here', '—', 'na'));
  rows.push(f.lander ? check('Engines working', `${f.lander.engines_ok} of 5`, f.lander.engines_ok < 5 ? 'warn' : 'ok') : check('Engines working', S.lander ? `${S.lander.engines_ok} of 5 at landing` : 'not landing yet', 'na'));
  rows.push(check('Who is in control', CONTROL_WORD[f.control] || '—', 'ok'));
  $('checks').innerHTML = rows.join('');
  const n = (f.targets || []).filter((t) => t.sampled).length;
  $('overtiles').innerHTML = tile('Time since start', fmtMET(f.t_s), 'how long the mission has run') + tile('Ice places checked', `${n} of ${(W.targets || []).length}`, 'places where the rover took a sample', n ? 'ok' : '')
    + (f.pose ? tile('Distance driven', `${f.distance_m.toFixed(0)} m`, 'since the rover rolled out') + tile('Energy used', `${f.energy_used_wh.toFixed(0)} Wh`, 'from the battery so far') : '');
  $('news').innerHTML = S.logs.slice(0, 4).map((e) => `<li><time>${fmtHMS(e.t_s)}</time>${esc(e.msg)}</li>`).join('') || '<li class="dim">Nothing yet.</li>';
}
function renderLanding() {
  const o = S.orbit, l = S.lander, groups = [];
  if (o) groups.push(['Orbit', [tile('Height above the Moon', `${o.alt_km.toFixed(1)} km`, 'how far up the lander is'), tile('Speed', `${o.speed_m_s.toFixed(0)} m/s`, 'how fast it moves around the Moon'), tile('Lap number', `${o.orbit_no ?? '—'}`, 'times it has gone around'), tile('Latitude', `${o.lat_deg.toFixed(1)}°`, 'north or south on the Moon'), tile('Longitude', `${o.lon_deg.toFixed(1)}°`, 'east or west around the Moon')]]);
  if (l) groups.push(['Landing', [tile('Height above the ground', `${l.alt_m.toFixed(0)} m`, 'how far from the surface'), tile('Falling speed', `${Math.abs(l.vz_m_s).toFixed(1)} m/s`, 'it must be gentle at the end'), tile('Sideways speed', `${Math.hypot(l.vx_m_s, l.vy_m_s).toFixed(1)} m/s`, 'drifting across the ground'),
    tile('Fuel left', `${l.fuel_kg.toFixed(0)} kg`, 'what the engines can still burn'), tile('Weight', `${l.mass_kg.toFixed(0)} kg`, 'lander plus fuel'), tile('Engine push', `${l.thrust_n.toFixed(0)} N`, 'force slowing the lander'), tile('Engines working', `${l.engines_ok} of 5`, l.engines_ok < 5 ? 'some are switched off' : 'all on', l.engines_ok < 5 ? 'warn' : 'ok')]]);
  if (S.phaseNow !== 'ORBIT' && S.phaseNow !== 'DEORBIT') groups.reverse();
  $('landtiles').innerHTML = groups.map(([t, ts]) => `<div class="group"><h3>${t}</h3><div class="tiles">${ts.join('')}</div></div>`).join('') || '<div class="card"><p class="hint">No landing information has arrived yet.</p></div>';
  const ex = $('engines'); if (l) { ex.innerHTML = ''; for (let i = 0; i < 5; i++) { const off = l.engines_ok < 5 && [1, 3].includes(i), hh = off ? 4 : clamp(l.thrust_n / (800 * Math.max(l.engines_ok, 1)) * 100, 3, 100); ex.insertAdjacentHTML('beforeend', `<div class="eng ${off ? 'off' : ''}"><i style="height:${hh}%"></i><span>Engine ${i + 1}${off ? ' · off' : ''}</span></div>`); } } else ex.innerHTML = '<span class="dim">No engine information yet.</span>';
}
function renderRover() {
  const f = S.last, W = S.W; if (!f || !W) return;
  if (!f.pose) { $('rovertiles').innerHTML = '<div class="card"><p class="hint">The rover has not rolled out yet. Its numbers appear after landing.</p></div>'; return; }
  const p = f.pose, net = f.solar_w - f.load_w, bad = f.slope_deg > W.limits.slope_limit_deg;
  const G = [
    ['What it is doing', [tile('Activity', MODE_WORD[f.mode] || f.mode, esc(f.reason || f.phase || '')), tile('Speed', `${(f.speed_m_s * 100).toFixed(1)} cm/s`, 'how fast it rolls'), tile('Facing', `${p.heading_deg.toFixed(0)}°`, `${compass(p.heading_deg)} (0° is north)`)]],
    ['Where it is', [tile('Position', `${p.x_m.toFixed(0)}, ${p.y_m.toFixed(0)} m`, 'east, north of the map centre'), tile('Distance driven', `${f.distance_m.toFixed(0)} m`, 'in total'), tile('Ground height', `${f.height_m.toFixed(0)} m`, 'above the Moon’s reference level')]],
    ['The ground under it', [tile('Tilt', `${f.slope_deg.toFixed(1)}°`, `the rover can handle up to ${W.limits.slope_limit_deg}°`, bad ? 'warn' : 'ok'), tile('Danger', f.hazard.toFixed(2), '0 is safe, 1 is dangerous', f.hazard >= 0.5 ? 'warn' : ''), tile('In a dark crater', f.in_psr ? 'Yes' : 'No', 'a crater the Sun never reaches'), tile('Signs of ice here', f.ice_score.toFixed(2), 'from 0 to 1, a computer estimate')]],
    ['Power', [tile('Battery', `${Math.round(f.battery_frac * 100)} %`, `${f.battery_wh.toFixed(0)} of ${W.limits.battery_capacity_wh} Wh (assumed size)`, f.battery_frac < 0.25 ? 'warn' : 'ok'), tile('Sun power in', `${f.solar_w.toFixed(0)} W`, 'what the solar panels make'), tile('Power out', `${f.load_w.toFixed(0)} W`, 'what the rover uses'), tile('Net', `${net >= 0 ? '+' : '−'}${Math.abs(net).toFixed(0)} W`, net >= 0 ? 'charging' : 'draining', net >= 0 ? 'ok' : 'warn'), tile('Energy used', `${f.energy_used_wh.toFixed(0)} Wh`, 'since the start')]],
    ['Ice work', [tile('Drilling', f.drill_target || 'Nothing', f.drill_target ? `${f.drill_left_s.toFixed(0)} s left` : 'not drilling right now'), tile('Samples taken', `${(f.targets || []).filter((t) => t.sampled).length} of ${(W.targets || []).length}`, 'ice places finished')]],
  ];
  $('rovertiles').innerHTML = G.map(([t, ts]) => `<div class="group"><h3>${t}</h3><div class="tiles">${ts.join('')}</div></div>`).join('');
}
function renderSun() {
  const f = S.last; if (!f?.sun) { $('suntiles').innerHTML = ''; return; }
  const eaz = S.W?.sky?.earth_azimuth_deg ?? 180, eel = f.earth_elev_deg ?? 0;
  $('suntiles').innerHTML = tile('Sun height', `${f.sun.elev_deg.toFixed(1)}°`, f.sun.elev_deg > 0 ? 'above the horizon' : 'below the horizon') + tile('Sun direction', `${f.sun.az_deg.toFixed(0)}°`, compass(f.sun.az_deg))
    + tile('Earth height', `${eel.toFixed(1)}°`, eel > 0 ? 'above the horizon' : 'below the horizon') + tile('Earth direction', `${eaz.toFixed(0)}°`, compass(eaz))
    + (f.lit !== undefined ? tile('Rover in sunlight', f.lit ? 'Yes' : 'No', 'it only charges in sunlight', f.lit ? 'ok' : 'warn') + tile('Can talk to Earth', f.earth_visible ? 'Yes' : 'No', 'it needs to see Earth', f.earth_visible ? 'ok' : 'warn') : '');
}
function renderIce() {
  const f = S.last, W = S.W; if (!f || !W) return; const n = (f.targets || []).filter((t) => t.sampled).length;
  $('icetitle').innerHTML = `Places to look for ice <span>${n} of ${(W.targets || []).length} done</span>`;
  $('icelist').innerHTML = (W.targets || []).map((t) => { const st = f.targets?.find((q) => q.id === t.id), act = f.drill_target === t.id, cls = st?.sampled ? 'done' : act ? 'active' : 'open', word = st?.sampled ? 'Sampled' : act ? 'Drilling now' : 'Not visited';
    return `<li><b>${esc(t.id)}</b><div class="bar"><i style="width:${Math.round(t.ice_score * 100)}%"></i></div><span class="dim">score ${t.ice_score.toFixed(2)} · depth ${(t.depth_m ?? 0).toFixed(0)} m</span><span class="st ${cls}">${word}</span></li>`; }).join('');
  $('icetiles').innerHTML = (f.pose ? tile('Signs of ice where the rover is', f.ice_score.toFixed(2), 'from 0 to 1') + tile('Drilling', f.drill_target || 'Nothing', f.drill_target ? `${f.drill_left_s.toFixed(0)} s left` : 'not drilling right now') : '')
    + tile('Places done', `${n} of ${(W.targets || []).length}`, 'ice places sampled', n ? 'ok' : '');
}
function renderAI() {
  $('ailist').innerHTML = S.models.map((m) => { const word = m.status === 'attached' ? 'Connected' : m.status === 'fallback' ? `Using a backup${m.fallback ? ': ' + esc(m.fallback) : ''}` : 'Not connected', cls = m.status === 'attached' ? 'attached' : m.status === 'fallback' ? 'fallback' : 'none';
    const params = m.params ? ` · ${m.params >= 1e6 ? (m.params / 1e6).toFixed(1) + ' million' : Math.round(m.params / 1e3) + ' thousand'} numbers` : '';
    return `<li><div><b>${esc(m.name)}</b><small>${esc(m.kind)}${params}</small></div><div>${esc(m.role)}<small>made by ${esc(m.owner || 'the team')} · used in ${esc(m.phase || '—')}</small></div><span class="st ${cls}">${word}</span></li>`; }).join('');
}
function renderLogView() {
  $('logcount').textContent = `${S.logs.length} entries`;
  $('log').innerHTML = S.logs.map((e) => { const k = KIND_WORD[e.kind] || String(e.kind).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()), cls = ['abort', 'dead'].includes(e.kind) ? 'alert' : e.kind === 'agent' ? 'agent' : '';
    return `<li class="${cls}"><span><time>${fmtHMS(e.t_s)}</time>${esc(k)}</span><span class="m">${esc(e.msg)}</span></li>`; }).join('') || '<li class="dim">Nothing yet.</li>';
}
function renderReal() {
  const pv = S.W?.provenance || {};
  $('reallist').innerHTML = Object.keys(PROV_NAMES).filter((k) => pv[k]).map((k) => { const t = String(pv[k]), real = /observed/i.test(t), word = /generated/i.test(t) ? 'Made up by a computer' : real ? 'Real NASA data' : /modell?ed/i.test(t) ? 'Computer model' : 'Unknown', cls = real ? 'real' : 'model', assumed = /assumed/i.test(t);
    return `<li><b>${PROV_NAMES[k]}</b><span class="tag ${cls}">${word}${assumed ? ' · with assumed numbers' : ''}</span><small>${esc(t)}</small></li>`; }).join('') || '<li class="dim">The data source has not said where its numbers come from.</li>';
}
function renderView() {
  switch (S.view) {
    case 'overview': renderOverview(); break; case 'landing': renderLanding(); break; case 'rover': renderRover(); break; case 'sun': renderSun(); break;
    case 'ice': renderIce(); break; case 'ai': renderAI(); break; case 'real': renderReal(); break;
    case 'log': if (S.logDirty) { renderLogView(); S.logDirty = false; } break; default: break;
  }
}
function showView(v) {
  S.view = VIEWS.includes(v) ? v : 'overview'; for (const s of document.querySelectorAll('.view')) s.classList.toggle('on', s.id === `v-${S.view}`);
  for (const b of $('nav').children) b.classList.toggle('on', b.dataset.v === S.view); if (location.hash !== `#${S.view}`) history.replaceState(null, '', `#${S.view}`);
  S.logDirty = true; S.dirty = true; renderView(); $('views').scrollTop = 0;
}

// ---------------------------------------------------------------- frames
function applyFrame(f, light = false) {
  S.last = f; S.phaseNow = f.mission_phase || 'ROVER OPS'; S.dirty = true;
  for (const e of f.events || []) { S.logs.unshift(e); S.logDirty = true; } if (S.logs.length > 250) S.logs.length = 250;
  if (f.pose) { const p = f.pose, tr = S.trail; if (!tr.length || Math.hypot(tr[tr.length - 1][0] - p.x_m, tr[tr.length - 1][1] - p.y_m) > 0.5) tr.push([p.x_m, p.y_m]); if (f.path) S.path = f.path; }
  if (f.orbit) { S.orbit = f.orbit; S.orbitPts.push({ lat: f.orbit.lat_deg, lon: f.orbit.lon_deg }); }
  if (f.lander) { S.lander = f.lander; S.desc.push({ t: f.t_s, alt: f.lander.alt_m, vz: f.lander.vz_m_s }); }
  S.hist.push([f.t_s, f.battery_frac ?? 0, f.lit ? 1 : 0]); if (S.hist.length > 600) S.hist.shift();
  if (light) return;
  if (f.lit_bits_b64 && S.W) { const bits = b64(f.lit_bits_b64), n = S.W.rows * S.W.cols, m = new Uint8Array(n); for (let i = 0; i < n; i++) m[i] = (bits[i >> 3] >> (7 - (i & 7))) & 1; S.lit = m; if (S.layer === 'terrain' || S.layer === 'light') buildLayer(); }
  $('simclock').textContent = fmtMET(f.t_s); renderNow(); renderView();
}

// ---------------------------------------------------------------- data sources
function resetDerived() { S.trail = []; S.hist = []; S.orbitPts = []; S.desc = []; S.lander = null; S.orbit = null; S.lit = null; S.path = null; S.logs = []; S.logDirty = true; }
function loadWorld(m) {
  S.worldMsg = m; const h = new Float32Array(b64(m.height_f32).buffer);
  S.W = { ...m, height: h, slope: b64(m.slope_u8), psr: b64(m.psr_u8), ice: b64(m.ice_u8), hazard: b64(m.hazard_u8), site: m.site || { lat_deg: -89.7, lon_deg: 0 } };
  resetDerived(); S.last = null; S.models = m.models || []; buildLayer(); renderView();
}
function notice(html) { const n = $('notice'); n.hidden = !html; n.innerHTML = html || ''; }
function setConn(kind, t) { const c = $('conn'); c.className = kind; c.textContent = t; }
function startReplay(world, frames) {
  S.mode = 'replay'; loadWorld(world); S.frames = frames; S.idx = -1; S.T0 = frames[0]?.t_s ?? 0; S.T1 = frames[frames.length - 1]?.t_s ?? 1; S.simT = S.T0; S.playing = true;
  S.orbitAll = frames.filter((f) => f.orbit).map((f) => ({ lat: f.orbit.lat_deg, lon: f.orbit.lon_deg }));
  S.descAll = frames.filter((f) => f.lander).map((f) => ({ t: f.t_s, alt: f.lander.alt_m, vz: f.lander.vz_m_s }));
  setConn('replay', 'Replaying a recording'); $('abort').disabled = true; $('override').disabled = true; $('play').textContent = 'Pause'; $('seek').disabled = false;
}
function advanceTo(t) { while (S.idx + 1 < S.frames.length && S.frames[S.idx + 1].t_s <= t) { S.idx++; applyFrame(S.frames[S.idx], S.idx + 1 < S.frames.length && S.frames[S.idx + 1].t_s <= t); } }
function seekTo(t) { S.idx = -1; resetDerived(); S.simT = t; advanceTo(t); $('seek').value = String(((t - S.T0) / Math.max(S.T1 - S.T0, 1)) * 1000); if (S.layer === 'terrain') buildLayer(); }
async function tryReplay() {
  try {
    const [w, r] = await Promise.all([fetch('sample/world.json'), fetch('sample/run.jsonl')]); if (!w.ok || !r.ok) throw new Error('no sample');
    const world = await w.json(), frames = (await r.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l)); notice(''); startReplay(world, frames);
    const seek = Q.get('seek'); if (seek !== null) { S.playing = false; $('play').textContent = 'Play'; seekTo(S.T0 + (S.T1 - S.T0) * Number(seek)); }
  } catch (e) { setConn('off', 'Not connected'); notice('<b>No mission is connected.</b><br><br>Start one with<br><code>python -m lunar_ops.server</code><br>then reload this page. It connects by itself.'); }
}
function connectLive(url) {
  return new Promise((resolve) => {
    let opened = false; const ws = new WebSocket(url), to = setTimeout(() => { if (!opened) { ws.close(); resolve(false); } }, 1500);
    ws.onopen = () => { opened = true; clearTimeout(to); S.ws = ws; S.mode = 'live'; setConn('live', 'Live from the mission'); notice(''); $('abort').disabled = false; $('override').disabled = false; $('seek').disabled = true; resolve(true); };
    ws.onmessage = (ev) => { const m = JSON.parse(ev.data);
      if (m.type === 'world') loadWorld(m); else if (m.type === 'frame' && S.W) applyFrame(m); else if (m.type === 'models') { S.models = m.models; S.dirty = true; renderView(); }
      else if (m.type === 'state') { S.playing = m.playing; $('play').textContent = m.playing ? 'Pause' : 'Play'; } };
    ws.onerror = () => { if (!opened) resolve(false); };
    ws.onclose = () => { if (opened) { setConn('off', 'Connection lost'); S.mode = 'none'; notice('<b>The connection was lost.</b><br>Reload the page to connect again.'); } };
  });
}
function send(o) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(o)); }
async function loadTraining() { try { const r = await fetch('/api/training'); if (r.ok) { S.training = await r.json(); S.dirty = true; } } catch (e) { /* static hosting: no endpoint */ } }

// ---------------------------------------------------------------- controls
function setSpeed(v) { S.speed = v; send({ type: 'cmd', cmd: 'speed', value: v }); }
$('slower').onclick = () => setSpeed(SPEEDS[Math.max(0, SPEEDS.indexOf(S.speed) - 1)] ?? 600);
$('faster').onclick = () => setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(S.speed) + 1)] ?? 3000);
$('play').onclick = () => { S.playing = !S.playing; $('play').textContent = S.playing ? 'Pause' : 'Play'; send({ type: 'cmd', cmd: S.playing ? 'play' : 'pause' }); };
$('seek').oninput = (e) => { if (S.mode === 'replay') seekTo(S.T0 + (S.T1 - S.T0) * Number(e.target.value) / 1000); };
$('abort').onclick = () => { if (confirm('Stop the rover and keep it safe? It will abandon any drilling.')) send({ type: 'cmd', cmd: 'abort' }); };
$('override').onchange = (e) => { S.override = e.target.checked; send({ type: 'cmd', cmd: 'override', on: S.override }); };
$('openfile').onclick = () => $('filepick').click();
$('filepick').onchange = async (e) => { const f = e.target.files[0]; if (!f || !S.W) return; const frames = (await f.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((m) => m.type === 'frame'); if (frames.length) startReplay(S.worldMsg, frames); };
addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target === document.body) { e.preventDefault(); $('play').click(); } S.keys[e.code] = true; });
addEventListener('keyup', (e) => { S.keys[e.code] = false; });
setInterval(() => { if (!S.override || S.mode !== 'live') return; const k = S.keys; send({ type: 'cmd', cmd: 'drive', v: k.KeyW ? 1 : 0, omega: (k.KeyD ? 1 : 0) - (k.KeyA ? 1 : 0) }); }, 200);
$('map').addEventListener('pointermove', mapHover);
for (const b of $('nav').children) b.onclick = () => showView(b.dataset.v);
addEventListener('hashchange', () => showView(location.hash.slice(1)));
{ const host = $('maplayers'); for (const [id, [name]] of Object.entries(LAYERS)) { const b = document.createElement('button'); b.textContent = name; b.dataset.l = id; b.onclick = () => { S.layer = id; for (const x of host.children) x.className = x.dataset.l === id ? 'on' : ''; $('layerhelp').textContent = LAYERS[id][1]; buildLayer(); }; host.appendChild(b); }
  host.children[0].className = 'on'; $('layerhelp').textContent = LAYERS.terrain[1]; }

// ---------------------------------------------------------------- main loop
let tPrev = performance.now(), lastDraw = 0;
function frameLoop(now) {
  const dt = Math.min((now - tPrev) / 1000, 0.1); tPrev = now;
  if (S.mode === 'replay' && S.playing && S.frames.length) { S.simT += dt * S.speed; advanceTo(S.simT); if (S.idx >= S.frames.length - 1) { S.playing = false; $('play').textContent = 'Play'; } $('seek').value = String(((S.simT - S.T0) / Math.max(S.T1 - S.T0, 1)) * 1000); S.dirty = true; }
  $('speedlab').textContent = `${S.speed >= 1000 ? S.speed / 1000 + 'k' : S.speed}×`;
  if ((S.dirty && now - lastDraw > 66) || now - lastDraw > 500) {
    lastDraw = now; S.dirty = false;
    ({ overview: () => drawMap('minimap', false), map: () => drawMap('map', true), landing: () => { drawOrbit(); drawDescent(); }, rover: drawBattery, sun: drawSky, ai: drawTrain }[S.view] || (() => {}))();
  }
  requestAnimationFrame(frameLoop);
}
addEventListener('resize', () => { S.dirty = true; });
requestAnimationFrame(frameLoop);
loadTraining();
showView(Q.get('view') || location.hash.slice(1) || 'overview');
(async () => {
  const explicit = Q.get('ws'), auto = location.protocol.startsWith('http') ? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/ui` : null, url = explicit || (Q.get('replay') ? null : auto);
  if (url && await connectLive(url)) return; await tryReplay();
})();
window.__lunar = { S, applyFrame };
