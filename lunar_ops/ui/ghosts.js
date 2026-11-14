// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Ghost runs: drop recorded, simulated attempts (rover_*.json / lander_*.json) and replay them side by side.
// Nothing is invented, tuned or repaired: a file that does not match the format is rejected with a list of what is wrong.
// Everything shown here is MODELLED (simulated). Format: lunar_ops/PROTOCOL.md, "Ghost files".
(function () {
'use strict';
const MC = (window.MC = window.MC || {});
const C = MC.C, esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const G = (MC.ghost = { files: [], idx: -1, t: 0, playing: true, speed: 1, all: false, hidden: new Set(), msgs: [], saved: [] });

const SUCCESS = new Set(['returned', 'ok', 'reached_ice_only']), LATE = new Set(['timeout', 'out_of_fuel', 'out_of_bounds', 'blocked']);
const OUTCOME_WORD = { returned: 'returned', reached_ice_only: 'reached the ice, did not return', died_battery: 'battery empty', blocked: 'blocked', timeout: 'ran out of time', ok: 'landed OK', hard_vertical: 'landed too fast (vertical)', hard_horizontal: 'landed too fast (sideways)', steep_slope: 'landed on a steep slope', hazard_cell: 'landed in a hazard cell', out_of_fuel: 'out of fuel', out_of_bounds: 'left the allowed area' };
const word = (o) => OUTCOME_WORD[o] || o;
const klass = (r) => (r.best ? 'best' : SUCCESS.has(r.outcome) ? 'ok' : LATE.has(r.outcome) ? 'late' : 'crash');
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

// Mirror of lunar_ops/ghosts.py validate_ghost (errors only). The server repeats the check when it stores the file.
function validate(o) {
  const e = [];
  if (!o || typeof o !== 'object' || Array.isArray(o)) return ['top level must be an object'];
  if (!['rover', 'lander'].includes(o.kind)) e.push("'kind' must be 'rover' or 'lander'");
  if (typeof o.region !== 'string' || !o.region) e.push("'region' must be a non-empty string");
  if (!(isNum(o.dt_s) && o.dt_s > 0)) e.push("'dt_s' must be a positive number");
  if (!Array.isArray(o.runs) || !o.runs.length) { e.push("'runs' must be a non-empty list"); return e; }
  const seen = new Set();
  o.runs.forEach((r, i) => {
    let tag = `runs[${i}]`; if (!r || typeof r !== 'object') { e.push(`${tag} must be an object`); return; }
    if (typeof r.id !== 'string' || !r.id) e.push(`${tag}: 'id' must be a non-empty string`); else { if (seen.has(r.id)) e.push(`${tag}: duplicate id '${r.id}'`); seen.add(r.id); tag = `run '${r.id}'`; }
    for (const k of ['policy', 'outcome']) if (typeof r[k] !== 'string' || !r[k]) e.push(`${tag}: '${k}' must be a non-empty string`);
    if (typeof r.best !== 'boolean') e.push(`${tag}: 'best' must be true or false`);
    if (r.fail_t_s != null && !isNum(r.fail_t_s)) e.push(`${tag}: 'fail_t_s' must be a number or null`);
    const t = r.t_s; if (!Array.isArray(t) || !t.length || !t.every(isNum)) { e.push(`${tag}: 't_s' must be a non-empty list of numbers`); return; }
    for (let k = 1; k < t.length; k++) if (t[k] < t[k - 1]) { e.push(`${tag}: 't_s' must not decrease`); break; }
    if (!Array.isArray(r.xyz_m) || r.xyz_m.length !== t.length || !r.xyz_m.every((p) => Array.isArray(p) && p.length === 3 && p.every(isNum))) e.push(`${tag}: 'xyz_m' must be a list of [x, y, z] numbers, one per 't_s' entry`);
    if (r.heading_deg != null && (!Array.isArray(r.heading_deg) || r.heading_deg.length !== t.length || !r.heading_deg.every(isNum))) e.push(`${tag}: 'heading_deg' must be one number per 't_s' entry`);
  });
  return e;
}
MC.ghostValidate = validate;

function msg(kind, text, list) { G.msgs.unshift({ kind, text, list: list || [], at: new Date().toLocaleTimeString() }); if (G.msgs.length > 12) G.msgs.length = 12; MC.S.dirty = true; MC.S.domDirty = true; }
function addGhost(name, obj) {
  const i = G.files.findIndex((f) => f.name === name); const entry = { name, ...obj }; if (i >= 0) G.files[i] = entry; else G.files.push(entry);
  G.idx = i >= 0 ? i : G.files.length - 1; G.t = 0; G.playing = true; G.hidden = new Set(); MC.S.dirty = true;
  const gt = new URLSearchParams(location.search).get('gt'); if (gt !== null) { G.t = Math.min(1, Math.max(0, Number(gt))) * tmax(); G.playing = false; }
}
const cur = () => G.files[G.idx] || null;
// Which runs to show: always the best, at least 2 of each failure type present, then fill up to the cap.
function selectRuns(runs, cap = 12) {
  if (G.all || runs.length <= cap) return runs.slice();
  const pick = new Set(), best = runs.find((r) => r.best); if (best) pick.add(best.id);
  const by = {}; for (const r of runs) (by[r.outcome] = by[r.outcome] || []).push(r);
  for (const [o, list] of Object.entries(by)) if (!SUCCESS.has(o)) for (const r of list.slice(0, 2)) pick.add(r.id);
  for (const r of runs) { if (pick.size >= cap) break; pick.add(r.id); }
  return runs.filter((r) => pick.has(r.id));
}
const shown = () => { const g = cur(); return g ? selectRuns(g.runs).filter((r) => !G.hidden.has(r.id)) : []; };
const tmax = () => Math.max(1, ...shown().map((r) => r.t_s[r.t_s.length - 1]));
// Position at time t. A run with fail_t_s is frozen there. Linear interpolation between the recorded samples.
function stateAt(r, t) {
  const T = r.t_s, frozen = r.fail_t_s != null && t >= r.fail_t_s, tt = r.fail_t_s != null ? Math.min(t, r.fail_t_s) : t; let lo = 0, hi = T.length - 1;
  if (tt <= T[0]) return { p: r.xyz_m[0], tt, frozen, ended: false, k: 0 }; if (tt >= T[hi]) return { p: r.xyz_m[hi], tt, frozen, ended: t >= T[hi], k: hi };
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (T[m] <= tt) lo = m; else hi = m; } const f = (tt - T[lo]) / ((T[hi] - T[lo]) || 1), a = r.xyz_m[lo], b = r.xyz_m[hi];
  return { p: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f], tt, frozen, ended: false, k: lo };
}
function pathLen(r) { let d = 0; for (let i = 1; i < r.xyz_m.length; i++) d += Math.hypot(r.xyz_m[i][0] - r.xyz_m[i - 1][0], r.xyz_m[i][1] - r.xyz_m[i - 1][1]); return d; }
function style(r) { const k = klass(r); return k === 'best' ? { col: C.blue, w: 3.6, dash: [] } : k === 'ok' ? { col: C.blueL, w: 1.8, dash: [] } : k === 'late' ? { col: C.orange, w: 1.8, dash: [6, 4] } : { col: C.orange, w: 2, dash: [] }; }

