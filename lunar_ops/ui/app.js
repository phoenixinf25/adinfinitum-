// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Adinfinitium Mission Control: 2D viewer. Draws whatever lunar_ops/PROTOCOL.md messages it receives.
// All 3D (vehicle models, descent and surface views) belongs to Basilisk / Vizard, not to this page.
// Palette: midnight black, electric blue, cantaloupe orange. Blue = normal, cantaloupe = needs attention.
'use strict';

const $ = (id) => document.getElementById(id);
const Q = new URLSearchParams(location.search);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const pad = (n, k = 2) => String(Math.floor(n)).padStart(k, '0');
const fmtMET = (t) => { t = Math.max(0, t); return `${pad(t / 86400)}d ${pad(t % 86400 / 3600)}:${pad(t % 3600 / 60)}:${pad(t % 60)}`; };
const fmtSim = (t) => { t = Math.max(0, t); return `${pad(t / 86400)}:${pad(t % 86400 / 3600)}:${pad(t % 3600 / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`; };
const fmtHMS = (t) => `${pad(t % 86400 / 3600)}:${pad(t % 3600 / 60)}:${pad(t % 60)}`;
const DEG = Math.PI / 180;
const PHASES = ['ORBIT', 'DEORBIT', 'DESCENT', 'LANDED', 'ROVER OPS'];
const SPEEDS = [1, 60, 600, 3000, 12000];
const C = { blue: '#2f7dff', blueL: '#8db9ff', blueD: '#14357a', orange: '#ffa566', orangeD: '#5e3a1f', dim: '#6b7d96', grid: '#121b2c', panel: '#070b14' };

function b64(s) { const bin = atob(s), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a; }
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

const S = {
  mode: 'none', ws: null, W: null, worldMsg: null, last: null, lit: null,
  layer: 'terrain', speed: 600, playing: true, override: false, keys: {},
  frames: [], idx: -1, T0: 0, T1: 1, simT: 0,
  trail: [], path: null, hist: [], orbitPts: [], orbitAll: [], desc: [], descAll: [],
  phaseNow: 'ORBIT', lander: null, models: [], training: null, dirty: true,
};

