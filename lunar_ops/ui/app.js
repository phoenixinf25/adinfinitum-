// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Adinfinitium Mission Control: 2D pit-wall viewer. Draws whatever lunar_ops/PROTOCOL.md messages it receives.
// All 3D (vehicle models, descent and surface views) belongs to Basilisk / Vizard, not to this page.
// Palette: midnight black, electric blue, cantaloupe orange. Blue = normal, cantaloupe = needs attention.
(function () {
'use strict';
const MC = (window.MC = window.MC || {});
const $ = (id) => document.getElementById(id), Q = new URLSearchParams(location.search), C = MC.C;
const SPEEDS = [1, 60, 600, 3000, 12000], DEG = Math.PI / 180;
function b64(s) { const bin = atob(s), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a; }

const S = (MC.S = {
  mode: 'none', ws: null, W: null, worldMsg: null, last: null, lit: null, layer: 'terrain', speed: 600, playing: true, override: false, keys: {},
  frames: [], idx: -1, T0: 0, T1: 1, simT: 0, path: null, logs: [], models: [], training: null, dirty: true, tab: 'wall', phaseNow: 'ORBIT',
});

// ---------------------------------------------------------------- workbook layouts: [panel, col1, col2, row1, row2] on a 12 x 12 grid
const LAYOUTS = {
  wall: ['Wall', [['gps', 1, 4, 1, 7], ['traces', 5, 9, 1, 7], ['targets', 10, 12, 1, 5], ['gauges', 10, 12, 6, 7], ['status', 1, 3, 8, 12], ['gantt', 4, 9, 8, 9], ['runtl', 4, 9, 10, 12], ['log', 10, 12, 8, 12]]],
  imagery: ['Imagery', [['imagery', 1, 8, 1, 12], ['locate', 9, 12, 1, 6], ['sitemini', 9, 12, 7, 9], ['track', 9, 12, 10, 12]]],
  charts: ['Charts', [['ouiPower', 1, 4, 1, 4], ['ouiBattery', 5, 8, 1, 4], ['ouiSplit', 9, 10, 1, 4], ['ouiRadar', 11, 12, 1, 4], ['ouiThermal', 1, 4, 5, 8], ['ouiEnergy', 5, 8, 5, 8], ['ouiLander', 9, 12, 5, 8], ['ouiTargets', 1, 4, 9, 12], ['ouiScatter', 5, 8, 9, 12], ['ouiEngines', 9, 10, 9, 12], ['ouiTime', 11, 12, 9, 12]]],
  landing: ['Landing', [['orbit', 1, 4, 1, 5], ['orbtr', 5, 8, 1, 5], ['engines', 9, 12, 1, 5], ['desctr', 1, 8, 6, 12], ['gauges', 9, 12, 6, 9], ['log', 9, 12, 10, 12]]],
  rover: ['Rover', [['gps', 1, 5, 1, 8], ['traces', 6, 9, 1, 8], ['wheels', 10, 12, 1, 4], ['vision', 10, 12, 5, 8], ['profile', 1, 6, 9, 12], ['hist', 7, 9, 9, 12], ['stats', 10, 12, 9, 12]]],
  power: ['Power · Thermal', [['flow', 1, 4, 1, 6], ['budget', 5, 8, 1, 6], ['thermal', 9, 12, 1, 6], ['runtl', 1, 8, 7, 12], ['wheels', 9, 12, 7, 9], ['env', 9, 12, 10, 12]]],
  comms: ['Comms · Sky', [['link', 1, 4, 1, 6], ['sky', 5, 8, 1, 6], ['skytr', 9, 12, 1, 6], ['gantt', 1, 12, 7, 9], ['env', 1, 6, 10, 12], ['stats', 7, 12, 10, 12]]],
  terrain: ['Terrain · Ice', [['map', 1, 6, 1, 9], ['targets', 7, 12, 1, 6], ['hist', 7, 12, 7, 9], ['profile', 1, 6, 10, 12], ['scatter', 7, 12, 10, 12]]],
  ai: ['AI · Systems', [['ai', 1, 6, 1, 5], ['policy', 7, 12, 1, 5], ['train', 1, 6, 6, 9], ['status', 7, 12, 6, 9], ['prov', 1, 6, 10, 12], ['log', 7, 12, 10, 12]]],
  ghosts: ['Ghosts', [['ghostmap', 1, 7, 1, 8], ['ghostctl', 1, 7, 9, 10], ['ghostz', 1, 7, 11, 12], ['ghostruns', 8, 12, 1, 6], ['ghostdrop', 8, 12, 7, 12]]],
  log: ['Log', [['log', 1, 12, 1, 12]]],
};
let live = []; // panel instances on screen
MC.showTab = function (name) {
  if (!LAYOUTS[name]) name = 'wall'; S.tab = name; const wb = $('wb'); for (const p of live) { try { p.root?.unmount(); } catch (e) { /* already gone */ } } wb.innerHTML = ''; live = [];
  for (const b of $('tabs').children) b.classList.toggle('on', b.dataset.tab === name);
  let order = 0; for (const [id, c1, c2, r1, r2] of LAYOUTS[name][1]) {
    const def = MC.panels[id]; if (!def) { console.error('missing panel', id); continue; }
    const sec = document.createElement('section'); sec.className = 'pn'; sec.style.setProperty('--i', String(order++)); sec.style.gridArea = `${r1} / ${c1} / ${r2 + 1} / ${c2 + 1}`;
    sec.innerHTML = `<h3><span class="t">${def.title}</span><span class="ctl"></span><em>${def.src || ''}</em></h3><div class="pb ${def.dom ? 'dom' : ''} ${def.oui ? 'oui' : ''}">${def.canvas ? '<canvas></canvas>' : ''}</div>`;
    const pb = sec.querySelector('.pb'), p = { id, def, el: pb, canvas: pb.querySelector('canvas'), sel: def.ctl?.def, last: null };
    if (def.ctl) { const host = sec.querySelector('.ctl'); for (const [val, lab] of def.ctl.options) { const b = document.createElement('button'); b.textContent = lab; b.className = val === p.sel ? 'on' : ''; b.onclick = () => { p.sel = val; for (const x of host.children) x.className = x === b ? 'on' : ''; def.ctl.onSel?.(val); S.dirty = true; }; host.appendChild(b); } if (def.ctl.def && def.ctl.onSel) def.ctl.onSel(def.ctl.def); }
    wb.appendChild(sec); live.push(p); try { def.init?.(pb, p); } catch (e) { console.error(id, e); }
  }
  if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`); S.dirty = true; renderPanels(performance.now(), true);
};
function renderPanels(now, force) {
  now = performance.now(); force = force || S.domDirty; S.domDirty = false;
  for (const p of live) {
    try {
      if (p.def.oui) { MC.ouiRender(p, now); continue; }
      if (p.canvas) { const fc = MC.fit(p.canvas); if (fc) p.def.draw(fc.g, fc.w, fc.h, p); }
      else { if (p.def.html && (force || now - (p.t || 0) > 250)) { p.t = now; const h = p.def.html(p); if (h !== p.last) { p.el.innerHTML = h; p.last = h; MC.nfHydrate(p.el, p.id); MC.numify(p.el); } } if (p.def.update) { p.def.update(p.el, p); MC.numify(p.el); } }
    } catch (e) { if (!p.err) { console.error(p.id, e); p.err = true; } if (p.canvas) { const fc = MC.fit(p.canvas); if (fc) MC.txt(fc.g, `panel error: ${e.message}`, 10, 20, C.orange, 'left', 11); } }
  }
}
$('tabs').innerHTML = Object.entries(LAYOUTS).map(([k, v]) => `<button data-tab="${k}">${v[0]}</button>`).join('');
for (const b of $('tabs').children) b.onclick = () => MC.showTab(b.dataset.tab);
addEventListener('hashchange', () => { const t = location.hash.slice(1); if (t !== S.tab) MC.showTab(t); });

// ---------------------------------------------------------------- terrain layers (shared by the map panels)
MC.layerCanvas = null;
MC.setLayer = function (L) { S.layer = L; buildLayer(); };
function ramp(stops, v) { v = Math.min(1, Math.max(0, v)) * (stops.length - 1); const i = Math.min(Math.floor(v), stops.length - 2), f = v - i, a = stops[i], b = stops[i + 1]; return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]; }
const ICE_RAMP = [[2, 4, 10], [14, 40, 110], [47, 125, 255], [141, 185, 255], [255, 165, 102]];
function buildLayer() {
  const W = S.W; if (!W) return; const { rows, cols } = W, clamp = MC.clamp;
  if (!MC.layerCanvas) MC.layerCanvas = document.createElement('canvas'); const cv = MC.layerCanvas; cv.width = cols; cv.height = rows;
  const g = cv.getContext('2d'), img = g.createImageData(cols, rows), d = img.data, h = W.height, L = S.layer, at = (r, c) => h[clamp(r, 0, rows - 1) * cols + clamp(c, 0, cols - 1)];
  const lx = Math.cos(45 * DEG) * Math.sin(315 * DEG), ly = Math.cos(45 * DEG) * Math.cos(315 * DEG), lz = Math.sin(45 * DEG);
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const i = r * cols + c, o = i * 4, dzdx = (at(r, c + 1) - at(r, c - 1)) / (2 * W.mpp), dzdy = (at(r - 1, c) - at(r + 1, c)) / (2 * W.mpp), nl = Math.sqrt(dzdx * dzdx + dzdy * dzdy + 1), shade = clamp((-dzdx * lx - dzdy * ly + lz) / nl, 0, 1); let R, G, B;
    if (L === 'terrain') { const lit = S.lit ? S.lit[i] : 1, k = (0.1 + 0.8 * shade) * (lit ? 1 : 0.3); R = 150 * k; G = 168 * k; B = 205 * k + (lit ? 0 : 8); }
    else if (L === 'light') { const lit = S.lit ? S.lit[i] : 1, k = 0.25 + 0.75 * shade; R = lit ? 255 * k : 6; G = lit ? 165 * k : 12; B = lit ? 102 * k : 36; }
    else if (L === 'shadow') { const k = 0.1 + 0.55 * shade; R = 150 * k; G = 168 * k; B = 205 * k; if (W.psr[i]) { R = R * 0.3 + 6; G = G * 0.4 + 30; B = B * 0.5 + 120; } }
    else if (L === 'ice') { [R, G, B] = ramp(ICE_RAMP, W.ice[i] / 255); }
    else { const k = 0.1 + 0.5 * shade, hz = W.hazard[i] / 255; R = 150 * k * (1 - hz) + 255 * hz; G = 168 * k * (1 - hz) + 165 * hz; B = 205 * k * (1 - hz) + 102 * hz; }
    d[o] = R; d[o + 1] = G; d[o + 2] = B; d[o + 3] = 255;
  }
  g.putImageData(img, 0, 0); S.dirty = true;
}

// Plain elevation hillshade (no light mask), blended under the site photo where the photo itself is black (permanent shadow).
MC.shade = null;
function buildShade() {
  const W = S.W; if (!W) return; const { rows, cols } = W, h = W.height, clamp = MC.clamp; if (!MC.shade) MC.shade = document.createElement('canvas'); const cv = MC.shade; cv.width = cols; cv.height = rows;
  const g = cv.getContext('2d'), img = g.createImageData(cols, rows), d = img.data, at = (r, c) => h[clamp(r, 0, rows - 1) * cols + clamp(c, 0, cols - 1)], lx = Math.cos(45 * DEG) * Math.sin(315 * DEG), ly = Math.cos(45 * DEG) * Math.cos(315 * DEG), lz = Math.sin(45 * DEG);
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) { const o = (r * cols + c) * 4, dzdx = (at(r, c + 1) - at(r, c - 1)) / (2 * W.mpp), dzdy = (at(r - 1, c) - at(r + 1, c)) / (2 * W.mpp), k = 255 * clamp((-dzdx * lx - dzdy * ly + lz) / Math.sqrt(dzdx * dzdx + dzdy * dzdy + 1), 0, 1); d[o] = k * 0.8; d[o + 1] = k * 0.88; d[o + 2] = k; d[o + 3] = 255; }
  g.putImageData(img, 0, 0);
}

// ---------------------------------------------------------------- top bar
function lim() { return S.W?.limits || { slope_limit_deg: 20 }; }
function renderTop(f) {
  if (MC.setMet) MC.setMet(f ? f.t_s : 0, S.speed < 30); else $('k-met').textContent = f ? MC.fmtT(f.t_s) + ':' + String(Math.floor(f.t_s % 60)).padStart(2, '0') : '0d 00:00:00';
  $('k-rem').classList.toggle('na', !(f && S.mode === 'replay'));
  if (MC.setRem && f && S.mode === 'replay') MC.setRem(Math.max(0, S.T1 - f.t_s), S.speed < 30); else if (!MC.setRem) $('k-rem').textContent = f && S.mode === 'replay' ? MC.fmtHMS(Math.max(0, S.T1 - f.t_s)) : '—';
  let st = 'WAITING', cl = ''; if (f) { if (f.aborted) { st = 'SAFE MODE'; cl = 'lost'; } else if (f.alive === false) { st = 'LOST'; cl = 'lost'; } else if ((f.battery_frac !== undefined && f.battery_frac < 0.25) || (f.lander && f.lander.engines_ok < 5) || f.slope_deg > lim().slope_limit_deg) { st = 'CAUTION'; cl = 'caution'; } else { st = 'NOMINAL'; cl = 'nominal'; } }
  $('k-status').textContent = st; $('k-status').className = cl; $('k-phase').textContent = f ? `${MC.PH.indexOf(f.mission_phase || 'ROVER OPS') + 1}/5 ${MC.PH_NAME[Math.max(0, MC.PH.indexOf(f.mission_phase || 'ROVER OPS'))]}` : '—';
  $('k-ctl').textContent = f ? (f.aborted ? 'SAFE MODE' : { agent: 'AI AGENT', operator: 'OPERATOR', baseline: 'BASELINE', autonomy: 'AUTOPILOT' }[f.control] || '—') : '—';
  const L = lim(), set = (id, v) => { $(id).className = 'light ' + v; }; set('l-power', f && f.battery_frac !== undefined ? (f.battery_frac < 0.25 ? 'warn' : 'ok') : '');
  set('l-comms', f && f.earth_visible !== undefined ? (f.earth_visible ? 'ok' : 'warn') : ''); set('l-mob', f && f.slope_deg !== undefined ? (f.slope_deg > L.slope_limit_deg ? 'warn' : 'ok') : '');
  const tb = MC.sim.temp.battery[MC.cur]; set('l-therm', Number.isFinite(tb) ? (tb < -5 ? 'warn' : 'ok') : '');
}

// ---------------------------------------------------------------- frames and data sources
function notify(prev, f) {
  if (!prev || S.seeking || !MC.toast) return; const n = MC.PH.indexOf(f.mission_phase || 'ROVER OPS');
  if ((prev.mission_phase || 'ROVER OPS') !== (f.mission_phase || 'ROVER OPS')) MC.toast('info', `Step ${n + 1} of 5: ${MC.PH_NAME[n]}`, { ORBIT: 'Circling the Moon.', DEORBIT: 'Lowering the orbit towards the landing site.', DESCENT: 'Powered descent has started.', LANDED: 'The lander has touched down.', 'ROVER OPS': 'The rover has rolled out and is working.' }[MC.PH[n]]);
  if (prev.battery_frac >= 0.25 && f.battery_frac < 0.25) MC.toast('warning', 'Battery low', `${Math.round(f.battery_frac * 100)} % left, below the 25 % warning line.`);
  if (prev.lander && f.lander && f.lander.engines_ok < prev.lander.engines_ok) MC.toast('error', 'Engine failure', `${f.lander.engines_ok} of 5 engines working. The lander is rebalancing.`);
  if (!prev.aborted && f.aborted) MC.toast('error', 'Safe mode', 'The rover has stopped and is keeping itself safe.');
  if (prev.earth_visible !== undefined && f.earth_visible !== undefined && prev.earth_visible !== f.earth_visible) MC.toast(f.earth_visible ? 'info' : 'warning', f.earth_visible ? 'Earth link up' : 'Earth link lost', f.earth_visible ? 'The rover can talk to Earth.' : 'Earth is below the horizon.');
  const ds = (x) => (x.targets || []).filter((t) => t.sampled).length; if (ds(f) > ds(prev)) MC.toast('success', 'Sample taken', 'An ice target was sampled (evidence, not confirmation).');
}
function applyFrame(f, light = false) {
  notify(S.last, f); S.last = f; S.phaseNow = f.mission_phase || 'ROVER OPS'; S.dirty = true; S.domDirty = true;
  for (const e of f.events || []) { S.logs.unshift(e); } if (S.logs.length > 250) S.logs.length = 250; if (f.path) S.path = f.path;
  if (S.mode === 'live') { if (MC.n() < 30000) { MC.push(f); MC.simUpdate(); } MC.cur = MC.n() - 1; } else MC.cur = S.idx;
  if (light) return;
  if (f.lit_bits_b64 && S.W) { const bits = b64(f.lit_bits_b64), n = S.W.rows * S.W.cols, m = new Uint8Array(n); for (let i = 0; i < n; i++) m[i] = (bits[i >> 3] >> (7 - (i & 7))) & 1; S.lit = m; if (S.layer === 'terrain' || S.layer === 'light') buildLayer(); }
  if (MC.setSim) MC.setSim(f.t_s, S.speed < 30); else $('simclock').textContent = MC.fmtT(f.t_s) + ':' + String(Math.floor(f.t_s % 60)).padStart(2, '0'); renderTop(f);
}
function loadWorld(m) {
  S.worldMsg = m; const h = new Float32Array(b64(m.height_f32).buffer);
  S.W = { ...m, height: h, slope: b64(m.slope_u8), psr: b64(m.psr_u8), ice: b64(m.ice_u8), hazard: b64(m.hazard_u8), site: m.site || { lat_deg: -89.7, lon_deg: 0 } };
  S.lit = null; S.last = null; S.path = null; S.logs = []; S.models = m.models || []; buildLayer(); buildShade(); loadPhoto(m);
}
const PHOTO_PROV = 'LROC NAC controlled south-pole average mosaic, 1 m/px (observed; averaged lighting), Archinal et al. 2023';
MC.photo = null;
function loadPhoto(m) {
  MC.photo = null; const key = String(m.region || '').replace('lola5m_', ''), real = String(m.region || '').startsWith('lola5m_'); const tileUrl = m.photo?.tile || (real ? `assets/${key}/photo_1m.jpg` : ''); if (!tileUrl) return;
  const P = { tile: null, ctx: null, prov: m.photo?.provenance || PHOTO_PROV }; const ld = (url, k) => { if (!url) return; const im = new Image(); im.onload = () => { P[k] = im; S.dirty = true; }; im.onerror = () => {}; im.src = url; };
  ld(tileUrl, 'tile'); ld(m.photo?.context || (real ? `assets/${key}/photo_ctx_2m.jpg` : ''), 'ctx'); MC.photo = P;
}
function notice(html) { const n = $('notice'); n.hidden = !html; n.innerHTML = html || ''; }
function setConn(kind, t) { const c = $('conn'); c.className = kind; c.textContent = t; }
function startReplay(world, frames) {
  S.mode = 'replay'; loadWorld(world); MC.reset(); for (const f of frames) MC.push(f); MC.simUpdate(); MC.cur = -1;
  S.frames = frames; S.idx = -1; S.T0 = frames[0]?.t_s ?? 0; S.T1 = frames[frames.length - 1]?.t_s ?? 1; S.simT = S.T0; S.playing = true;
  setConn('replay', 'Replaying a recording'); $('abort').disabled = true; $('override').disabled = true; $('play').textContent = 'Pause'; $('seek').disabled = false;
}
MC.openRecording = (frames) => { if (S.worldMsg) startReplay(S.worldMsg, frames); };
function advanceTo(t) { while (S.idx + 1 < S.frames.length && S.frames[S.idx + 1].t_s <= t) { S.idx++; applyFrame(S.frames[S.idx], S.idx + 1 < S.frames.length && S.frames[S.idx + 1].t_s <= t); } }
function seekTo(t) { S.seeking = true; S.idx = -1; S.logs = []; S.lit = null; S.path = null; MC.cur = -1; S.simT = t; advanceTo(t); S.seeking = false; $('seek').value = String(((t - S.T0) / Math.max(S.T1 - S.T0, 1)) * 1000); if (S.layer === 'terrain') buildLayer(); S.dirty = true; }
async function tryReplay() {
  try {
    const [w, r] = await Promise.all([fetch('sample/world.json'), fetch('sample/run.jsonl')]); if (!w.ok || !r.ok) throw new Error('no sample');
    const world = await w.json(), frames = (await r.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l)); notice(''); startReplay(world, frames);
    const seek = Q.get('seek'); if (seek !== null) { S.playing = Q.get('play') === '1'; $('play').textContent = S.playing ? 'Pause' : 'Play'; seekTo(S.T0 + (S.T1 - S.T0) * Number(seek)); }
  } catch (e) { setConn('off', 'Not connected'); notice('<b>No mission is connected.</b><br><br>Start one with<br><code>python -m lunar_ops.server</code><br>then reload this page. It connects by itself.'); }
}
function connectLive(url) {
  return new Promise((resolve) => {
    let opened = false; const ws = new WebSocket(url), to = setTimeout(() => { if (!opened) { ws.close(); resolve(false); } }, 1500);
    ws.onopen = () => { opened = true; clearTimeout(to); S.ws = ws; S.mode = 'live'; setConn('live', 'Live from the mission'); notice(''); $('abort').disabled = false; $('override').disabled = false; $('seek').disabled = true; resolve(true); };
    ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.type === 'world') { loadWorld(m); MC.reset(); } else if (m.type === 'frame' && S.W) applyFrame(m); else if (m.type === 'models') { S.models = m.models; S.dirty = true; } else if (m.type === 'state') { S.playing = m.playing; $('play').textContent = m.playing ? 'Pause' : 'Play'; } };
    ws.onerror = () => { if (!opened) resolve(false); };
    ws.onclose = () => { if (opened) { setConn('off', 'Connection lost'); S.mode = 'none'; notice('<b>The connection was lost.</b><br>Reload the page to connect again.'); } };
  });
}
function send(o) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(o)); }
async function loadTraining() { try { const r = await fetch('/api/training'); if (r.ok) { S.training = await r.json(); S.dirty = true; } } catch (e) { /* static hosting: no endpoint */ } }

// ---------------------------------------------------------------- animated clocks (NumberFlow) and colour mode
MC.nfReady = () => { MC.setMet = MC.makeTimeFlow($('k-met')); MC.setRem = MC.makeTimeFlow($('k-rem'), false); MC.setSim = MC.makeTimeFlow($('simclock')); if (S.last) { renderTop(S.last); MC.setSim(S.last.t_s); } S.domDirty = true; S.dirty = true; };
if (MC.NumberFlow) MC.nfReady();
if (Q.get('still') === '1') document.documentElement.classList.add('still');
function setTheme(mode) { document.documentElement.classList.toggle('bw', mode === 'bw'); for (const b of $('theme').children) b.classList.toggle('on', b.dataset.theme === mode); try { localStorage.setItem('mc-theme', mode); } catch (e) { /* private mode */ } S.dirty = true; }
for (const b of $('theme').children) b.onclick = () => setTheme(b.dataset.theme);
setTheme(Q.get('bw') === '1' ? 'bw' : (() => { try { return localStorage.getItem('mc-theme') || 'colour'; } catch (e) { return 'colour'; } })());

// ---------------------------------------------------------------- controls
const setSpeed = (v) => { S.speed = v; send({ type: 'cmd', cmd: 'speed', value: v }); };
$('slower').onclick = () => setSpeed(SPEEDS[Math.max(0, SPEEDS.indexOf(S.speed) - 1)] ?? 600);
$('faster').onclick = () => setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(S.speed) + 1)] ?? 3000);
$('play').onclick = () => { S.playing = !S.playing; $('play').textContent = S.playing ? 'Pause' : 'Play'; send({ type: 'cmd', cmd: S.playing ? 'play' : 'pause' }); };
$('seek').oninput = (e) => { if (S.mode === 'replay') seekTo(S.T0 + (S.T1 - S.T0) * Number(e.target.value) / 1000); };
$('abort').onclick = () => { if (confirm('Stop the rover and keep it safe? It will abandon any drilling.')) send({ type: 'cmd', cmd: 'abort' }); };
$('override').onchange = (e) => { S.override = e.target.checked; send({ type: 'cmd', cmd: 'override', on: S.override }); };
$('openfile').onclick = () => $('filepick').click();
$('filepick').onchange = (e) => { MC.ghostHandleFiles(e.target.files); e.target.value = ''; };
addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target === document.body) { e.preventDefault(); $('play').click(); } S.keys[e.code] = true; });
addEventListener('keyup', (e) => { S.keys[e.code] = false; });
setInterval(() => { if (!S.override || S.mode !== 'live') return; const k = S.keys; send({ type: 'cmd', cmd: 'drive', v: k.KeyW ? 1 : 0, omega: (k.KeyD ? 1 : 0) - (k.KeyA ? 1 : 0) }); }, 200);

// ---------------------------------------------------------------- main loop
let tPrev = performance.now(), lastDraw = 0;
function frameLoop(now) {
  const dt = Math.min((now - tPrev) / 1000, 0.1); tPrev = now;
  if (S.mode === 'replay' && S.playing && S.frames.length) { S.simT += dt * S.speed; advanceTo(S.simT); if (S.idx >= S.frames.length - 1) { S.playing = false; $('play').textContent = 'Play'; } $('seek').value = String(((S.simT - S.T0) / Math.max(S.T1 - S.T0, 1)) * 1000); S.dirty = true; }
  if (S.tab === 'ghosts') MC.ghostTick(dt);
  $('speedlab').textContent = `${S.speed >= 1000 ? S.speed / 1000 + 'k' : S.speed}×`; MC.numify($('speedlab')); MC.numify($('k-phase')); MC.numify($('k-ctl'));
  if ((S.dirty && now - lastDraw > 66) || now - lastDraw > 500) { lastDraw = now; S.dirty = false; renderPanels(now, false); }
  requestAnimationFrame(frameLoop);
}
addEventListener('resize', () => { S.dirty = true; });
if (document.fonts) { document.fonts.load('13px "Instrument Sans"'); document.fonts.load('500 12px "JetBrains Mono"'); document.fonts.ready.then(() => { S.dirty = true; S.domDirty = true; }); }
MC.showTab(Q.get('tab') || location.hash.slice(1) || 'wall'); requestAnimationFrame(frameLoop); loadTraining(); MC.ghostLoadSaved(true);
(async () => {
  const explicit = Q.get('ws'), auto = location.protocol.startsWith('http') ? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/ui` : null, url = explicit || (Q.get('replay') ? null : auto);
  if (url && await connectLive(url)) return; await tryReplay();
})();
window.__lunar = { S, MC, applyFrame };
})();