// ------------------------------------------------------------------------------------------------ files
async function upload(name, buf) {
  try {
    const r = await fetch(`/api/ghosts/${encodeURIComponent(name)}`, { method: 'POST', body: buf }); const j = await r.json().catch(() => ({}));
    if (r.ok && j.saved) { msg('ok', `Saved on the server: runs/ghosts/${name}`, j.warnings); loadSaved(false); } else msg('err', `The server rejected ${name}`, j.errors || [j.detail || `HTTP ${r.status}`]);
  } catch (e) { msg('warn', `The server is not reachable, so ${name} is only loaded in this browser.`); }
}
async function handleFiles(files) {
  for (const f of files) {
    const name = f.name, ext = name.split('.').pop().toLowerCase(), buf = await f.arrayBuffer();
    if (ext === 'jsonl') { try { const frames = new TextDecoder().decode(buf).split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((m) => m.type === 'frame'); if (!frames.length) throw new Error('no frames'); MC.openRecording(frames); msg('ok', `${name}: loaded ${frames.length} frames as a recording`); } catch (e) { msg('err', `${name}: not a recording (${e.message})`); } continue; }
    if (ext === 'json') {
      let obj; try { obj = JSON.parse(new TextDecoder().decode(buf)); } catch (e) { msg('err', `${name}: not valid JSON`, [String(e.message)]); continue; }
      const errs = validate(obj); if (errs.length) { msg('err', `${name}: not loaded. Ask the producer to fix these fields.`, errs.slice(0, 8)); continue; }
      addGhost(name, obj); msg('ok', `${name}: loaded ${obj.runs.length} runs (${obj.kind}, ${obj.region})`); MC.showTab('ghosts'); upload(name, buf); continue;
    }
    if (['obj', 'mtl', 'glb', 'png', 'jpg'].includes(ext)) { msg('ok', `${name}: model or texture file, sending to the server`); upload(name, buf); continue; }
    msg('err', `${name}: file type .${ext} is not supported`);
  }
}
MC.ghostHandleFiles = handleFiles;
async function loadSaved(loadFiles = true) {
  try {
    const r = await fetch('/api/ghosts'); if (!r.ok) return; G.saved = await r.json(); G.serverOk = true; MC.S.dirty = true; if (!loadFiles) return;
    for (const it of G.saved.filter((x) => x.name.endsWith('.json') && x.summary?.kind).slice(0, 6)) { if (G.files.some((f) => f.name === it.name)) continue; const j = await (await fetch(`/api/ghosts/${encodeURIComponent(it.name)}`)).json(); if (!validate(j).length) { const keep = G.idx; addGhost(it.name, j); if (keep >= 0) G.idx = keep; } }
  } catch (e) { G.serverOk = false; }
}
MC.ghostLoadSaved = loadSaved;
addEventListener('dragover', (e) => { if (e.dataTransfer?.types?.includes('Files')) { e.preventDefault(); document.body.classList.add('dragging'); } });
addEventListener('dragleave', (e) => { if (!e.relatedTarget) document.body.classList.remove('dragging'); });
addEventListener('drop', (e) => { if (!e.dataTransfer?.files?.length) return; e.preventDefault(); document.body.classList.remove('dragging'); MC.showTab('ghosts'); handleFiles(e.dataTransfer.files); });
MC.ghostTick = (dt) => { if (!cur() || !G.playing) return; const T = tmax(); G.t += dt * (T / 20) * G.speed; if (G.t >= T) { G.t = T; G.playing = false; } MC.S.dirty = true; };