// ---------------------------------------------------------------- canvas helpers
function fit(c) {
  const dpr = window.devicePixelRatio || 1, w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  const g = c.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); return { g, w: c.clientWidth, h: c.clientHeight };
}
function ramp(stops, v) {
  v = clamp(v, 0, 1) * (stops.length - 1); const i = Math.min(Math.floor(v), stops.length - 2), f = v - i, a = stops[i], b = stops[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}
const ICE_RAMP = [[2, 4, 10], [14, 40, 110], [47, 125, 255], [141, 185, 255], [255, 165, 102]]; // black, blue, light blue, cantaloupe (high evidence)
function grid(g, w, h, m) { g.strokeStyle = C.grid; g.lineWidth = 1; g.beginPath(); for (let i = 1; i < 4; i++) { const y = m.t + (h - m.t - m.b) * i / 4; g.moveTo(m.l, y); g.lineTo(w - m.r, y); } g.stroke(); }
function text(g, t, x, y, col = C.dim, align = 'left') { g.fillStyle = col; g.font = '10.5px ui-monospace, Menlo, monospace'; g.textAlign = align; g.fillText(t, x, y); }

// ---------------------------------------------------------------- map layers
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

function drawMap() {
  const c = $('map'), { g, w, h } = fit(c); g.fillStyle = C.panel; g.fillRect(0, 0, w, h);
  const W = S.W; if (!W || !layerCanvas) return;
  const top = 30, bot = 28, s = Math.min(w / (2 * W.half_x), (h - top - bot) / (2 * W.half_y)); view.s = s; view.x0 = (w - 2 * W.half_x * s) / 2; view.y0 = top + (h - top - bot - 2 * W.half_y * s) / 2;
  g.imageSmoothingEnabled = true; g.drawImage(layerCanvas, view.x0, view.y0, 2 * W.half_x * s, 2 * W.half_y * s);
  const f = S.last;
  if (S.path && S.path.length > 1) { g.strokeStyle = C.blueL; g.setLineDash([5, 4]); g.lineWidth = 1.5; g.beginPath(); S.path.forEach((p, i) => { const [x, y] = worldToPx(p[0], p[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); g.setLineDash([]); }
  if (S.trail.length > 1) { g.strokeStyle = C.blue; g.lineWidth = 2.5; g.beginPath(); S.trail.forEach((p, i) => { const [x, y] = worldToPx(p[0], p[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); }
  for (const t of W.targets || []) {
    const [x, y] = worldToPx(t.x_m, t.y_m), st = f?.targets?.find((q) => q.id === t.id), done = st?.sampled, act = f?.drill_target === t.id, col = done ? C.blue : act ? C.blueL : C.orange;
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1.8; g.beginPath(); g.arc(x, y, 6, 0, 7); done || act ? g.fill() : g.stroke(); text(g, t.id, x + 9, y - 7, col);
  }
  if (W.start) { const [x, y] = worldToPx(W.start.x_m, W.start.y_m); g.strokeStyle = C.blueL; g.lineWidth = 1.5; g.strokeRect(x - 5, y - 5, 10, 10); }
  if (S.phaseNow === 'DESCENT' && f?.lander) { const [x, y] = worldToPx(f.lander.x_m, f.lander.y_m); g.fillStyle = C.orange; g.beginPath(); g.arc(x, y, 6, 0, 7); g.fill(); text(g, `${f.lander.alt_m.toFixed(0)} m`, x + 10, y + 4, C.orange); }
  if (f?.pose) { const [x, y] = worldToPx(f.pose.x_m, f.pose.y_m), hd = f.pose.heading_deg * DEG; g.save(); g.translate(x, y); g.rotate(hd); g.fillStyle = f.aborted ? C.orange : '#fff'; g.beginPath(); g.moveTo(0, -10); g.lineTo(7, 8); g.lineTo(-7, 8); g.closePath(); g.fill(); g.restore(); }
  const m100 = 100 * s; g.strokeStyle = '#fff'; g.lineWidth = 2; g.beginPath(); g.moveTo(view.x0 + 12, h - bot + 4); g.lineTo(view.x0 + 12 + m100, h - bot + 4); g.stroke(); text(g, '100 m', view.x0 + 12 + m100 + 8, h - bot + 8, '#fff');
  $('mapkey').textContent = { terrain: 'lit terrain', light: 'illumination · modelled', shadow: 'blue = modelled shadow', ice: 'ice evidence · modelled', hazard: 'orange = hazard' }[S.layer];
}
function mapHover(e) {
  if (!S.W) return; const r = $('map').getBoundingClientRect(), [x, y] = pxToWorld(e.clientX - r.left, e.clientY - r.top);
  const col = Math.floor((x + S.W.half_x) / S.W.mpp), row = Math.floor((S.W.half_y - y) / S.W.mpp), tip = $('maptip');
  if (col < 0 || row < 0 || col >= S.W.cols || row >= S.W.rows) { tip.textContent = ''; return; }
  const i = row * S.W.cols + col;
  tip.textContent = `E ${x.toFixed(0)}  N ${y.toFixed(0)} m · slope ${S.W.slope[i]}° · ice evidence ${(S.W.ice[i] / 255).toFixed(2)} · ${S.W.psr[i] ? 'shadow' : 'not shadow'} · hazard ${(S.W.hazard[i] / 255).toFixed(2)}`;
}

// ---------------------------------------------------------------- context plot (changes with the mission phase)
function ctxMode() { return S.phaseNow === 'ORBIT' || S.phaseNow === 'DEORBIT' ? 'orbit' : S.phaseNow === 'DESCENT' ? 'descent' : 'battery'; }
function drawCtx() {
  const mode = ctxMode(), c = $('ctx'), { g, w, h } = fit(c), m = { l: 6, r: 6, t: 6, b: 16 }; g.clearRect(0, 0, w, h); grid(g, w, h, m);
  $('ctxtitle').textContent = { orbit: 'Orbit · ground track', descent: 'Descent · altitude and vertical speed', battery: 'Battery' }[mode];
  if (mode === 'orbit') {
    const X = (lon) => m.l + (((lon + 180) % 360 + 360) % 360) / 360 * (w - m.l - m.r), Y = (lat) => m.t + (90 - lat) / 180 * (h - m.t - m.b);
    const seg = (pts, col, wd) => { g.strokeStyle = col; g.lineWidth = wd; g.beginPath(); let prev = null; for (const p of pts) { const x = X(p.lon), y = Y(p.lat); if (prev === null || Math.abs(x - prev) > 0.25 * (w - m.l - m.r)) g.moveTo(x, y); else g.lineTo(x, y); prev = x; } g.stroke(); };
    seg(S.orbitAll, C.blueD, 1); seg(S.orbitPts, C.blue, 2);
    if (S.W?.site) { const x = X(S.W.site.lon_deg), y = Y(S.W.site.lat_deg); g.strokeStyle = C.orange; g.lineWidth = 1.5; g.beginPath(); g.arc(x, y, 5, 0, 7); g.stroke(); text(g, 'site', x + 8, y - 4, C.orange); }
    const p = S.orbitPts[S.orbitPts.length - 1]; if (p) { g.fillStyle = '#fff'; g.beginPath(); g.arc(X(p.lon), Y(p.lat), 4, 0, 7); g.fill(); }
    text(g, '+90°', m.l, m.t + 10); text(g, '−90°', m.l, h - m.b - 3); text(g, 'longitude −180° to +180°', m.l, h - 3);
    if (!S.orbitAll.length) text(g, 'no orbit data in this feed', w / 2, h / 2, C.dim, 'center');
  } else if (mode === 'descent') {
    const A = S.descAll; if (A.length < 2) { text(g, 'no descent telemetry in this feed', w / 2, h / 2, C.dim, 'center'); return; }
    const t0 = A[0].t, t1 = A[A.length - 1].t, aMax = Math.max(...A.map((p) => p.alt)), vMin = Math.min(...A.map((p) => p.vz)), vMax = Math.max(...A.map((p) => p.vz), 0.5);
    const X = (t) => m.l + (t - t0) / Math.max(t1 - t0, 1) * (w - m.l - m.r), YA = (a) => h - m.b - a / aMax * (h - m.t - m.b), YV = (v) => h - m.b - (v - vMin) / (vMax - vMin) * (h - m.t - m.b);
    const line = (pts, fy, col, wd) => { g.strokeStyle = col; g.lineWidth = wd; g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.t), fy(p)) : g.moveTo(X(p.t), fy(p)))); g.stroke(); };
    line(A, (p) => YA(p.alt), C.blueD, 1); line(A, (p) => YV(p.vz), C.orangeD, 1);
    if (S.desc.length > 1) { line(S.desc, (p) => YA(p.alt), C.blue, 2.2); line(S.desc, (p) => YV(p.vz), C.orange, 1.6); }
    text(g, `${aMax.toFixed(0)} m`, m.l, m.t + 10, C.blue); text(g, `${vMin.toFixed(0)} m/s`, m.l, h - m.b - 3, C.orange); text(g, 'altitude', m.l, h - 3, C.blue); text(g, 'vertical speed', m.l + 64, h - 3, C.orange);
  } else {
    const H = S.hist; if (H.length < 2) { text(g, 'rover power appears after landing', w / 2, h / 2, C.dim, 'center'); return; }
    const t0 = H[0][0], t1 = H[H.length - 1][0], X = (t) => m.l + (t - t0) / Math.max(t1 - t0, 1) * (w - m.l - m.r), Y = (v) => h - m.b - v * (h - m.t - m.b);
    g.strokeStyle = C.orange; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(m.l, Y(0.2)); g.lineTo(w - m.r, Y(0.2)); g.stroke(); g.setLineDash([]); text(g, '20 % floor', w - m.r, Y(0.2) - 4, C.orange, 'right');
    g.fillStyle = 'rgba(47,125,255,.16)'; g.strokeStyle = C.blue; g.lineWidth = 2; g.beginPath(); H.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1])))); g.stroke(); g.lineTo(X(t1), h - m.b); g.lineTo(X(t0), h - m.b); g.fill();
    g.fillStyle = C.orange; for (const p of H) if (p[2]) g.fillRect(X(p[0]), h - m.b + 4, 2, 4); text(g, 'orange ticks: in sunlight', m.l, h - 3);
  }
}
function drawSky() {
  const c = $('sky'), { g, w, h } = fit(c), m = { l: 6, r: 6, t: 4, b: 14 }; g.clearRect(0, 0, w, h); const f = S.last; if (!f?.sun) return;
  const X = (az) => m.l + ((az % 360 + 360) % 360) / 360 * (w - m.l - m.r), Y = (el) => m.t + (30 - clamp(el, -10, 30)) / 40 * (h - m.t - m.b);
  g.fillStyle = '#0b1424'; g.fillRect(m.l, Y(0), w - m.l - m.r, h - m.b - Y(0)); g.strokeStyle = C.blueD; g.beginPath(); g.moveTo(m.l, Y(0)); g.lineTo(w - m.r, Y(0)); g.stroke();
  const sx = X(f.sun.az_deg), sy = Y(f.sun.elev_deg); g.fillStyle = C.orange; g.beginPath(); g.arc(sx, sy, 6, 0, 7); g.fill(); text(g, `Sun ${f.sun.elev_deg.toFixed(1)}°`, sx + 10, sy + 4, C.orange);
  const eaz = S.W?.sky?.earth_azimuth_deg ?? 180, ex = X(eaz), ey = Y(f.earth_elev_deg ?? 0); g.fillStyle = C.blue; g.beginPath(); g.arc(ex, ey, 5, 0, 7); g.fill(); text(g, `Earth ${(f.earth_elev_deg ?? 0).toFixed(1)}°`, ex + 10, ey + 4, C.blue);
  text(g, 'flat horizon · skyline not in feed', m.l, h - 2);
}
function drawTrain() {
  const T = S.training, wrap = $('trainwrap'); wrap.hidden = !(T && T.rows?.length); if (wrap.hidden) return;
  const c = $('train'), { g, w, h } = fit(c); g.clearRect(0, 0, w, h);
  const rows = T.rows, pick = (keys) => keys.find((k) => typeof rows[rows.length - 1][k] === 'number'), kr = pick(['reward', 'mean_reward', 'return', 'ep_return', 'mean_return']), kl = pick(['loss', 'policy_loss', 'value_loss']);
  const plot = (key, col) => { if (!key) return; const v = rows.map((r) => r[key]).filter((x) => typeof x === 'number'), lo = Math.min(...v), hi = Math.max(...v);
    g.strokeStyle = col; g.lineWidth = 1.6; g.beginPath(); v.forEach((y, i) => { const px = 2 + i / Math.max(v.length - 1, 1) * (w - 4), py = h - 3 - (y - lo) / Math.max(hi - lo, 1e-9) * (h - 6); i ? g.lineTo(px, py) : g.moveTo(px, py); }); g.stroke(); };
  plot(kr, C.blue); plot(kl, C.orange);
}

// ---------------------------------------------------------------- readouts and side panels
function ro(label, value, sub = '', cls = '') { return `<div class="ro"><small>${label}</small><b class="${cls}">${value}</b><i>${sub || '&nbsp;'}</i></div>`; }
function renderReadouts() {
  const f = S.last, W = S.W; if (!f || !W) return; const cells = [ro('Mission time', fmtMET(f.t_s), esc(f.phase || ''))];
  if (f.orbit) { const o = f.orbit; cells.push(ro('Altitude', `${o.alt_km.toFixed(1)} km`), ro('Speed', `${o.speed_m_s.toFixed(0)} m/s`), ro('Orbit', `${o.orbit_no ?? '—'}`), ro('Latitude', `${o.lat_deg.toFixed(1)}°`, `longitude ${o.lon_deg.toFixed(1)}°`)); }
  else if (f.lander) { const l = f.lander, out = l.engines_ok < 5; cells.push(ro('Altitude', `${l.alt_m.toFixed(0)} m`), ro('Vertical speed', `${l.vz_m_s.toFixed(1)} m/s`, `horizontal ${Math.hypot(l.vx_m_s, l.vy_m_s).toFixed(1)} m/s`), ro('Fuel', `${l.fuel_kg.toFixed(0)} kg`, `mass ${l.mass_kg.toFixed(0)} kg`), ro('Thrust', `${l.thrust_n.toFixed(0)} N`, `engines ${l.engines_ok} of 5`, out ? 'cantaloupe' : '')); }
  else if (f.pose) { const lowBat = f.battery_frac < 0.25, slopeBad = f.slope_deg > W.limits.slope_limit_deg;
    cells.push(ro('Battery', `${(f.battery_frac * 100).toFixed(0)}%`, `${f.battery_wh.toFixed(0)} Wh · ${f.solar_w - f.load_w >= 0 ? '+' : '−'}${Math.abs(f.solar_w - f.load_w).toFixed(0)} W`, lowBat ? 'cantaloupe' : 'blue'),
      ro('Slope', `${f.slope_deg.toFixed(1)}°`, `limit ${W.limits.slope_limit_deg}°`, slopeBad ? 'cantaloupe' : ''), ro('Sun', f.lit ? 'Lit' : 'Shadow', f.in_psr ? 'in permanent shadow' : '', f.lit ? 'blue' : ''), ro('Earth link', f.earth_visible ? 'Up' : 'Down', '', f.earth_visible ? 'blue' : 'cantaloupe')); }
  $('readouts').innerHTML = cells.join('');
}
function renderSide() {
  const f = S.last, W = S.W; if (!f || !W) return;
  const l = S.lander, ex = $('ctxextra');
  if (ctxMode() === 'descent' && l) { ex.innerHTML = '<div class="eng"></div>'; const el = ex.firstChild; for (let i = 0; i < 5; i++) { const off = l.engines_ok < 5 && [1, 3].includes(i), hh = off ? 4 : clamp(l.thrust_n / (800 * Math.max(l.engines_ok, 1)) * 100, 3, 100); el.insertAdjacentHTML('beforeend', `<div class="${off ? 'off' : ''}"><i style="height:${hh}%"></i>E${i + 1}</div>`); } } else ex.innerHTML = '';
  const n = (f.targets || []).filter((t) => t.sampled).length;
  $('icetitle').textContent = `Ice evidence · ${n} of ${(W.targets || []).length} sampled`;
  $('ice').innerHTML = (W.targets || []).map((t) => { const st = f.targets?.find((q) => q.id === t.id), act = f.drill_target === t.id, cls = st?.sampled ? 'done' : act ? 'active' : 'open', txt = st?.sampled ? 'sampled' : act ? 'drilling' : 'open';
    return `<div class="row"><span>${esc(t.id)}<span class="meter"><i style="width:${Math.round(t.ice_score * 100)}%"></i></span><span class="dim">${t.ice_score.toFixed(2)} · ${(t.depth_m ?? 0).toFixed(0)} m</span></span><span class="st ${cls}">${txt}</span></div>`; }).join('')
    + '<div class="note">Modelled evidence, not a detection.</div>';
  $('ai').innerHTML = S.models.map((m) => { const cls = m.status === 'attached' ? 'attached' : m.status === 'fallback' ? 'fallback' : 'none';
    return `<div class="row"><span>${esc(m.name)} <span class="dim">${esc(m.kind)}</span></span><span class="st ${cls}">${esc(m.status)}</span></div>`; }).join('');
}
function renderLog(e) {
  const li = document.createElement('li'), k = e.kind; li.className = ['abort', 'dead'].includes(k) ? 'alert' : k === 'agent' ? 'agent' : '';
  li.innerHTML = `<time>${fmtHMS(e.t_s)}</time><span class="m"></span>`; li.lastChild.textContent = e.msg;
  const ol = $('log'); ol.prepend(li); while (ol.children.length > 250) ol.lastChild.remove(); $('logcount').textContent = `${ol.children.length}`;
}