// ------------------------------------------------------------------------------------------------ panels
const P = MC.panels;
P.ghostdrop = {
  title: 'Add files', src: 'your files', dom: true,
  init(el) {
    el.innerHTML = `<div class="drop" id="gd-zone"><b>Drop files here</b><span>ghost files <code>rover_*.json</code> · <code>lander_*.json</code>, recordings <code>.jsonl</code>, models <code>.obj .glb .mtl</code></span><button id="gd-pick">Choose files…</button><input id="gd-input" type="file" multiple hidden accept=".json,.jsonl,.obj,.mtl,.glb,.png,.jpg"></div><div id="gd-msgs"></div><div id="gd-saved"></div>`;
    const z = el.querySelector('#gd-zone'), inp = el.querySelector('#gd-input'); el.querySelector('#gd-pick').onclick = () => inp.click(); inp.onchange = () => { handleFiles(inp.files); inp.value = ''; };
    z.addEventListener('dragover', (e) => { e.preventDefault(); z.classList.add('over'); }); z.addEventListener('dragleave', () => z.classList.remove('over'));
    el.addEventListener('click', (e) => { const b = e.target.closest('[data-open]'); if (b) { const i = G.files.findIndex((f) => f.name === b.dataset.open); if (i >= 0) { G.idx = i; G.t = 0; G.playing = true; G.hidden = new Set(); MC.S.dirty = true; } } });
  },
  update(el) {
    const m = G.msgs.map((x) => `<div class="gm ${x.kind}"><b>${esc(x.text)}</b>${x.list.length ? '<ul>' + x.list.map((l) => `<li>${esc(l)}</li>`).join('') + '</ul>' : ''}</div>`).join('') || '<div class="gm dim">Nothing added yet. Files you drop are checked first. A file with missing or wrong fields is rejected with a list, never repaired.</div>';
    const s = G.serverOk ? '<h5>Stored on the server (runs/ghosts/)</h5>' + (G.saved.map((x) => `<div class="gs"><span>${esc(x.name)}</span><em>${x.summary?.kind ? `${esc(x.summary.kind)} · ${x.summary.n_runs} runs` : `${(x.size / 1024).toFixed(0)} kB`}</em>${x.summary?.kind ? `<button data-open="${esc(x.name)}">Replay</button>` : ''}</div>`).join('') || '<div class="dim">Nothing stored yet.</div>') : '<div class="dim gm">Server not reachable: files stay in this browser only.</div>';
    const a = el.querySelector('#gd-msgs'), b = el.querySelector('#gd-saved'), hm = m + '|', hs = s + '|'; if (a._h !== hm) { a.innerHTML = m; a._h = hm; } if (b._h !== hs) { b.innerHTML = s; b._h = hs; }
  },
};
P.ghostctl = {
  title: 'Ghost replay controls', src: 'your files', dom: true,
  init(el) {
    el.innerHTML = `<div class="gctl"><button id="gc-play">Pause</button><button id="gc-restart">Restart</button><input id="gc-seek" type="range" min="0" max="1000" value="0"><span id="gc-time" class="mono">0 s</span><label>Speed <select id="gc-speed"><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option></select></label><label>File <select id="gc-file"></select></label><button id="gc-all">Show all runs</button></div>`;
    el.querySelector('#gc-play').onclick = () => { if (G.t >= tmax()) G.t = 0; G.playing = !G.playing; }; el.querySelector('#gc-restart').onclick = () => { G.t = 0; G.playing = true; };
    el.querySelector('#gc-seek').oninput = (e) => { G.t = Number(e.target.value) / 1000 * tmax(); G.playing = false; MC.S.dirty = true; };
    el.querySelector('#gc-speed').onchange = (e) => { G.speed = Number(e.target.value); }; el.querySelector('#gc-file').onchange = (e) => { G.idx = Number(e.target.value); G.t = 0; G.playing = true; G.hidden = new Set(); MC.S.dirty = true; };
    el.querySelector('#gc-all').onclick = () => { G.all = !G.all; MC.S.dirty = true; };
  },
  update(el) {
    const g = cur(), T = tmax(); el.querySelector('#gc-play').textContent = G.playing ? 'Pause' : 'Play'; el.querySelector('#gc-seek').value = String(g ? Math.round(G.t / T * 1000) : 0); el.querySelector('#gc-time').textContent = g ? `${G.t.toFixed(g.dt_s < 10 ? 1 : 0)} of ${T.toFixed(0)} s` : '—';
    const sel = el.querySelector('#gc-file'), h = G.files.map((f) => f.name).join('|') + G.idx; if (sel._h !== h) { sel.innerHTML = G.files.map((f, i) => `<option value="${i}" ${i === G.idx ? 'selected' : ''}>${esc(f.name)}</option>`).join('') || '<option>no ghost file</option>'; sel._h = h; }
    const all = el.querySelector('#gc-all'); all.textContent = g && g.runs.length > 12 ? (G.all ? 'Show 12 runs' : `Show all ${g.runs.length} runs`) : 'Show all runs'; all.disabled = !g || g.runs.length <= 12;
  },
};
P.ghostmap = {
  title: 'Ghost runs · replay of simulated runs (MODELLED)', src: 'your files', canvas: true,
  draw(g, w, h) {
    const f = cur(); if (!f) return MC.empty(g, w, h, 'Drop a ghost file to replay its runs here.'); const runs = shown(), W = MC.S.W, useWorld = W && MC.layerCanvas && W.region === f.region;
    let x0, x1, y0, y1; if (useWorld) { x0 = -W.half_x; x1 = W.half_x; y0 = -W.half_y; y1 = W.half_y; } else { x0 = y0 = Infinity; x1 = y1 = -Infinity; for (const r of runs) for (const p of r.xyz_m) { x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); y0 = Math.min(y0, p[1]); y1 = Math.max(y1, p[1]); } const px = (x1 - x0) * 0.08 + 5, py = (y1 - y0) * 0.08 + 5; x0 -= px; x1 += px; y0 -= py; y1 += py; }
    const m = 10, bottom = 44, s = Math.min((w - 2 * m) / (x1 - x0), (h - 2 * m - bottom) / (y1 - y0)), vx = (w - (x1 - x0) * s) / 2, vy = m + (h - 2 * m - bottom - (y1 - y0) * s) / 2, P2 = (x, y) => [vx + (x - x0) * s, vy + (y1 - y) * s];
    if (useWorld) { g.globalAlpha = 0.55; g.drawImage(MC.layerCanvas, vx, vy, (x1 - x0) * s, (y1 - y0) * s); g.globalAlpha = 1; }
    g.strokeStyle = C.grid; g.lineWidth = 1; g.strokeRect(vx, vy, (x1 - x0) * s, (y1 - y0) * s); g.beginPath(); const step = (x1 - x0) > 4000 ? 1000 : (x1 - x0) > 800 ? 200 : 50; for (let k = Math.ceil(x0 / step) * step; k < x1; k += step) { const [a] = P2(k, 0); g.moveTo(a, vy); g.lineTo(a, vy + (y1 - y0) * s); } for (let k = Math.ceil(y0 / step) * step; k < y1; k += step) { const [, b] = P2(0, k); g.moveTo(vx, b); g.lineTo(vx + (x1 - x0) * s, b); } g.stroke();
    if (!useWorld) MC.txt(g, `terrain for “${f.region}” is not loaded here, plain grid shown`, vx + 6, vy + 14, C.dim, 'left', 10);
    const order = [...runs].sort((a, b) => (a.best ? 1 : 0) - (b.best ? 1 : 0)), labels = [];
    for (const r of order) {
      const st = style(r), S = stateAt(r, G.t); g.setLineDash(st.dash); g.strokeStyle = st.col; g.lineCap = 'round';
      g.globalAlpha = 0.16; g.lineWidth = 1; g.beginPath(); r.xyz_m.forEach((p, i) => { const [x, y] = P2(p[0], p[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
      g.globalAlpha = r.best ? 1 : 0.78; g.lineWidth = st.w; g.beginPath(); for (let i = 0; i <= S.k; i++) { const [x, y] = P2(r.xyz_m[i][0], r.xyz_m[i][1]); i ? g.lineTo(x, y) : g.moveTo(x, y); } const [ex, ey] = P2(S.p[0], S.p[1]); g.lineTo(ex, ey); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
      if (S.frozen && !r.best) { g.strokeStyle = st.col; g.fillStyle = st.col; g.lineWidth = 2.5; if (klass(r) === 'crash') { g.beginPath(); g.moveTo(ex - 7, ey - 7); g.lineTo(ex + 7, ey + 7); g.moveTo(ex + 7, ey - 7); g.lineTo(ex - 7, ey + 7); g.stroke(); } else { g.beginPath(); g.moveTo(ex, ey - 8); g.lineTo(ex + 8, ey); g.lineTo(ex, ey + 8); g.lineTo(ex - 8, ey); g.closePath(); g.stroke(); } labels.push([ex, ey, `${r.id}: ${word(r.outcome)}`, st.col]); }
      else { g.globalAlpha = r.best ? 1 : 0.8; g.fillStyle = r.best ? '#fff' : st.col; g.beginPath(); if (f.kind === 'lander') { g.moveTo(ex, ey - 6); g.lineTo(ex + 6, ey + 5); g.lineTo(ex - 6, ey + 5); g.closePath(); } else g.arc(ex, ey, r.best ? 6 : 4, 0, 7); g.fill(); g.globalAlpha = 1; if (r.best) labels.push([ex, ey, `BEST · ${r.id}${S.ended ? ': ' + word(r.outcome) : ''}`, C.blueL]); }
    }
    for (const [x, y, t, col] of labels) { const tw = MC.txtWidth(g, t, 11) + 14, lx = Math.min(x + 10, w - tw - 4), ly = Math.max(14, y - 22); g.fillStyle = 'rgba(2,4,10,.88)'; g.fillRect(lx, ly, tw, 18); g.strokeStyle = col; g.lineWidth = 1; g.strokeRect(lx + 0.5, ly + 0.5, tw - 1, 17); MC.txt(g, t, lx + 7, ly + 13, col, 'left', 11); }
    const ly = h - 30; [['BEST', C.blue, []], ['reached goal', C.blueL, []], ['crash / died', C.orange, []], ['timeout / fuel / bounds / blocked', C.orange, [6, 4]]].reduce((x, [t, col, dash]) => { g.setLineDash(dash); g.strokeStyle = col; g.lineWidth = 3; g.beginPath(); g.moveTo(x, ly); g.lineTo(x + 22, ly); g.stroke(); g.setLineDash([]); MC.txt(g, t, x + 28, ly + 4, C.text, 'left', 10); return x + 28 + t.length * 5.6 + 20; }, 12);
    MC.txt(g, `${f.kind} ghosts · ${f.region} · MODELLED (simulated) · replay of recorded runs, nothing re-run or tuned`, 12, h - 10, C.dim, 'left', 9);
  },
};
P.ghostz = {
  title: 'Height (z) of each run over time', src: 'your files', canvas: true,
  draw(g, w, h) {
    const f = cur(); if (!f) return MC.empty(g, w, h, 'No ghost file loaded.'); const runs = shown(), T = tmax(), m = { l: 46, r: 10, t: 14, b: 22 }; let lo = Infinity, hi = -Infinity; for (const r of runs) for (const p of r.xyz_m) { lo = Math.min(lo, p[2]); hi = Math.max(hi, p[2]); } if (hi - lo < 1e-9) hi = lo + 1;
    const X = (t) => m.l + t / T * (w - m.l - m.r), Y = (z) => m.t + (1 - (z - lo) / (hi - lo)) * (h - m.t - m.b);
    g.strokeStyle = C.grid; g.lineWidth = 1; g.beginPath(); for (let k = 0; k <= 3; k++) { g.moveTo(m.l, m.t + (h - m.t - m.b) * k / 3); g.lineTo(w - m.r, m.t + (h - m.t - m.b) * k / 3); } g.stroke();
    for (const r of [...runs].sort((a, b) => (a.best ? 1 : 0) - (b.best ? 1 : 0))) { const st = style(r), S = stateAt(r, G.t); g.setLineDash(st.dash); g.strokeStyle = st.col; g.globalAlpha = 0.2; g.lineWidth = 1; g.beginPath(); r.t_s.forEach((t, i) => { i ? g.lineTo(X(t), Y(r.xyz_m[i][2])) : g.moveTo(X(t), Y(r.xyz_m[i][2])); }); g.stroke(); g.globalAlpha = r.best ? 1 : 0.8; g.lineWidth = st.w * 0.7; g.beginPath(); for (let i = 0; i <= S.k; i++) { const px = X(r.t_s[i]), py = Y(r.xyz_m[i][2]); i ? g.lineTo(px, py) : g.moveTo(px, py); } g.lineTo(X(S.tt), Y(S.p[2])); g.stroke(); g.setLineDash([]); g.globalAlpha = 1; if (S.frozen) { g.fillStyle = st.col; g.beginPath(); g.arc(X(S.tt), Y(S.p[2]), 3.5, 0, 7); g.fill(); } }
    g.strokeStyle = C.white; g.globalAlpha = 0.5; g.beginPath(); g.moveTo(X(G.t), m.t); g.lineTo(X(G.t), h - m.b); g.stroke(); g.globalAlpha = 1;
    MC.txt(g, `${hi.toFixed(0)} m`, m.l - 4, m.t + 8, C.dim, 'right', 9, true); MC.txt(g, `${lo.toFixed(0)} m`, m.l - 4, h - m.b, C.dim, 'right', 9, true); MC.txt(g, `0 – ${T.toFixed(0)} s`, m.l, h - 6, C.dim, 'left', 9, true);
  },
};
P.ghostruns = {
  title: 'Runs · who won, who failed and where', src: 'your files', dom: true,
  init(el) { el.addEventListener('click', (e) => { const r = e.target.closest('[data-run]'); if (!r) return; const id = r.dataset.run; G.hidden.has(id) ? G.hidden.delete(id) : G.hidden.add(id); MC.S.dirty = true; }); },
  html() {
    const f = cur(); if (!f) return '<div class="msg">No ghost file loaded yet. Drop one on the right.</div>'; const runs = selectRuns(f.runs), best = f.runs.find((r) => r.best), T = tmax();
    const head = best ? `<div class="gwin"><small>Winner</small><b>${esc(best.id)}</b> · ${esc(best.policy)} · ${esc(word(best.outcome))}</div>` : '<div class="gwin"><small>No run is marked best in this file.</small></div>';
    const order = { best: 0, ok: 1, late: 2, crash: 3 }, sorted = [...runs].sort((a, b) => order[klass(a)] - order[klass(b)]);
    return head + '<table class="tbl"><tr><th></th><th>Run</th><th>Policy</th><th>Outcome</th><th>Now</th><th>Ends at s</th><th>Path m</th></tr>' + sorted.map((r) => { const st = style(r), S = stateAt(r, G.t), off = G.hidden.has(r.id), now = off ? 'hidden' : S.frozen ? `stopped at ${r.fail_t_s.toFixed(0)} s` : S.ended ? 'finished' : 'moving';
      return `<tr data-run="${esc(r.id)}" class="${off ? 'off' : ''}"><td><i class="sw" style="background:${st.col};${st.dash.length ? 'opacity:.7' : ''}"></i></td><td><b>${esc(r.id)}</b>${r.best ? ' <em>BEST</em>' : ''}</td><td>${esc(r.policy)}</td><td class="${klass(r) === 'crash' || klass(r) === 'late' ? 'bad' : 'ok'}">${esc(word(r.outcome))}</td><td class="${S.frozen ? 'bad' : ''}">${now}</td><td>${r.t_s[r.t_s.length - 1].toFixed(0)}</td><td>${pathLen(r).toFixed(0)}</td></tr>`; }).join('')
      + `</table><div class="note">${f.runs.length > runs.length ? `Showing ${runs.length} of ${f.runs.length} runs (the best, and at least 2 of each failure type). ` : ''}Click a row to hide or show a run. Paths are exactly as recorded; positions between samples are linear. Time ${G.t.toFixed(0)} of ${T.toFixed(0)} s.</div>`;
  },
};
})();