// ---------------------------------------------------------------- frames
function applyFrame(f, light = false) {
  S.last = f; S.phaseNow = f.mission_phase || 'ROVER OPS'; S.dirty = true;
  for (const e of f.events || []) renderLog(e);
  if (f.pose) { const p = f.pose, tr = S.trail; if (!tr.length || Math.hypot(tr[tr.length - 1][0] - p.x_m, tr[tr.length - 1][1] - p.y_m) > 0.5) tr.push([p.x_m, p.y_m]); if (f.path) S.path = f.path; }
  if (f.orbit) S.orbitPts.push({ lat: f.orbit.lat_deg, lon: f.orbit.lon_deg });
  if (f.lander) { S.lander = f.lander; S.desc.push({ t: f.t_s, alt: f.lander.alt_m, vz: f.lander.vz_m_s }); }
  S.hist.push([f.t_s, f.battery_frac ?? 0, f.lit ? 1 : 0]); if (S.hist.length > 600) S.hist.shift();
  if (light) return;
  if (f.lit_bits_b64 && S.W) { const bits = b64(f.lit_bits_b64), n = S.W.rows * S.W.cols, m = new Uint8Array(n); for (let i = 0; i < n; i++) m[i] = (bits[i >> 3] >> (7 - (i & 7))) & 1; S.lit = m; if (S.layer === 'terrain' || S.layer === 'light') buildLayer(); }
  $('simclock').textContent = fmtSim(f.t_s);
  const c = $('control'), src = f.aborted ? 'Safe mode' : { agent: 'AI agent', operator: 'Operator', baseline: 'Baseline', autonomy: 'Autonomy' }[f.control] || '—'; c.textContent = src; c.className = f.aborted ? 'safe' : '';
  const now = PHASES.indexOf(S.phaseNow); for (const li of $('phases').children) { const me = PHASES.indexOf(li.dataset.p); li.classList.toggle('on', me === now); li.classList.toggle('done', me < now); }
  renderReadouts(); renderSide();
}

// ---------------------------------------------------------------- data sources
function loadWorld(m) {
  S.worldMsg = m;
  const h = new Float32Array(b64(m.height_f32).buffer);
  S.W = { ...m, height: h, slope: b64(m.slope_u8), psr: b64(m.psr_u8), ice: b64(m.ice_u8), hazard: b64(m.hazard_u8), site: m.site || { lat_deg: -89.7, lon_deg: 0 } };
  S.lit = null; S.trail = []; S.hist = []; S.orbitPts = []; S.desc = []; S.lander = null; S.last = null; S.path = null; $('log').innerHTML = '';
  S.models = m.models || []; $('site').textContent = `${m.region} · ${m.site.lat_deg.toFixed(2)}°, ${m.site.lon_deg.toFixed(1)}°`;
  const pv = m.provenance || {};
  $('banner').innerHTML = `<b>${esc((pv.terrain || 'provenance unknown').toUpperCase())}</b>ice ${esc(pv.ice_evidence || 'unknown')} · sun ${esc(pv.illumination || 'unknown')} · rover ${esc(pv.rover || 'unknown')}`;
  buildLayer();
}
function notice(html) { const n = $('notice'); n.hidden = !html; n.innerHTML = html || ''; }
function setConn(kind, t) { const c = $('conn'); c.className = kind; c.textContent = `● ${t}`; }
function resetDerived() { S.trail = []; S.hist = []; S.orbitPts = []; S.desc = []; S.lander = null; S.lit = null; S.path = null; $('log').innerHTML = ''; }

function startReplay(world, frames) {
  S.mode = 'replay'; loadWorld(world); S.frames = frames; S.idx = -1; S.T0 = frames[0]?.t_s ?? 0; S.T1 = frames[frames.length - 1]?.t_s ?? 1; S.simT = S.T0; S.playing = true;
  S.orbitAll = frames.filter((f) => f.orbit).map((f) => ({ lat: f.orbit.lat_deg, lon: f.orbit.lon_deg }));
  S.descAll = frames.filter((f) => f.lander).map((f) => ({ t: f.t_s, alt: f.lander.alt_m, vz: f.lander.vz_m_s }));
  setConn('replay', 'Replay'); $('abort').disabled = true; $('override').disabled = true; $('play').textContent = '❚❚'; $('seek').disabled = false;
}
function advanceTo(t) { while (S.idx + 1 < S.frames.length && S.frames[S.idx + 1].t_s <= t) { S.idx++; applyFrame(S.frames[S.idx], S.idx + 1 < S.frames.length && S.frames[S.idx + 1].t_s <= t); } }
function seekTo(t) { S.idx = -1; resetDerived(); S.simT = t; advanceTo(t); $('seek').value = String(((t - S.T0) / Math.max(S.T1 - S.T0, 1)) * 1000); if (S.layer === 'terrain') buildLayer(); }
async function tryReplay() {
  try {
    const [w, r] = await Promise.all([fetch('sample/world.json'), fetch('sample/run.jsonl')]); if (!w.ok || !r.ok) throw new Error('no sample');
    const world = await w.json(), frames = (await r.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l)); notice(''); startReplay(world, frames);
    const seek = Q.get('seek'); if (seek !== null) { S.playing = false; $('play').textContent = '▶'; seekTo(S.T0 + (S.T1 - S.T0) * Number(seek)); }
  } catch (e) { setConn('off', 'No backend'); notice('<b>No backend connected.</b><br><br>Start one that speaks <code>lunar_ops/PROTOCOL.md</code>, for example<br><code>python -m lunar_ops.server</code><br>then reload. This page connects to <code>/ws/ui</code> automatically.'); }
}
function connectLive(url) {
  return new Promise((resolve) => {
    let opened = false; const ws = new WebSocket(url), to = setTimeout(() => { if (!opened) { ws.close(); resolve(false); } }, 1500);
    ws.onopen = () => { opened = true; clearTimeout(to); S.ws = ws; S.mode = 'live'; setConn('live', 'Live'); notice(''); $('abort').disabled = false; $('override').disabled = false; $('seek').disabled = true; resolve(true); };
    ws.onmessage = (ev) => { const m = JSON.parse(ev.data);
      if (m.type === 'world') loadWorld(m); else if (m.type === 'frame' && S.W) applyFrame(m); else if (m.type === 'models') { S.models = m.models; S.dirty = true; renderSide(); }
      else if (m.type === 'state') { S.playing = m.playing; $('play').textContent = m.playing ? '❚❚' : '▶'; } };
    ws.onerror = () => { if (!opened) resolve(false); };
    ws.onclose = () => { if (opened) { setConn('off', 'Disconnected'); S.mode = 'none'; notice('<b>Backend disconnected.</b><br>Reload to reconnect.'); } };
  });
}
function send(o) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(o)); }
async function loadTraining() { try { const r = await fetch('/api/training'); if (r.ok) { S.training = await r.json(); S.dirty = true; } } catch (e) { /* static hosting: no endpoint */ } }

// ---------------------------------------------------------------- controls
function setSpeed(v) { S.speed = v; send({ type: 'cmd', cmd: 'speed', value: v }); }
$('slower').onclick = () => setSpeed(SPEEDS[Math.max(0, SPEEDS.indexOf(S.speed) - 1)] ?? 600);
$('faster').onclick = () => setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(S.speed) + 1)] ?? 3000);
$('play').onclick = () => { S.playing = !S.playing; $('play').textContent = S.playing ? '❚❚' : '▶'; send({ type: 'cmd', cmd: S.playing ? 'play' : 'pause' }); };
$('seek').oninput = (e) => { if (S.mode === 'replay') seekTo(S.T0 + (S.T1 - S.T0) * Number(e.target.value) / 1000); };
$('abort').onclick = () => { if (confirm('Latch safe mode? The rover will stop and abandon any drill.')) send({ type: 'cmd', cmd: 'abort' }); };
$('override').onchange = (e) => { S.override = e.target.checked; send({ type: 'cmd', cmd: 'override', on: S.override }); };
$('openfile').onclick = () => $('filepick').click();
$('filepick').onchange = async (e) => { const f = e.target.files[0]; if (!f || !S.W) return; const frames = (await f.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((m) => m.type === 'frame'); if (frames.length) startReplay(S.worldMsg, frames); };
addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target === document.body) { e.preventDefault(); $('play').click(); } S.keys[e.code] = true; });
addEventListener('keyup', (e) => { S.keys[e.code] = false; });
setInterval(() => { if (!S.override || S.mode !== 'live') return; const k = S.keys; send({ type: 'cmd', cmd: 'drive', v: k.KeyW ? 1 : 0, omega: (k.KeyD ? 1 : 0) - (k.KeyA ? 1 : 0) }); }, 200);
$('map').addEventListener('pointermove', mapHover);
{ const host = $('maplayers'); for (const [id, t] of [['terrain', 'Terrain'], ['light', 'Light'], ['shadow', 'Shadow'], ['ice', 'Ice evidence'], ['hazard', 'Hazard']]) { const b = document.createElement('button'); b.textContent = t; b.dataset.l = id; if (id === S.layer) b.className = 'on'; b.onclick = () => { S.layer = id; for (const x of host.children) x.className = x.dataset.l === id ? 'on' : ''; buildLayer(); }; host.appendChild(b); } }

// ---------------------------------------------------------------- main loop
let tPrev = performance.now(), lastDraw = 0;
function frameLoop(now) {
  const dt = Math.min((now - tPrev) / 1000, 0.1); tPrev = now;
  if (S.mode === 'replay' && S.playing && S.frames.length) { S.simT += dt * S.speed; advanceTo(S.simT); if (S.idx >= S.frames.length - 1) { S.playing = false; $('play').textContent = '▶'; } $('seek').value = String(((S.simT - S.T0) / Math.max(S.T1 - S.T0, 1)) * 1000); S.dirty = true; }
  $('state').textContent = S.playing ? 'Playing' : 'Paused'; $('state').className = S.playing ? 'playing' : ''; $('speedlab').textContent = `${S.speed >= 1000 ? S.speed / 1000 + 'k' : S.speed}×`;
  if ((S.dirty && now - lastDraw > 66) || now - lastDraw > 500) { lastDraw = now; S.dirty = false; drawMap(); drawCtx(); drawSky(); drawTrain(); }
  requestAnimationFrame(frameLoop);
}
addEventListener('resize', () => { S.dirty = true; });
requestAnimationFrame(frameLoop);
loadTraining();
(async () => {
  const explicit = Q.get('ws'), auto = location.protocol.startsWith('http') ? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/ui` : null, url = explicit || (Q.get('replay') ? null : auto);
  if (url && await connectLive(url)) return; await tryReplay();
})();
window.__lunar = { S, applyFrame };
