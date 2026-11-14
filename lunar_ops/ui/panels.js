// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Panel library. A panel is {title, src, canvas|dom, ctl?, draw(g,w,h,p) | html(p) | init(el,p)}.
// src says where the numbers come from: feed (mission data), derived (computed from it), simulated (a simple model).
(function () {
'use strict';
const MC = (window.MC = window.MC || {});
MC.panels = {};
const C = MC.C, P = MC.panels, esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const f1 = (v, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : '—');
const lim = () => MC.S.W?.limits || { battery_capacity_wh: 350, solar_peak_w: 50, slope_limit_deg: 20, max_speed_m_s: 0.01 };
function photoRectHoist() {}
const roverPos = () => ({ x: MC.lastFinite('x'), y: MC.lastFinite('y') });
const phaseNow = () => MC.at('ph');

// ------------------------------------------------------------------------------------------------ maps
function mapFrame(g, w, h, bottom) {
  const W = MC.S.W, m = 8, s = Math.min((w - 2 * m) / (2 * W.half_x), (h - 2 * m - bottom) / (2 * W.half_y)), vx = (w - 2 * W.half_x * s) / 2, vy = m + (h - 2 * m - bottom - 2 * W.half_y * s) / 2;
  return { s, vx, vy, P: (x, y) => [vx + (x + W.half_x) * s, vy + (W.half_y - y) * s] };
}
function drawTargets(g, M, big) {
  const W = MC.S.W, f = MC.S.last;
  for (const t of W.targets || []) {
    const [x, y] = M.P(t.x_m, t.y_m), st = f?.targets?.find((q) => q.id === t.id), done = st?.sampled, act = f?.drill_target === t.id, col = done ? C.blue : act ? C.blueL : C.orange;
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1.6; g.beginPath(); g.arc(x, y, big ? 6 : 4, 0, 7); done || act ? g.fill() : g.stroke(); if (big) MC.txt(g, t.id, x + 9, y - 7, col, 'left', 11);
  }
  if (W.start) { const [x, y] = M.P(W.start.x_m, W.start.y_m); g.strokeStyle = C.blueL; g.lineWidth = 1.5; g.strokeRect(x - 4, y - 4, 8, 8); }
}
function drawRover(g, M, big) {
  const i = MC.cur, x = MC.at('x', i), y = MC.at('y', i), hd = MC.at('hd', i); if (!Number.isFinite(x)) return;
  const [px, py] = M.P(x, y); g.save(); g.translate(px, py);
  if (Number.isFinite(hd)) { g.rotate(hd * Math.PI / 180); g.fillStyle = MC.S.last?.aborted ? C.orange : '#fff'; g.beginPath(); g.moveTo(0, -9); g.lineTo(6, 7); g.lineTo(-6, 7); g.closePath(); g.fill(); }
  else { g.fillStyle = C.orange; g.beginPath(); g.arc(0, 0, big ? 6 : 4, 0, 7); g.fill(); }
  g.restore();
}
P.gps = {
  title: 'Rover GPS · coloured by', src: 'feed', canvas: true, ctl: { options: [['soc', 'Battery'], ['speed', 'Speed'], ['slope', 'Slope'], ['lit', 'Sun'], ['haz', 'Hazard']], def: 'soc' },
  draw(g, w, h, p) {
    const S = MC.S, W = S.W; if (!W) return MC.empty(g, w, h, 'Waiting for the map…');
    const M = mapFrame(g, w, h, 20), c = MC.cols, n = MC.n(), cur = MC.cur, key = p.sel, L = lim();
    if (MC.photo?.tile) { g.globalAlpha = 0.6; g.filter = 'brightness(1.6)'; photoRect(g, MC.photo.tile, W.half_x, -W.half_x, W.half_x, -W.half_y, W.half_y, M.vx, M.vy, 2 * W.half_x * M.s, 2 * W.half_y * M.s); g.filter = 'none'; g.globalAlpha = 1; } else if (MC.layerCanvas) { g.globalAlpha = 0.3; g.drawImage(MC.layerCanvas, M.vx, M.vy, 2 * W.half_x * M.s, 2 * W.half_y * M.s); g.globalAlpha = 1; }
    g.strokeStyle = C.grid; g.lineWidth = 1; g.strokeRect(M.vx, M.vy, 2 * W.half_x * M.s, 2 * W.half_y * M.s);
    g.beginPath(); for (let k = -2000; k <= 2000; k += 500) { if (Math.abs(k) >= W.half_x) continue; const [x] = M.P(k, 0), [, y] = M.P(0, k); g.moveTo(x, M.vy); g.lineTo(x, M.vy + 2 * W.half_y * M.s); g.moveTo(M.vx, y); g.lineTo(M.vx + 2 * W.half_x * M.s, y); } g.stroke();
    const scale = { soc: [0, 1], speed: [0, L.max_speed_m_s * 100], slope: [0, L.slope_limit_deg], lit: [0, 1], haz: [0, 1] }[key];
    g.lineWidth = 3; g.lineCap = 'round';
    for (let i = 0; i < n - 1; i++) {
      const x0 = c.x[i], y0 = c.y[i], x1 = c.x[i + 1], y1 = c.y[i + 1]; if (![x0, y0, x1, y1].every(Number.isFinite)) continue;
      const v = c[key][i], bad = (key === 'slope' && v > L.slope_limit_deg) || (key === 'haz' && v > 0.5) || (key === 'soc' && v < 0.25);
      g.strokeStyle = !Number.isFinite(v) ? C.blueD : bad ? C.orange : MC.heat(0.25 + 0.75 * (v - scale[0]) / (scale[1] - scale[0] || 1)); g.globalAlpha = i < cur ? 1 : 0.22;
      const [a, b] = M.P(x0, y0), [d, e] = M.P(x1, y1); g.beginPath(); g.moveTo(a, b); g.lineTo(d, e); g.stroke();
      if (Number.isFinite(c.dist[i]) && Math.floor(c.dist[i + 1] / 100) > Math.floor(c.dist[i] / 100)) { g.globalAlpha = 1; g.fillStyle = C.white; g.fillRect(d - 2, e - 2, 4, 4); MC.txt(g, `${Math.floor(c.dist[i + 1] / 100) * 100} m`, d + 5, e - 4, C.dim, 'left', 9, true); }
    }
    g.globalAlpha = 1; g.lineCap = 'butt'; drawTargets(g, M, true); drawRover(g, M, true);
    const gx = 12, gw = Math.min(220, w - 24), gy = h - 14; for (let k = 0; k < gw; k++) { g.fillStyle = MC.heat(0.25 + 0.75 * k / gw); g.fillRect(gx + k, gy, 1, 6); }
    MC.txt(g, f1(scale[0], 0), gx, gy - 2, C.dim, 'left', 9, true); MC.txt(g, f1(scale[1], key === 'soc' || key === 'haz' || key === 'lit' ? 1 : 0), gx + gw, gy - 2, C.dim, 'right', 9, true);
    MC.txt(g, 'orange = out of limits', gx + gw + 10, gy + 6, C.orange, 'left', 9);
  },
};
P.map = {
  title: 'Terrain map · layer', src: 'feed', canvas: true, ctl: { options: [['terrain', 'Ground'], ['light', 'Sunlight'], ['shadow', 'Dark craters'], ['ice', 'Ice signs'], ['hazard', 'Danger']], def: 'terrain', onSel: (v) => MC.setLayer(v) },
  init(el, p) { p.hover = ''; el.querySelector('canvas').addEventListener('pointermove', (e) => { const W = MC.S.W, c = e.currentTarget, r = c.getBoundingClientRect(); if (!W || !p.M) return; const x = (e.clientX - r.left - p.M.vx) / p.M.s - W.half_x, y = W.half_y - (e.clientY - r.top - p.M.vy) / p.M.s, col = Math.floor((x + W.half_x) / W.mpp), row = Math.floor((W.half_y - y) / W.mpp);
    p.hover = col < 0 || row < 0 || col >= W.cols || row >= W.rows ? '' : (() => { const i = row * W.cols + col; return `E ${x.toFixed(0)}  N ${y.toFixed(0)} m · slope ${W.slope[i]}° · ice signs ${(W.ice[i] / 255).toFixed(2)} · shadow crater ${W.psr[i] ? 'yes' : 'no'} · hazard ${(W.hazard[i] / 255).toFixed(2)}`; })(); MC.S.dirty = true; }); },
  draw(g, w, h, p) {
    const S = MC.S, W = S.W; if (!W || !MC.layerCanvas) return MC.empty(g, w, h, 'Waiting for the map…'); const M = (p.M = mapFrame(g, w, h, 22));
    g.imageSmoothingEnabled = true; g.drawImage(MC.layerCanvas, M.vx, M.vy, 2 * W.half_x * M.s, 2 * W.half_y * M.s);
    const c = MC.cols, n = MC.n(), cur = MC.cur;
    if (S.path && S.path.length > 1) { g.strokeStyle = C.blueL; g.setLineDash([6, 5]); g.lineWidth = 1.5; g.beginPath(); S.path.forEach((q, i) => { const [x, y] = M.P(q[0], q[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); g.setLineDash([]); }
    g.strokeStyle = C.blue; g.lineWidth = 2.5; g.beginPath(); let pen = false; for (let i = 0; i <= cur && i < n; i++) { if (!Number.isFinite(c.hd[i])) { pen = false; continue; } const [x, y] = M.P(c.x[i], c.y[i]); pen ? g.lineTo(x, y) : g.moveTo(x, y); pen = true; } g.stroke();
    drawTargets(g, M, true); drawRover(g, M, true);
    const m100 = 100 * M.s; g.strokeStyle = '#fff'; g.lineWidth = 3; g.beginPath(); g.moveTo(M.vx + 8, h - 12); g.lineTo(M.vx + 8 + m100, h - 12); g.stroke(); MC.txt(g, '100 m', M.vx + 14 + m100, h - 8, C.text, 'left', 10, true);
    MC.txt(g, p.hover || 'Point at the map to read the ground there.', w - 8, h - 8, C.dim, 'right', 10);
  },
};

// ------------------------------------------------------------------------------------------------ imagery
// Draw the world rectangle [x0,x1] x [y0,y1] (metres, y north) of an image whose extent is +-half metres about the tile centre.
function photoRect(g, img, half, x0, x1, y0, y1, dx, dy, dw, dh) {
  if (!img) return false; const k = img.width / (2 * half), sx0 = (x0 + half) * k, sx1 = (x1 + half) * k, sy0 = (half - y1) * k, sy1 = (half - y0) * k;
  const cx0 = Math.max(0, sx0), cx1 = Math.min(img.width, sx1), cy0 = Math.max(0, sy0), cy1 = Math.min(img.height, sy1); if (cx1 <= cx0 || cy1 <= cy0) return false;
  const fx = dw / (sx1 - sx0), fy = dh / (sy1 - sy0); g.drawImage(img, cx0, cy0, cx1 - cx0, cy1 - cy0, dx + (cx0 - sx0) * fx, dy + (cy0 - sy0) * fy, (cx1 - cx0) * fx, (cy1 - cy0) * fy); return true;
}
const landerSite = () => { const W = MC.S.W; return W?.start ? { x: W.start.x_m, y: W.start.y_m } : { x: 0, y: 0 }; };
function vehicles() {
  const c = MC.cols, i = MC.cur, ph = MC.at('ph'), W = MC.S.W; const rov = Number.isFinite(MC.at('hd')) ? { x: MC.at('x'), y: MC.at('y'), hd: MC.at('hd') } : null;
  let lander = null, state = 'Waiting'; if (ph <= 1) state = 'In orbit'; else if (ph === 2 && Number.isFinite(MC.at('alt'))) { lander = { x: MC.at('x'), y: MC.at('y'), alt: MC.at('alt') }; state = 'Descending'; } else if (ph >= 3) { lander = { ...landerSite(), alt: 0 }; state = 'On the surface'; }
  return { rov, lander, state, ph };
}
P.imagery = {
  title: 'Site imagery · lander and rover', src: 'observed image + feed', canvas: true, ctl: { options: [['auto', 'Auto'], ['rover', 'Rover'], ['lander', 'Lander'], ['site', 'Whole site'], ['wide', 'Wide']], def: 'auto' },
  draw(g, w, h, p) {
    const S = MC.S, W = S.W, ph = MC.photo; if (!W) return MC.empty(g, w, h, 'Waiting for the map…'); const v = vehicles(); let mode = p.sel;
    if (mode === 'auto') mode = v.ph === 2 ? 'lander' : v.ph >= 3 && v.rov ? 'rover' : 'site';
    let cx = 0, cy = 0, span = 2 * W.half_x * 1.02; const tgt = mode === 'rover' ? v.rov : mode === 'lander' ? v.lander : null;
    if (mode === 'rover') span = 420; else if (mode === 'lander') span = v.ph === 2 ? 900 : 260; else if (mode === 'wide') span = 5200;
    if (tgt && Number.isFinite(tgt.x)) { cx = tgt.x; cy = tgt.y; } else if ((mode === 'rover' || mode === 'lander') && !tgt) { const o = mode === 'rover' ? landerSite() : landerSite(); cx = o.x; cy = o.y; }
    const sm = (p.sm = p.sm || { cx, cy, span }); const k = 0.18; sm.cx += (cx - sm.cx) * k; sm.cy += (cy - sm.cy) * k; sm.span += (span - sm.span) * k; if (Math.abs(cx - sm.cx) + Math.abs(cy - sm.cy) + Math.abs(span - sm.span) > 0.5) MC.S.dirty = true;
    const s = Math.min(w, h) / sm.span, X0 = sm.cx - w / (2 * s), X1 = sm.cx + w / (2 * s), Y0 = sm.cy - h / (2 * s), Y1 = sm.cy + h / (2 * s), Pm = (x, y) => [w / 2 + (x - sm.cx) * s, h / 2 - (y - sm.cy) * s];
    MC.imgView = { cx: sm.cx, cy: sm.cy, w: w / s, h: h / s };
    g.filter = 'brightness(1.9) contrast(1.12)'; if (ph?.ctx) photoRect(g, ph.ctx, ph.ctx.width, X0, X1, Y0, Y1, 0, 0, w, h); if (ph?.tile) photoRect(g, ph.tile, W.half_x, X0, X1, Y0, Y1, 0, 0, w, h); g.filter = 'none';
    if (MC.shade && (ph?.tile || ph?.ctx)) { g.globalCompositeOperation = 'lighten'; g.globalAlpha = 0.5; photoRect(g, MC.shade, W.half_x, X0, X1, Y0, Y1, 0, 0, w, h); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; }
    if (!ph?.tile && !ph?.ctx && MC.layerCanvas) { g.globalAlpha = 0.9; photoRect(g, MC.layerCanvas, W.half_x, X0, X1, Y0, Y1, 0, 0, w, h); g.globalAlpha = 1; }
    // site grid every 100 m or 500 m
    const step = sm.span > 3000 ? 500 : sm.span > 800 ? 100 : 50; g.strokeStyle = 'rgba(141,185,255,.14)'; g.lineWidth = 1; g.beginPath(); for (let x = Math.ceil(X0 / step) * step; x < X1; x += step) { const [a] = Pm(x, 0); g.moveTo(a, 0); g.lineTo(a, h); } for (let y = Math.ceil(Y0 / step) * step; y < Y1; y += step) { const [, b] = Pm(0, y); g.moveTo(0, b); g.lineTo(w, b); } g.stroke();
    // targets
    const f = S.last; for (const t of W.targets || []) { const [x, y] = Pm(t.x_m, t.y_m); if (x < -20 || y < -20 || x > w + 20 || y > h + 20) continue; const st = f?.targets?.find((q) => q.id === t.id), done = st?.sampled, act = f?.drill_target === t.id, col = done ? C.blue : act ? C.blueL : C.orange; g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 2; g.beginPath(); g.arc(x, y, 8, 0, 7); done || act ? g.fill() : g.stroke(); MC.txt(g, t.id, x + 12, y - 9, col, 'left', 12); }
    // lander descent trail coloured by altitude
    const c = MC.cols, n = MC.n(), cur = MC.cur, aMax = MC.range('alt')[1] || 1;
    g.lineCap = 'round'; for (let i = 0; i < n - 1; i++) { if (c.ph[i] !== 2 || !Number.isFinite(c.alt[i]) || !Number.isFinite(c.alt[i + 1])) continue; const [a, b] = Pm(c.x[i], c.y[i]), [d, e] = Pm(c.x[i + 1], c.y[i + 1]); g.globalAlpha = i < cur ? 1 : 0.25; g.strokeStyle = MC.heat(0.2 + 0.8 * (1 - c.alt[i] / aMax)); g.lineWidth = 3; g.beginPath(); g.moveTo(a, b); g.lineTo(d, e); g.stroke(); } g.globalAlpha = 1;
    // rover trail: fades with age, chevrons show the direction of travel
    const idx = []; for (let i = 0; i <= cur && i < n; i++) if (Number.isFinite(c.hd[i])) idx.push(i);
    for (let k = 1; k < idx.length; k++) { const i0 = idx[k - 1], i1 = idx[k], [a, b] = Pm(c.x[i0], c.y[i0]), [d, e] = Pm(c.x[i1], c.y[i1]); g.strokeStyle = C.blue; g.globalAlpha = 0.25 + 0.75 * (k / idx.length); g.lineWidth = 3.5; g.beginPath(); g.moveTo(a, b); g.lineTo(d, e); g.stroke(); if (k % 5 === 0) { const ang = Math.atan2(e - b, d - a); g.globalAlpha = 1; g.fillStyle = C.blueL; g.save(); g.translate(d, e); g.rotate(ang); g.beginPath(); g.moveTo(5, 0); g.lineTo(-4, -4); g.lineTo(-4, 4); g.closePath(); g.fill(); g.restore(); } }
    g.globalAlpha = 1; for (let k = 0; k < idx.length; k++) { const i = idx[k]; if (k && k % 12 !== 0) continue; const [x, y] = Pm(c.x[i], c.y[i]); g.fillStyle = C.white; g.fillRect(x - 2, y - 2, 4, 4); if (s * 100 > 40) MC.txt(g, MC.fmtHMS(c.t[i]).slice(0, 5), x + 5, y + 12, C.text, 'left', 9, true); }
    if (S.path && S.path.length > 1) { g.strokeStyle = C.blueL; g.setLineDash([6, 5]); g.lineWidth = 1.8; g.beginPath(); S.path.forEach((q, i) => { const [x, y] = Pm(q[0], q[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); g.setLineDash([]); }
    const call = (x, y, lines, col) => { const tw = Math.max(...lines.map((t) => MC.txtWidth(g, t, 11.5))) + 18, lx = Math.min(Math.max(4, x + 16), w - tw - 4), ly = Math.min(Math.max(4, y - 20), h - 16 * lines.length - 10); g.fillStyle = 'rgba(2,4,10,.86)'; g.fillRect(lx, ly, tw, 16 * lines.length + 6); g.strokeStyle = col; g.lineWidth = 1; g.strokeRect(lx + 0.5, ly + 0.5, tw - 1, 16 * lines.length + 5); lines.forEach((t, i) => MC.txt(g, t, lx + 9, ly + 16 + i * 16 - 3, i ? C.text : col, 'left', 11.5)); g.strokeStyle = col; g.beginPath(); g.moveTo(x, y); g.lineTo(lx, ly + 8); g.stroke(); };
    // lander
    const L = landerSite(); if (v.state !== 'In orbit') { const lp = v.lander || L, [x, y] = Pm(lp.x, lp.y); g.strokeStyle = C.blueL; g.lineWidth = 2; g.strokeRect(x - 8, y - 8, 16, 16); if (v.state === 'Descending') { g.fillStyle = C.orange; g.beginPath(); g.moveTo(x, y - 11); g.lineTo(x + 10, y + 8); g.lineTo(x - 10, y + 8); g.closePath(); g.fill(); g.strokeStyle = C.orange; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(x, y); g.lineTo(x, y + 26); g.stroke(); g.setLineDash([]); } else { g.fillStyle = C.blueL; g.fillRect(x - 3, y - 3, 6, 6); }
      call(x, y, [v.state === 'Descending' ? 'LANDER · descending' : 'LANDER · touchdown point', `E ${lp.x.toFixed(0)}  N ${lp.y.toFixed(0)} m`, v.state === 'Descending' ? `altitude ${lp.alt.toFixed(0)} m · fall ${Math.abs(MC.lastFinite('vz')).toFixed(1)} m/s` : `rover is ${v.rov ? Math.hypot(v.rov.x - lp.x, v.rov.y - lp.y).toFixed(0) : '—'} m away`], v.state === 'Descending' ? C.orange : C.blueL); }
    // rover
    if (v.rov) { const [x, y] = Pm(v.rov.x, v.rov.y), a = v.rov.hd * Math.PI / 180; g.save(); g.translate(x, y); g.rotate(a); g.fillStyle = S.last?.aborted ? C.orange : '#fff'; g.strokeStyle = C.blue; g.lineWidth = 2; g.beginPath(); g.moveTo(0, -13); g.lineTo(9, 10); g.lineTo(-9, 10); g.closePath(); g.fill(); g.stroke(); g.restore();
      call(x, y + 40, ['ROVER · ' + (MC.MODES[MC.at('mode')] || '—'), `E ${v.rov.x.toFixed(0)}  N ${v.rov.y.toFixed(0)} m`, `heading ${v.rov.hd.toFixed(0)}° · ${MC.at('speed').toFixed(2)} cm/s`, `driven ${MC.lastFinite('dist').toFixed(0)} m`], C.white); }
    if (v.state === 'In orbit') { const lat = MC.lastFinite('lat'), lon = MC.lastFinite('lon'); call(w / 2 - 80, h / 2, ['LANDER · in orbit', `${v.ph === 0 ? 'circling at' : 'lowering to'} ${f1(MC.lastFinite('orbAlt'))} km`, `over ${f1(lat)}°, ${f1(lon)}°`, 'imagery shows the landing site below'], C.blueL); }
    // scale bar + north + credit
    const nice = [10, 20, 50, 100, 200, 500, 1000, 2000].find((m) => m * s > 90) || 2000; g.strokeStyle = '#fff'; g.lineWidth = 3; g.beginPath(); g.moveTo(14, h - 34); g.lineTo(14 + nice * s, h - 34); g.stroke(); MC.txt(g, `${nice} m`, 14 + nice * s + 8, h - 30, C.white, 'left', 11, true);
    g.fillStyle = '#fff'; g.beginPath(); g.moveTo(w - 26, 16); g.lineTo(w - 20, 32); g.lineTo(w - 32, 32); g.closePath(); g.fill(); MC.txt(g, 'N', w - 26, 48, C.white, 'center', 11);
    MC.txt(g, ph?.tile || ph?.ctx ? `Image: ${ph.prov}. Where the photo is black, LOLA elevation hillshade is blended in.` : 'No site photo available: showing the terrain model instead', 12, h - 10, C.dim, 'left', 9); MC.txt(g, `view ${sm.span.toFixed(0)} m wide`, w - 12, h - 10, C.dim, 'right', 9, true);
  },
};
P.sitemini = {
  title: 'Site overview · where the view is', src: 'observed image + feed', canvas: true,
  draw(g, w, h) {
    const W = MC.S.W; if (!W) return MC.empty(g, w, h, 'Waiting…'); const m = 6, s = Math.min((w - 2 * m) / (2 * W.half_x), (h - 2 * m) / (2 * W.half_y)), vx = (w - 2 * W.half_x * s) / 2, vy = (h - 2 * W.half_y * s) / 2, Pm = (x, y) => [vx + (x + W.half_x) * s, vy + (W.half_y - y) * s];
    if (MC.photo?.tile) photoRect(g, MC.photo.tile, W.half_x, -W.half_x, W.half_x, -W.half_y, W.half_y, vx, vy, 2 * W.half_x * s, 2 * W.half_y * s); else if (MC.layerCanvas) g.drawImage(MC.layerCanvas, vx, vy, 2 * W.half_x * s, 2 * W.half_y * s);
    g.fillStyle = 'rgba(2,4,10,.3)'; g.fillRect(vx, vy, 2 * W.half_x * s, 2 * W.half_y * s); g.strokeStyle = C.line || '#16233f'; g.strokeRect(vx, vy, 2 * W.half_x * s, 2 * W.half_y * s);
    for (const t of W.targets || []) { const [x, y] = Pm(t.x_m, t.y_m); g.strokeStyle = C.orange; g.lineWidth = 1.2; g.beginPath(); g.arc(x, y, 3, 0, 7); g.stroke(); }
    const c = MC.cols, cur = MC.cur; g.strokeStyle = C.blue; g.lineWidth = 2; g.beginPath(); let pen = false; for (let i = 0; i <= cur; i++) { if (!Number.isFinite(c.hd[i])) continue; const [x, y] = Pm(c.x[i], c.y[i]); pen ? g.lineTo(x, y) : g.moveTo(x, y); pen = true; } g.stroke();
    const v = vehicles(); const L = v.lander || landerSite(); if (v.state !== 'In orbit') { const [x, y] = Pm(L.x, L.y); g.fillStyle = v.state === 'Descending' ? C.orange : C.blueL; g.fillRect(x - 3, y - 3, 6, 6); } if (v.rov) { const [x, y] = Pm(v.rov.x, v.rov.y); g.fillStyle = '#fff'; g.beginPath(); g.arc(x, y, 3.5, 0, 7); g.fill(); }
    const iv = MC.imgView; if (iv) { const [a, b] = Pm(iv.cx - iv.w / 2, iv.cy + iv.h / 2), [d, e] = Pm(iv.cx + iv.w / 2, iv.cy - iv.h / 2); g.strokeStyle = C.white; g.lineWidth = 1.5; g.setLineDash([4, 3]); g.strokeRect(Math.max(vx, a), Math.max(vy, b), Math.min(vx + 2 * W.half_x * s, d) - Math.max(vx, a), Math.min(vy + 2 * W.half_y * s, e) - Math.max(vy, b)); g.setLineDash([]); }
    MC.txt(g, 'dashed box = what the big image shows', 8, h - 6, C.text, 'left', 9);
  },
};
P.locate = {
  title: 'Where are they now', src: 'feed + derived', dom: true,
  html() {
    const S = MC.S, W = S.W, f = S.last; if (!W || !f) return '<div class="msg">Waiting…</div>'; const v = vehicles(), L = landerSite(), row = (a, b, cls = '') => `<div class="srow"><span>${a}</span><b class="${cls}">${b}</b></div>`;
    let h = '<div class="sect">Lander</div>' + row('State', v.state);
    if (v.state === 'In orbit') h += row('Height', `${f1(MC.lastFinite('orbAlt'))} km`) + row('Speed', `${f1(MC.lastFinite('orbSpd'), 0)} m/s`) + row('Over', `${f1(MC.lastFinite('lat'))}°, ${f1(MC.lastFinite('lon'))}°`) + row('Lap', `${f1(MC.lastFinite('t') / 7068, 1)}`, 'dim');
    else if (v.state === 'Descending') h += row('Position', `E ${MC.nf('lx', v.lander.x)} N ${MC.nf('ly', v.lander.y)} m`) + row('Altitude', MC.nf('lalt', v.lander.alt, { suf: ' m' })) + row('Fall speed', MC.nf('lvz', Math.abs(MC.lastFinite('vz')), { d: 1, suf: ' m/s' })) + row('Sideways', MC.nf('lvh', MC.lastFinite('vh'), { d: 1, suf: ' m/s' })) + row('Distance to touchdown point', MC.nf('ldt', Math.hypot(v.lander.x - L.x, v.lander.y - L.y), { suf: ' m' }));
    else if (v.state === 'On the surface') h += row('Touchdown point', `E ${L.x.toFixed(0)}  N ${L.y.toFixed(0)} m`) + row('Landed after', `${f1(MC.cols.t[MC.cols.ph.indexOf(3)] ?? NaN, 0)} s`, 'dim');
    h += '<div class="sect">Rover</div>';
    if (!v.rov) h += row('State', 'not deployed yet');
    else { const dx = v.rov.x - L.x, dy = v.rov.y - L.y, brg = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360; let near = null; for (const t of W.targets || []) { const d = Math.hypot(t.x_m - v.rov.x, t.y_m - v.rov.y); if (!near || d < near.d) near = { id: t.id, d }; }
      h += row('Activity', MC.MODES[MC.at('mode')] || '—') + row('Position', `E ${MC.nf('rx', v.rov.x)} N ${MC.nf('ry', v.rov.y)} m`) + row('Heading', MC.nf('rhd', v.rov.hd, { suf: '°' })) + row('Speed', MC.nf('rsp', MC.at('speed'), { d: 2, suf: ' cm/s' })) + row('Driven', MC.nf('rdr', MC.lastFinite('dist'), { suf: ' m' })) + row('From the lander', `${MC.nf('rfl', Math.hypot(dx, dy))} m at ${MC.nf('rbr', brg, { suf: '°' })}`) + row('Nearest ice target', near ? `${near.id} · ${near.d.toFixed(0)} m` : '—'); }
    h += '<div class="sect">Site</div>' + row('Region', esc(W.region)) + row('Centre', `${W.site.lat_deg.toFixed(2)}°, ${W.site.lon_deg.toFixed(1)}°`);
    return h + `<div class="note">Positions are metres east (E) and north (N) of the tile centre. Bearing is clockwise from north.</div>`;
  },
};
P.track = {
  title: 'Rover movement over time', src: 'derived', canvas: true,
  draw(g, w, h) {
    const c = MC.cols, n = MC.n(), L = landerSite(); if (!c.hd.some(Number.isFinite)) return MC.empty(g, w, h, 'Movement appears once the rover rolls out.');
    const away = MC.series((i) => (Number.isFinite(c.hd[i]) ? Math.hypot(c.x[i] - L.x, c.y[i] - L.y) : NaN)), hd = MC.series((i) => c.hd[i]);
    MC.stack(g, w, h, [{ title: 'Distance from lander', unit: 'm', series: [{ arr: away }], fill: true, fmt: (v) => v.toFixed(0) }, { title: 'Distance driven', unit: 'm', series: [{ k: 'dist', color: C.blueL }], fmt: (v) => v.toFixed(0) }, { title: 'Heading (0° = north)', unit: '°', series: [{ arr: hd, color: C.orange }], min: 0, max: 360, fmt: (v) => v.toFixed(0) }, { title: 'Speed', unit: 'cm/s', series: [{ k: 'speed' }], fmt: (v) => v.toFixed(2) }], { focus: 'hd' });
  },
};
// ------------------------------------------------------------------------------------------------ trace stacks
P.traces = {
  title: 'Rover telemetry', src: 'feed', canvas: true,
  draw(g, w, h) {
    const L = lim();
    MC.stack(g, w, h, [
      { title: 'Speed', unit: 'cm/s', series: [{ k: 'speed' }], min: 0, max: L.max_speed_m_s * 100 * 1.1, fmt: (v) => v.toFixed(2) },
      { title: 'Battery', unit: '%', series: [{ k: 'soc', scale: 100 }], min: 0, max: 100, fill: true, hline: 20, fmt: (v) => v.toFixed(0) },
      { title: 'Power', unit: 'W', series: [{ k: 'solar', color: C.blueL, label: 'solar' }, { k: 'load', color: C.orange, label: 'load' }], fmt: (v) => v.toFixed(0) },
      { title: 'Slope', unit: '°', series: [{ k: 'slope' }], min: 0, hline: L.slope_limit_deg },
      { title: 'Ground height', unit: 'm', series: [{ k: 'h' }], fmt: (v) => v.toFixed(0) },
      { title: 'Ice signs · hazard', series: [{ k: 'ice', label: 'ice' }, { k: 'haz', color: C.orange, label: 'hazard' }], min: 0, max: 1, fmt: (v) => v.toFixed(2) },
    ], { focus: 'soc' });
  },
};
P.desctr = {
  title: 'Landing telemetry', src: 'feed', canvas: true,
  draw(g, w, h) {
    const twr = MC.series(MC.derive.twr);
    MC.stack(g, w, h, [
      { title: 'Altitude', unit: 'm', series: [{ k: 'alt' }], fill: true, fmt: (v) => v.toFixed(0) },
      { title: 'Vertical speed', unit: 'm/s', series: [{ k: 'vz', color: C.orange }] },
      { title: 'Sideways speed', unit: 'm/s', series: [{ k: 'vh' }] },
      { title: 'Engine thrust', unit: 'N', series: [{ k: 'thrust', color: C.blueL }], fmt: (v) => v.toFixed(0) },
      { title: 'Fuel', unit: 'kg', series: [{ k: 'fuel' }], fmt: (v) => v.toFixed(0) },
      { title: 'Thrust-to-weight (derived)', series: [{ arr: twr, color: C.orange }], fmt: (v) => v.toFixed(2) },
    ], { focus: 'alt' });
  },
};
P.orbtr = {
  title: 'Orbit telemetry', src: 'feed', canvas: true,
  draw(g, w, h) { MC.stack(g, w, h, [{ title: 'Height above Moon', unit: 'km', series: [{ k: 'orbAlt' }], fill: true }, { title: 'Orbital speed', unit: 'm/s', series: [{ k: 'orbSpd', color: C.blueL }], fmt: (v) => v.toFixed(0) }, { title: 'Latitude', unit: '°', series: [{ k: 'lat', color: C.orange }], min: -90, max: 90 }], { focus: 'orbAlt' }); },
};
P.orbit = {
  title: 'Orbit ground track', src: 'feed', canvas: true,
  draw(g, w, h) {
    const m = { l: 10, r: 10, t: 10, b: 22 }, c = MC.cols, n = MC.n(), cur = MC.cur;
    const X = (lon) => m.l + (((lon + 180) % 360 + 360) % 360) / 360 * (w - m.l - m.r), Y = (lat) => m.t + (90 - lat) / 180 * (h - m.t - m.b);
    g.strokeStyle = C.grid; g.lineWidth = 1; g.beginPath(); for (let i = 0; i <= 4; i++) { const y = m.t + (h - m.t - m.b) * i / 4; g.moveTo(m.l, y); g.lineTo(w - m.r, y); const x = m.l + (w - m.l - m.r) * i / 4; g.moveTo(x, m.t); g.lineTo(x, h - m.b); } g.stroke();
    const seg = (i0, i1, col, wd) => { g.strokeStyle = col; g.lineWidth = wd; g.beginPath(); let pv = null; for (let i = i0; i <= i1; i++) { if (!Number.isFinite(c.lat[i])) continue; const x = X(c.lon[i]), y = Y(c.lat[i]); if (pv === null || Math.abs(x - pv) > 0.25 * (w - m.l - m.r)) g.moveTo(x, y); else g.lineTo(x, y); pv = x; } g.stroke(); };
    if (!MC.has('lat')) return MC.empty(g, w, h, 'No orbit data in this feed.');
    seg(0, n - 1, C.blueD, 1.5); seg(0, cur, C.blue, 2.5);
    const W = MC.S.W; if (W?.site) { const x = X(W.site.lon_deg), y = Y(W.site.lat_deg); g.strokeStyle = C.orange; g.lineWidth = 1.5; g.beginPath(); g.arc(x, y, 6, 0, 7); g.stroke(); MC.txt(g, 'landing site', x + 10, y - 5, C.orange, 'left', 10); }
    const lat = MC.lastFinite('lat'), lon = MC.lastFinite('lon'); if (Number.isFinite(lat)) { g.fillStyle = '#fff'; g.beginPath(); g.arc(X(lon), Y(lat), 4, 0, 7); g.fill(); }
    MC.txt(g, '+90° N', m.l + 2, m.t + 10, C.dim, 'left', 9, true); MC.txt(g, '−90° S', m.l + 2, h - m.b - 3, C.dim, 'left', 9, true); MC.txt(g, 'longitude −180° … +180°', w - m.r, h - 6, C.dim, 'right', 9);
  },
};
// ------------------------------------------------------------------------------------------------ gauges, engines
P.gauges = {
  title: 'Gauges', src: 'feed', canvas: true,
  draw(g, w, h) {
    const L = lim(), ph = phaseNow(), cur = MC.cur; let items;
    const rr = MC.range;
    if (ph >= 3 && MC.has('soc')) items = [['Battery', '%', MC.at('soc') * 100, 0, 100, { warnBelow: 25 }], ['Solar', 'W', MC.at('solar'), 0, L.solar_peak_w], ['Load', 'W', MC.at('load'), 0, L.solar_peak_w, { warnAbove: L.solar_peak_w * 0.9 }], ['Slope', '°', MC.at('slope'), 0, L.slope_limit_deg, { warnAbove: L.slope_limit_deg * 0.8 }], ['Speed', 'cm/s', MC.at('speed'), 0, L.max_speed_m_s * 100, { fmt: (v) => v.toFixed(2) }], ['Hazard', '', MC.at('haz'), 0, 1, { warnAbove: 0.5, fmt: (v) => v.toFixed(2) }]];
    else if (ph === 2 || MC.has('alt')) items = [['Altitude', 'm', MC.lastFinite('alt'), 0, rr('alt')[1] || 1], ['Fall speed', 'm/s', Math.abs(MC.lastFinite('vz')), 0, Math.abs(rr('vz')[0]) || 1, { warnAbove: 1.5 }], ['Fuel', 'kg', MC.lastFinite('fuel'), 0, rr('fuel')[1] || 1, { warnBelow: 5 }], ['Thrust', 'N', MC.lastFinite('thrust'), 0, rr('thrust')[1] || 1], ['Engines', 'of 5', MC.lastFinite('eng'), 0, 5, { warnBelow: 5 }], ['Thrust/weight', '', MC.derive.twr(MC.cur), 0, 4, { fmt: (v) => v.toFixed(2) }]];
    else items = [['Height', 'km', MC.lastFinite('orbAlt'), 0, 100, { fmt: (v) => v.toFixed(1) }], ['Speed', 'm/s', MC.lastFinite('orbSpd'), 0, 1800], ['Latitude', '°', MC.lastFinite('lat'), -90, 90], ['Longitude', '°', MC.lastFinite('lon'), -180, 180]];
    if (cur < 0) return MC.empty(g, w, h, 'Waiting for data…');
    let cols = 1, best = 0; for (let k = 1; k <= items.length; k++) { const rr2 = Math.min(w / k, h / Math.ceil(items.length / k)); if (rr2 > best) { best = rr2; cols = k; } }
    const rows = Math.ceil(items.length / cols), cw = w / cols, ch = h / rows, r = Math.min(cw * 0.3, ch * 0.3);
    items.forEach((it, i) => { const o = it[5] || {}; MC.gauge(g, (i % cols + 0.5) * cw, Math.floor(i / cols) * ch + ch * 0.5, r, it[2], { label: it[0], unit: it[1], min: it[3], max: it[4], ...o }); });
  },
};
P.engines = {
  title: 'Engines', src: 'feed + simulated temps', canvas: true,
  draw(g, w, h) {
    const eng = MC.lastFinite('eng'), th = MC.lastFinite('thrust'); if (!Number.isFinite(eng)) return MC.empty(g, w, h, 'Engines appear during the landing.');
    const per = th / Math.max(eng, 1), n = 5, bw = (w - 40) / n, top = 54, base = h - 44;
    MC.txt(g, 'Total thrust', 12, 18, C.dim, 'left', 10); MC.txt(g, `${f1(th, 0)} N`, 12, 40, C.white, 'left', 22, true);
    MC.txt(g, 'Thrust / weight', w * 0.42, 18, C.dim, 'left', 10); MC.txt(g, f1(MC.derive.twr(MC.cur), 2), w * 0.42, 40, C.white, 'left', 22, true);
    MC.txt(g, 'Fuel burn', w * 0.7, 18, C.dim, 'left', 10); MC.txt(g, `${f1(MC.derive.burn(MC.cur), 2)} kg/s`, w * 0.7, 40, C.white, 'left', 22, true);
    for (let i = 0; i < n; i++) {
      const off = eng < 5 && [1, 3].includes(i), thr = off ? 0 : MC.clamp(per / 800, 0, 1), x = 20 + i * bw + bw * 0.15, ww = bw * 0.7;
      g.fillStyle = C.blueDD; g.fillRect(x, top, ww, base - top); g.fillStyle = off ? C.orangeD : C.blue; g.fillRect(x, base - (base - top) * (off ? 0.03 : thr), ww, (base - top) * (off ? 0.03 : thr));
      MC.txt(g, off ? 'OFF' : `${(thr * 100).toFixed(0)} %`, x + ww / 2, base + 14, off ? C.orange : C.white, 'center', 11, true);
      MC.txt(g, `E${i + 1}${off ? '' : ' · ' + (280 + thr * 340).toFixed(0) + ' °C'}`, x + ww / 2, base + 28, off ? C.orange : C.dim, 'center', 9, true);
    }
  },
};
// ------------------------------------------------------------------------------------------------ tables (DOM)
P.targets = {
  title: 'Ice target board', src: 'derived', dom: true,
  html() {
    const S = MC.S, W = S.W, f = S.last; if (!W || !f) return '<div class="msg">Waiting for targets…</div>';
    const { x, y } = roverPos(), px = Number.isFinite(x) ? x : W.start.x_m, py = Number.isFinite(y) ? y : W.start.y_m, used = MC.lastFinite('used'), dist = MC.lastFinite('dist');
    const k = Number.isFinite(used) && dist > 50 ? MC.clamp(used / dist, 0.1, 3) : 0.35, usable = Math.max(0, (MC.lastFinite('wh') || 0) - 0.2 * lim().battery_capacity_wh);
    const rows = (W.targets || []).map((t) => { const st = f.targets?.find((q) => q.id === t.id), d = Math.hypot(t.x_m - px, t.y_m - py), rt = 2 * d * k; return { t, d, rt, margin: usable - rt, state: st?.sampled ? 'sampled' : f.drill_target === t.id ? 'drilling' : 'open' }; });
    rows.sort((a, b) => b.t.ice_score - a.t.ice_score || a.d - b.d); const near = Math.min(...rows.map((r) => r.d)), top = Math.max(...rows.map((r) => r.t.ice_score));
    return `<table class="tbl"><tr><th>P</th><th>Target</th><th>Ice</th><th>Dist m</th><th>Trip Wh</th><th>Margin Wh</th><th>Depth m</th><th>State</th></tr>`
      + rows.map((r, i) => `<tr><td class="dim">${i + 1}</td><td><b>${esc(r.t.id)}</b></td><td class="${r.t.ice_score === top ? 'hi' : ''}">${r.t.ice_score.toFixed(2)}</td><td class="${r.d === near ? 'best' : ''}">${MC.nf('d-' + r.t.id, r.d)}</td><td>${MC.nf('r-' + r.t.id, r.rt)}</td><td class="${r.margin < 0 ? 'bad' : 'ok'}">${MC.nf('m-' + r.t.id, r.margin, { sign: true })}</td><td>${MC.nf('p-' + r.t.id, r.t.depth_m ?? 0)}</td><td class="st-${r.state}">${r.state}</td></tr>`).join('')
      + `</table><div class="note">Round trip = 2 × distance × ${k.toFixed(2)} Wh/m (estimated from energy used so far). Margin = battery above the 20 % floor minus round trip.</div>`;
  },
};
P.status = {
  title: 'Subsystem status', src: 'derived', dom: true,
  html() {
    const S = MC.S, f = S.last, L = lim(); if (!f) return '<div class="msg">Waiting…</div>'; const ph = phaseNow(), rov = Number.isFinite(MC.at('soc')), eng = MC.lastFinite('eng'), models = S.models || [];
    const led = (cls, name, val) => `<div class="srow"><i class="led ${cls}"></i><span>${name}</span><b>${val}</b></div>`;
    const tb = MC.sim.temp.battery[MC.cur];
    const m = (id) => models.find((x) => x.id === id);
    return [
      led(Number.isFinite(eng) ? (eng < 5 ? 'warn' : 'ok') : 'off', 'Lander engines', Number.isFinite(eng) ? `${eng} of 5` : 'n/a'),
      led(rov ? 'ok' : 'off', 'Rover', rov ? (MC.MODES[MC.at('mode')] || '—') : 'not deployed'),
      led(rov ? (MC.at('soc') < 0.25 ? 'warn' : 'ok') : 'off', 'Battery', rov ? `${f1(MC.at('soc') * 100, 0)} %` : 'n/a'),
      led(rov ? (MC.at('solar') > 0 ? 'ok' : 'warn') : 'off', 'Solar input', rov ? `${f1(MC.at('solar'), 0)} W` : 'n/a'),
      led(rov ? (MC.at('earth') === 1 ? 'ok' : 'warn') : 'off', 'Link to Earth', rov ? (MC.at('earth') === 1 ? 'up' : 'down') : 'n/a'),
      led(rov ? (MC.at('slope') > L.slope_limit_deg ? 'warn' : 'ok') : 'off', 'Mobility', rov ? `slope ${f1(MC.at('slope'))}°` : 'n/a'),
      led(Number.isFinite(tb) ? (tb < -5 ? 'warn' : 'ok') : 'off', 'Thermal (sim.)', Number.isFinite(tb) ? `${f1(tb, 0)} °C` : 'n/a'),
      led(rov ? (MC.at('drill') > 0 ? 'ok' : 'idle') : 'off', 'Drill', rov ? (MC.at('drill') > 0 ? `${f1(MC.at('drill'), 0)} s left` : 'idle') : 'n/a'),
      led(m('hazard')?.status === 'attached' ? 'ok' : 'idle', 'Hazard detector', esc(m('hazard')?.status || '—')),
      led(m('rover')?.status === 'attached' ? 'ok' : 'idle', 'Rover brain', esc(m('rover')?.status || '—')),
      led(m('light')?.status === 'attached' ? 'ok' : 'idle', 'Light model', esc(m('light')?.status || '—')),
      led(f.aborted ? 'warn' : 'ok', 'Safe mode', f.aborted ? 'LATCHED' : 'off'),
    ].join('');
  },
};
P.log = {
  title: 'Race control messages', src: 'feed', dom: true,
  html() {
    const L = MC.S.logs.slice(0, 60); if (!L.length) return '<div class="msg">No messages yet.</div>'; const seen = (MC.logSeen = MC.logSeen || new Map()), now = performance.now();
    return '<table class="tbl log">' + L.map((e) => { const k = `${e.t_s}|${e.kind}|${e.msg}`; if (!seen.has(k)) seen.set(k, now); return `<tr class="${['abort', 'dead'].includes(e.kind) ? 'bad' : e.kind === 'agent' ? 'ai' : ''} ${now - seen.get(k) < 900 ? 'enter' : ''}"><td class="dim">${MC.fmtHMS(e.t_s)}</td><td class="k">${esc(String(e.kind).replace(/_/g, ' '))}</td><td>${esc(e.msg)}</td></tr>`; }).join('') + '</table>';
  },
};
P.stats = {
  title: 'Run statistics', src: 'derived', dom: true,
  html() {
    const c = MC.cols, n = MC.n(), cur = MC.cur; if (cur < 0) return '<div class="msg">Waiting…</div>';
    const count = (k, v, to = cur) => { let s = 0; for (let i = 0; i <= to; i++) if (c[k][i] === v) s++; return s; }, rov = c.hd.some(Number.isFinite);
    const share = (k) => { let a = 0, b = 0; for (let i = 0; i <= cur; i++) if (Number.isFinite(c[k][i])) { b++; if (c[k][i] === 1) a++; } return b ? 100 * a / b : NaN; };
    let minSoc = Infinity, maxSlope = 0, maxSpd = 0; for (let i = 0; i <= cur; i++) { if (c.soc[i] < minSoc) minSoc = c.soc[i]; if (c.slope[i] > maxSlope) maxSlope = c.slope[i]; if (c.speed[i] > maxSpd) maxSpd = c.speed[i]; }
    const sampled = (MC.S.last?.targets || []).filter((t) => t.sampled).length, failures = MC.events.filter((e) => /fail/i.test(e.msg) && e.t_s <= c.t[cur]).length;
    const cell = (a, b, cl = '') => `<div class="sc"><small>${a}</small><b class="${cl}">${b}</b></div>`;
    const N = MC.nf; return '<div class="sgrid">' + cell('Distance driven', N('dist', MC.lastFinite('dist'), { suf: ' m' })) + cell('Energy used', N('used', MC.lastFinite('used'), { suf: ' Wh' })) + cell('Samples taken', N('samp', sampled)) + cell('Lowest battery', Number.isFinite(minSoc) && minSoc !== Infinity ? N('minsoc', minSoc * 100, { suf: ' %' }) : '—', minSoc < 0.25 ? 'bad' : '')
      + cell('Steepest slope', rov ? N('maxslope', maxSlope, { d: 1, suf: '°' }) : '—') + cell('Top speed', rov ? N('maxspd', maxSpd, { d: 2, suf: ' cm/s' }) : '—') + cell('Time in sunlight', N('shlit', share('lit'), { suf: ' %' })) + cell('Time linked to Earth', N('shearth', share('earth'), { suf: ' %' }))
      + cell('Time drilling', N('cdrill', count('mode', 3), { suf: ' steps' })) + cell('Time asleep', N('csleep', count('mode', 2), { suf: ' steps' })) + cell('Failures logged', N('fails', failures), failures ? 'bad' : '') + cell('Frames seen', `${N('frames', cur + 1)} of ${n}`) + '</div>';
  },
};
P.wheels = {
  title: 'Wheel motors', src: 'simulated', dom: true,
  html() {
    if (!Number.isFinite(MC.at('speed'))) return '<div class="msg">The rover has not rolled out yet.</div>';
    return '<div class="wgrid">' + MC.WHEELS.map((nm, i) => { const w = MC.wheel(i); return `<div class="wc"><small>${nm}</small><b>${MC.nf('t' + i, w.temp, { suf: ' °C' })}</b><div class="mini"><i style="width:${MC.clamp((w.temp + 60) / 120, 0, 1) * 100}%"></i></div><span>${MC.nf('a' + i, w.amps, { d: 2, suf: ' A' })}</span><span>wear ${MC.nf('w' + i, w.wear, { d: 1, suf: ' %' })}</span></div>`; }).join('') + '</div>';
  },
};
P.env = {
  title: 'Environment', src: 'derived + simulated', dom: true,
  html() {
    const cur = MC.cur; if (cur < 0) return '<div class="msg">Waiting…</div>'; const psr = MC.at('psr'), lit = MC.at('lit'), amb = psr === 1 ? -170 : lit === 1 ? -35 : Number.isNaN(lit) ? -60 : -150;
    const row = (a, b, c = '') => `<div class="srow"><span>${a}</span><b>${b}</b><em>${c}</em></div>`;
    return row('Sun height', MC.nf('sun', MC.lastFinite('sunEl'), { d: 1, suf: '°' }), 'feed') + row('Earth height', MC.nf('earth', MC.lastFinite('earthEl'), { d: 1, suf: '°' }), 'feed') + row('Surface temperature', MC.nf('amb', amb, { suf: ' °C' }), 'simulated') + row('Radiation dose rate', MC.nf('rad', 0.8 + 0.2 * Math.sin(MC.at('t') / 3000), { d: 2, suf: ' µSv/h' }), 'simulated')
      + row('Local gravity', `${MC.GRAVITY_MOON} m/s²`, 'constant') + row('Earth–Moon distance', `${MC.EARTH_MOON_KM.toLocaleString()} km`, 'mean') + row('One-way light time', `${MC.LIGHT_TIME_S} s`, 'constant');
  },
};
P.ai = {
  title: 'AI stack', src: 'feed', dom: true,
  html() {
    const M = MC.S.models || []; return '<table class="tbl"><tr><th>Model</th><th>Type</th><th>Job</th><th>Owner</th><th>Status</th></tr>' + M.map((m) => `<tr><td><b>${esc(m.name)}</b></td><td>${esc(m.kind)}${m.params ? ' · ' + (m.params >= 1e6 ? (m.params / 1e6).toFixed(1) + 'M' : Math.round(m.params / 1e3) + 'k') : ''}</td><td>${esc(m.role)}</td><td>${esc(m.owner || '—')}</td><td class="st-${m.status === 'attached' ? 'sampled' : m.status === 'fallback' ? 'drilling' : 'open'}">${esc(m.status)}${m.fallback && m.status === 'fallback' ? ' → ' + esc(m.fallback) : ''}</td></tr>`).join('') + '</table>';
  },
};
P.prov = {
  title: 'Data provenance', src: 'feed', dom: true,
  html() {
    const pv = MC.S.W?.provenance || {}, names = { terrain: 'Terrain', psr: 'Dark craters', ice_evidence: 'Ice signs', illumination: 'Sunlight', earth_link: 'Earth link', rover: 'Rover' };
    const rows = Object.keys(names).filter((k) => pv[k]).map((k) => { const t = String(pv[k]), real = /observed/i.test(t); return `<tr><td><b>${names[k]}</b></td><td class="${real ? 'ok' : 'bad'}">${/generated/i.test(t) ? 'GENERATED' : real ? 'OBSERVED' : 'MODELLED'}${/assumed/i.test(t) ? ' · ASSUMED' : ''}</td><td class="dim">${esc(t)}</td></tr>`; });
    return '<table class="tbl">' + rows.join('') + '</table><div class="note">Panels tagged “simulated” run a simple physical model driven by the feed. They are not measurements.</div>';
  },
};
// ------------------------------------------------------------------------------------------------ gantt + run heat grid
const SEG = (g, x0, x1, y, h, col) => { g.fillStyle = col; g.fillRect(x0, y, Math.max(1, x1 - x0), h); };
P.gantt = {
  title: 'Mission timeline', src: 'feed', canvas: true,
  draw(g, w, h) {
    const c = MC.cols, n = MC.n(); if (n < 2) return MC.empty(g, w, h, 'Waiting for data…');
    const LM = 78, pw = w - LM - 8, t0 = c.t[0], t1 = c.t[n - 1], X = (t) => LM + (t - t0) / ((t1 - t0) || 1) * pw;
    const rows = [['Phase', (i) => ['#14357a', '#1b4aa6', '#2f7dff', '#5c9bff', '#8db9ff'][c.ph[i]]], ['Sunlight', (i) => (c.lit[i] === 1 ? C.blueL : c.lit[i] === 0 ? C.blueDD : null)], ['Earth link', (i) => (c.earth[i] === 1 ? C.blue : c.earth[i] === 0 ? C.blueDD : null)], ['Dark crater', (i) => (c.psr[i] === 1 ? C.blue : c.psr[i] === 0 ? C.blueDD : null)], ['Activity', (i) => [C.blue, C.blueD, '#1b2a4a', C.blueL][c.mode[i]] || null]];
    const rh = (h - 22) / (rows.length + 1);
    rows.forEach(([lab, col], r) => { const y = 4 + r * rh; MC.txt(g, lab, 6, y + rh * 0.62, C.dim, 'left', 10); for (let i = 0; i < n; i++) { const cc = col(i); if (cc) SEG(g, X(c.t[i]), X(i + 1 < n ? c.t[i + 1] : c.t[i]) + 0.5, y + 2, rh - 5, cc); } });
    const ey = 4 + rows.length * rh; MC.txt(g, 'Events', 6, ey + rh * 0.62, C.dim, 'left', 10); for (const e of MC.events) { const bad = /fail|abort|dead|rejected/i.test(e.kind + e.msg); g.fillStyle = bad ? C.orange : C.blueL; g.fillRect(X(e.t_s) - 0.5, ey + 3, 1.5, rh - 6); }
    for (let k = 0; k <= 6; k++) { const tt = t0 + (t1 - t0) * k / 6; MC.txt(g, MC.fmtT(tt), X(tt), h - 4, C.dim, k === 0 ? 'left' : k === 6 ? 'right' : 'center', 9, true); }
    if (MC.cur >= 0) { const cx = X(c.t[MC.cur]); g.strokeStyle = C.white; g.globalAlpha = 0.6; g.beginPath(); g.moveTo(cx, 2); g.lineTo(cx, h - 16); g.stroke(); g.globalAlpha = 1; }
  },
};
P.runtl = {
  title: 'Run timeline · average per time slice', src: 'feed', canvas: true,
  draw(g, w, h) {
    const c = MC.cols, n = MC.n(), L = lim(), ph = phaseNow(); if (n < 2) return MC.empty(g, w, h, 'Waiting for data…');
    const rover = ph >= 3 && MC.has('soc'), lander = !rover && MC.has('alt');
    const rows = rover ? [['Battery %', c.soc.map((v) => v * 100), 0, 100, { bad: (v) => v < 25 }], ['Solar W', c.solar, 0, L.solar_peak_w], ['Load W', c.load, 0, L.solar_peak_w], ['Slope °', c.slope, 0, L.slope_limit_deg, { bad: (v) => v > L.slope_limit_deg }], ['Hazard', c.haz, 0, 1, { bad: (v) => v > 0.5, d: 2 }], ['Speed cm/s', c.speed, 0, L.max_speed_m_s * 100, { d: 2 }], ['Ice signs', c.ice, 0, 1, { d: 2 }], ['Sun °', c.sunEl, 0, 6, { d: 1 }]]
      : lander ? [['Altitude m', c.alt, 0, MC.range('alt')[1]], ['Vert. m/s', c.vz.map(Math.abs), 0, Math.abs(MC.range('vz')[0]) || 1], ['Side m/s', c.vh, 0, MC.range('vh')[1] || 1, { d: 1 }], ['Thrust N', c.thrust, 0, MC.range('thrust')[1] || 1], ['Fuel kg', c.fuel, 0, MC.range('fuel')[1] || 1], ['Engines', c.eng, 0, 5, { bad: (v) => v < 5, d: 1 }], ['Mass kg', c.mass, 0, MC.range('mass')[1] || 1]]
        : [['Height km', c.orbAlt, 0, 100, { d: 1 }], ['Speed m/s', c.orbSpd, 0, 1800], ['Latitude °', c.lat, -90, 90], ['Longitude °', c.lon, -180, 180]];
    let a = n, b = 0; rows.forEach((r) => { for (let i = 0; i < n; i++) if (Number.isFinite(r[1][i])) { a = Math.min(a, i); b = Math.max(b, i); } }); if (b <= a) return MC.empty(g, w, h, 'No data for this phase yet.');
    const NB = Math.max(8, Math.min(24, Math.floor((w - 80) / 46))), LM = 74, cw = (w - LM - 6) / NB, rh = (h - 18) / rows.length, ta = c.t[a], tb = c.t[b];
    rows.forEach((r, ri) => {
      MC.txt(g, r[0], 6, ri * rh + rh * 0.62, C.dim, 'left', 10);
      for (let k = 0; k < NB; k++) {
        const s = ta + (tb - ta) * k / NB, e = ta + (tb - ta) * (k + 1) / NB; let sum = 0, cnt = 0; for (let i = a; i <= b; i++) if (c.t[i] >= s && (c.t[i] < e || (k === NB - 1 && c.t[i] <= e)) && Number.isFinite(r[1][i])) { sum += r[1][i]; cnt++; }
        const x = LM + k * cw, y = ri * rh; if (!cnt) { g.fillStyle = '#080d18'; g.fillRect(x + 1, y + 1, cw - 2, rh - 2); continue; }
        const v = sum / cnt, bad = r[4]?.bad?.(v), f = MC.clamp((v - r[2]) / ((r[3] - r[2]) || 1), 0, 1);
        g.fillStyle = bad ? C.orangeD : MC.heat(0.1 + 0.8 * f); g.fillRect(x + 1, y + 1, cw - 2, rh - 2);
        MC.txt(g, v.toFixed(r[4]?.d ?? 0), x + cw / 2, y + rh * 0.66, bad ? C.orange : f > 0.55 ? '#02040a' : C.text, 'center', 10, true);
      }
    });
    if (MC.cur >= a && MC.cur <= b) { const k = Math.min(NB - 1, Math.floor((c.t[MC.cur] - ta) / ((tb - ta) || 1) * NB)); g.strokeStyle = C.white; g.lineWidth = 1.5; g.strokeRect(LM + k * cw + 0.5, 0.5, cw - 1, rows.length * rh - 1); }
    for (let k = 0; k <= NB; k += Math.ceil(NB / 6)) MC.txt(g, MC.fmtT(ta + (tb - ta) * k / NB), LM + k * cw, h - 4, C.dim, 'left', 9, true);
  },
};
// ------------------------------------------------------------------------------------------------ terrain-derived
P.vision = {
  title: 'Rover vision · terrain around the rover', src: 'derived', canvas: true,
  draw(g, w, h) {
    const W = MC.S.W, { x, y } = roverPos(); if (!W || !Number.isFinite(x) || !Number.isFinite(MC.at('hd'))) return MC.empty(g, w, h, 'The rover has not rolled out yet.');
    const R = 20, cell = Math.min(w, h - 22) / (2 * R + 1), ox = (w - cell * (2 * R + 1)) / 2, oy = 4, hd = MC.at('hd') * Math.PI / 180, L = lim(); let nearest = Infinity;
    const c0 = Math.floor((x + W.half_x) / W.mpp), r0 = Math.floor((W.half_y - y) / W.mpp);
    for (let dr = -R; dr <= R; dr++) for (let dc = -R; dc <= R; dc++) {
      const r = r0 + dr, c = c0 + dc, px = ox + (dc + R) * cell, py = oy + (dr + R) * cell; if (r < 0 || c < 0 || r >= W.rows || c >= W.cols) { g.fillStyle = '#04070d'; g.fillRect(px, py, cell, cell); continue; }
      const i = r * W.cols + c, hz = W.hazard[i] / 255, sl = W.slope[i] / L.slope_limit_deg; g.fillStyle = hz > 0.5 || sl > 1 ? C.orangeD : MC.heat(0.15 + 0.6 * MC.clamp(sl, 0, 1)); g.fillRect(px, py, cell - 0.5, cell - 0.5);
      if (hz > 0.5 || sl > 1) nearest = Math.min(nearest, Math.hypot(dr, dc) * W.mpp);
    }
    const cx = ox + (R + 0.5) * cell, cy = oy + (R + 0.5) * cell; g.strokeStyle = C.blueL; g.lineWidth = 1; g.setLineDash([3, 3]); for (const m of [50, 100]) { g.beginPath(); g.arc(cx, cy, m / W.mpp * cell, 0, 7); g.stroke(); } g.setLineDash([]);
    g.save(); g.translate(cx, cy); g.rotate(hd); g.fillStyle = '#fff'; g.beginPath(); g.moveTo(0, -9); g.lineTo(6, 7); g.lineTo(-6, 7); g.closePath(); g.fill(); g.restore();
    MC.txt(g, Number.isFinite(nearest) ? `nearest danger cell ${nearest.toFixed(0)} m` : 'no danger cells within 100 m', 8, h - 6, Number.isFinite(nearest) ? C.orange : C.dim, 'left', 10); MC.txt(g, 'rings: 50 m, 100 m · orange: over slope limit or hazard', w - 8, h - 6, C.dim, 'right', 9);
  },
};
P.profile = {
  title: 'Elevation profile along the route', src: 'derived', canvas: true,
  draw(g, w, h) {
    const W = MC.S.W, c = MC.cols, n = MC.n(); if (!W) return MC.empty(g, w, h, 'Waiting…'); const pts = []; let d = 0, px = null, py = null;
    for (let i = 0; i < n; i++) { if (!Number.isFinite(c.hd[i])) continue; if (px !== null) d += Math.hypot(c.x[i] - px, c.y[i] - py); px = c.x[i]; py = c.y[i]; const col = Math.floor((c.x[i] + W.half_x) / W.mpp), row = Math.floor((W.half_y - c.y[i]) / W.mpp); if (col < 0 || row < 0 || col >= W.cols || row >= W.rows) continue; pts.push({ d, z: W.height[row * W.cols + col], lit: c.lit[i], i }); }
    if (pts.length < 2) return MC.empty(g, w, h, 'The route appears once the rover moves.');
    const LM = 44, pw = w - LM - 8, top = 14, ph = h - 34, zs = pts.map((q) => q.z), lo = Math.min(...zs) - 2, hi = Math.max(...zs) + 2, dmax = pts[pts.length - 1].d || 1, X = (v) => LM + v / dmax * pw, Y = (z) => top + (1 - (z - lo) / (hi - lo)) * ph;
    g.strokeStyle = C.grid; g.beginPath(); for (let k = 0; k <= 3; k++) { g.moveTo(LM, top + ph * k / 3); g.lineTo(LM + pw, top + ph * k / 3); } g.stroke();
    const draw = (to, alpha) => { g.globalAlpha = alpha; g.beginPath(); pts.forEach((q, k) => { if (q.i > to) return; k ? g.lineTo(X(q.d), Y(q.z)) : g.moveTo(X(q.d), Y(q.z)); }); g.strokeStyle = C.blue; g.lineWidth = 2; g.stroke(); g.globalAlpha = 1; };
    draw(n, 0.25); const last = pts.filter((q) => q.i <= MC.cur).pop(); g.beginPath(); pts.forEach((q, k) => { if (q.i > MC.cur) return; k ? g.lineTo(X(q.d), Y(q.z)) : g.moveTo(X(q.d), Y(q.z)); }); g.lineTo(X(last?.d ?? 0), top + ph); g.lineTo(X(0), top + ph); g.fillStyle = 'rgba(47,125,255,.16)'; g.fill(); draw(MC.cur, 1);
    for (const q of pts) if (q.lit === 1 && q.i <= MC.cur) { g.fillStyle = C.orange; g.fillRect(X(q.d) - 1, top + ph + 4, 2, 5); }
    if (last) { g.fillStyle = '#fff'; g.beginPath(); g.arc(X(last.d), Y(last.z), 4, 0, 7); g.fill(); }
    MC.txt(g, `${hi.toFixed(0)} m`, LM - 4, top + 8, C.dim, 'right', 9, true); MC.txt(g, `${lo.toFixed(0)} m`, LM - 4, top + ph, C.dim, 'right', 9, true); MC.txt(g, `0 – ${dmax.toFixed(0)} m driven · orange ticks = in sunlight`, LM, h - 4, C.dim, 'left', 9);
  },
};
let histCache = null;
P.hist = {
  title: 'Terrain statistics (whole map)', src: 'derived', canvas: true,
  draw(g, w, h) {
    const W = MC.S.W; if (!W) return MC.empty(g, w, h, 'Waiting…');
    if (!histCache || histCache.W !== W) { const mk = (nb) => new Array(nb).fill(0), sl = mk(15), ic = mk(20), hz = mk(10); for (let i = 0; i < W.slope.length; i++) { sl[Math.min(14, Math.floor(W.slope[i] / 2))]++; ic[Math.min(19, Math.floor(W.ice[i] / 255 * 20))]++; hz[Math.min(9, Math.floor(W.hazard[i] / 255 * 10))]++; } histCache = { W, sl, ic, hz }; }
    const L = lim(), defs = [['Slope °', histCache.sl, 30, MC.at('slope'), L.slope_limit_deg], ['Ice signs', histCache.ic, 1, MC.at('ice'), null], ['Hazard', histCache.hz, 1, MC.at('haz'), 0.5]], cw = w / 3;
    defs.forEach(([name, bins, maxV, cur, limit], k) => {
      const x0 = k * cw + 10, bw = (cw - 20) / bins.length, top = 20, ph = h - 40, mx = Math.max(...bins) || 1; MC.txt(g, name, x0, 12, C.dim, 'left', 10);
      bins.forEach((v, i) => { const hh = Math.sqrt(v / mx) * ph; g.fillStyle = limit != null && (i + 0.5) / bins.length * maxV > limit ? C.orangeD : C.blueD; g.fillRect(x0 + i * bw, top + ph - hh, bw - 1, hh); });
      if (Number.isFinite(cur)) { const x = x0 + MC.clamp(cur / maxV, 0, 1) * bw * bins.length; g.strokeStyle = C.white; g.lineWidth = 1.5; g.beginPath(); g.moveTo(x, top); g.lineTo(x, top + ph); g.stroke(); MC.txt(g, `now ${cur.toFixed(maxV > 5 ? 1 : 2)}`, x + 3, top + 8, C.white, 'left', 9, true); }
      MC.txt(g, '0', x0, h - 6, C.dim, 'left', 9, true); MC.txt(g, String(maxV), x0 + bw * bins.length, h - 6, C.dim, 'right', 9, true);
    });
  },
};
P.scatter = {
  title: 'Targets · ice score vs distance', src: 'derived', canvas: true,
  draw(g, w, h) {
    const S = MC.S, W = S.W, f = S.last; if (!W || !f) return MC.empty(g, w, h, 'Waiting…'); const { x, y } = roverPos(), px = Number.isFinite(x) ? x : W.start.x_m, py = Number.isFinite(y) ? y : W.start.y_m;
    const T = (W.targets || []).map((t) => ({ t, d: Math.hypot(t.x_m - px, t.y_m - py), st: f.targets?.find((q) => q.id === t.id)?.sampled })); if (!T.length) return MC.empty(g, w, h, 'No targets.');
    const ds = T.map((q) => q.d), is = T.map((q) => q.t.ice_score), dMax = Math.max(...ds) * 1.1, iLo = Math.min(...is) - 0.01, iHi = Math.max(...is) + 0.01, m = { l: 44, r: 14, t: 14, b: 26 };
    const X = (d) => m.l + d / dMax * (w - m.l - m.r), Y = (v) => m.t + (1 - (v - iLo) / (iHi - iLo)) * (h - m.t - m.b);
    g.strokeStyle = C.grid; g.beginPath(); for (let k = 0; k <= 3; k++) { g.moveTo(m.l, m.t + (h - m.t - m.b) * k / 3); g.lineTo(w - m.r, m.t + (h - m.t - m.b) * k / 3); } g.stroke();
    for (const q of T) { const cx = X(q.d), cy = Y(q.t.ice_score), r = 3 + (q.t.depth_m ?? 40) / 20; g.fillStyle = q.st ? C.blue : C.orange; g.globalAlpha = 0.7; g.beginPath(); g.arc(cx, cy, r, 0, 7); g.fill(); g.globalAlpha = 1; MC.txt(g, q.t.id, cx + r + 3, cy + 3, C.text, 'left', 10); }
    MC.txt(g, iHi.toFixed(2), m.l - 4, m.t + 8, C.dim, 'right', 9, true); MC.txt(g, iLo.toFixed(2), m.l - 4, h - m.b, C.dim, 'right', 9, true); MC.txt(g, `distance from rover 0 – ${dMax.toFixed(0)} m · bubble size = depth`, m.l, h - 6, C.dim, 'left', 9);
  },
};
// ------------------------------------------------------------------------------------------------ power, thermal, comms, sky
P.flow = {
  title: 'Power flow', src: 'feed + simulated split', canvas: true,
  draw(g, w, h) {
    const solar = MC.at('solar'), load = MC.at('load'), soc = MC.at('soc'); if (!Number.isFinite(solar)) return MC.empty(g, w, h, 'Rover power appears after landing.');
    const L = lim(), net = solar - load, mode = MC.MODES[MC.at('mode')] || 'hold', split = MC.SPLIT[mode], cat = Object.keys(split);
    const box = (x, y, bw, bh, t, v, col = C.blue) => { g.fillStyle = C.blueDD; g.fillRect(x, y, bw, bh); g.strokeStyle = col; g.lineWidth = 1.5; g.strokeRect(x, y, bw, bh); MC.txt(g, t, x + bw / 2, y + 15, C.dim, 'center', 10); MC.txt(g, v, x + bw / 2, y + bh - 10, C.white, 'center', 13, true); };
    const line = (x0, y0, x1, y1, wv, col) => { g.strokeStyle = col; g.lineWidth = MC.clamp(1 + wv / 6, 1, 9); g.globalAlpha = wv > 0.5 ? 0.9 : 0.25; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke(); g.globalAlpha = 1; };
    const bw = Math.min(110, w * 0.2), bh = 46, y0 = h / 2 - bh / 2, xs = 10, xb = w * 0.38, xl = w - bw - 10;
    box(xs, y0, bw, bh, 'SOLAR PANEL', `${f1(solar, 0)} W`); box(xb, y0, bw, bh, 'BATTERY', `${f1(soc * 100, 0)} %`, net < 0 ? C.orange : C.blue);
    line(xs + bw, h / 2, xb, h / 2, Math.abs(net), net < 0 ? C.orange : C.blueL); MC.txt(g, `${net >= 0 ? '+' : '−'}${Math.abs(net).toFixed(0)} W ${net >= 0 ? 'charging' : 'draining'}`, (xs + bw + xb) / 2, h / 2 - 10, net < 0 ? C.orange : C.blueL, 'center', 10, true);
    const lh = (h - 16) / cat.length; cat.forEach((nm, i) => { const wv = load * split[nm], y = 8 + i * lh + lh / 2; line(xb + bw, h / 2, xl, y, wv, C.blue); g.fillStyle = C.blueDD; g.fillRect(xl, y - 13, bw, 26); g.strokeStyle = C.blueD; g.lineWidth = 1; g.strokeRect(xl, y - 13, bw, 26); MC.txt(g, nm.toUpperCase(), xl + 8, y + 4, C.dim, 'left', 10); MC.txt(g, `${wv.toFixed(1)} W`, xl + bw - 8, y + 5, C.white, 'right', 12, true); });
    MC.txt(g, `Mode: ${mode} · total load ${f1(load, 0)} W · solar peak ${L.solar_peak_w} W · split by mode is simulated`, 10, h - 6, C.dim, 'left', 9);
  },
};
P.budget = {
  title: 'Energy budget', src: 'derived', canvas: true,
  draw(g, w, h) {
    const c = MC.cols, n = MC.n(), ein = new Array(n).fill(NaN), eout = new Array(n).fill(NaN); let a = 0, b = 0;
    for (let i = 0; i < n; i++) { if (!Number.isFinite(c.solar[i])) continue; const dt = i ? Math.max(0, c.t[i] - c.t[i - 1]) : 0; a += c.solar[i] * dt / 3600; b += c.load[i] * dt / 3600; ein[i] = a; eout[i] = b; }
    MC.stack(g, w, h, [{ title: 'Solar vs load', unit: 'W', series: [{ k: 'solar', color: C.blueL, label: 'solar' }, { k: 'load', color: C.orange, label: 'load' }], fmt: (v) => v.toFixed(0) }, { title: 'Energy in vs out (cumulative)', unit: 'Wh', series: [{ arr: ein, color: C.blueL, label: 'in' }, { arr: eout, color: C.orange, label: 'out' }], fmt: (v) => v.toFixed(0) }, { title: 'Battery', unit: '%', series: [{ k: 'soc', scale: 100 }], min: 0, max: 100, fill: true, hline: 20, fmt: (v) => v.toFixed(0) }], { focus: 'soc' });
  },
};
P.thermal = {
  title: 'Thermal channels', src: 'simulated', canvas: true,
  draw(g, w, h) {
    const n = MC.n(); if (n < 2) return MC.empty(g, w, h, 'Waiting…'); const side = 128, cols = [C.blueL, C.blue, '#5c9bff', '#2a5bbf', C.white, C.orange];
    const cw = w - side, t0 = MC.cols.t[0], t1 = MC.cols.t[n - 1];
    MC.lane(g, 0, 0, cw, h - 16, { title: 'Temperature', noValues: true, unit: '°C', series: MC.THERMAL.map((t, i) => ({ arr: MC.sim.temp[t.k], color: cols[i] })), t0, t1, fmt: (v) => v.toFixed(0) });
    MC.THERMAL.forEach((t, i) => { const v = MC.sim.temp[t.k][MC.cur], y = 22 + i * 26; g.fillStyle = cols[i]; g.fillRect(cw + 8, y - 8, 8, 8); MC.txt(g, t.name, cw + 22, y, C.dim, 'left', 10); MC.txt(g, `${f1(v, 0)} °C`, w - 6, y + 12, cols[i], 'right', 12, true); });
    for (let k = 0; k <= 5; k++) { const tt = t0 + (t1 - t0) * k / 5; MC.txt(g, MC.fmtT(tt), 38 + (cw - 44) * k / 5, h - 3, C.dim, k === 0 ? 'left' : k === 5 ? 'right' : 'center', 9, true); }
  },
};
P.link = {
  title: 'Earth link', src: 'feed + simulated margin', canvas: true,
  draw(g, w, h) {
    const n = MC.n(); if (n < 2) return MC.empty(g, w, h, 'Waiting…'); const margin = MC.series((i) => (Number.isFinite(MC.at('earth', i)) ? MC.link(i).margin : NaN)), rate = MC.series((i) => (Number.isFinite(MC.at('earth', i)) ? MC.link(i).kbps : NaN));
    MC.stack(g, w, h, [{ title: 'Earth height', unit: '°', series: [{ k: 'earthEl' }] }, { title: 'Link margin (simulated)', unit: 'dB', series: [{ arr: margin, color: C.blueL }], min: 0, max: 14, fmt: (v) => v.toFixed(1) }, { title: 'Data rate (simulated)', unit: 'kbps', series: [{ arr: rate, color: C.orange }], min: 0, max: 280, fmt: (v) => v.toFixed(0) }], { focus: 'soc' });
  },
};
P.sky = {
  title: 'Sky view · Sun and Earth', src: 'feed', canvas: true,
  draw(g, w, h) {
    const c = MC.cols, n = MC.n(), cx = w / 2, cy = h / 2 + 4, R = Math.min(w, h) / 2 - 22; if (!MC.has('sunEl')) return MC.empty(g, w, h, 'Waiting for the Sun position…');
    const pos = (az, el) => { const a = az * Math.PI / 180, r = (90 - MC.clamp(el, -15, 90)) / 90 * R; return [cx + r * Math.sin(a), cy - r * Math.cos(a)]; };
    g.strokeStyle = C.grid; g.lineWidth = 1; for (const el of [0, 30, 60]) { g.beginPath(); g.arc(cx, cy, (90 - el) / 90 * R, 0, 7); g.stroke(); MC.txt(g, `${el}°`, cx + 3, cy - (90 - el) / 90 * R - 2, C.dim, 'left', 9, true); }
    g.beginPath(); for (let k = 0; k < 4; k++) { g.moveTo(cx, cy); g.lineTo(cx + R * Math.sin(k * Math.PI / 2), cy - R * Math.cos(k * Math.PI / 2)); } g.stroke(); [['N', 0, -1], ['E', 1, 0], ['S', 0, 1], ['W', -1, 0]].forEach(([t, dx, dy]) => MC.txt(g, t, cx + dx * (R + 10), cy + dy * (R + 10) + 4, C.text, 'center', 11));
    g.strokeStyle = C.blueD; g.lineWidth = 1.5; g.beginPath(); let pen = false; for (let i = 0; i < n; i++) { if (!Number.isFinite(c.sunEl[i])) continue; const [x, y] = pos(c.sunAz[i], c.sunEl[i]); pen ? g.lineTo(x, y) : g.moveTo(x, y); pen = true; } g.stroke();
    g.strokeStyle = C.orange; g.lineWidth = 2; g.beginPath(); pen = false; for (let i = 0; i <= MC.cur; i++) { if (!Number.isFinite(c.sunEl[i])) continue; const [x, y] = pos(c.sunAz[i], c.sunEl[i]); pen ? g.lineTo(x, y) : g.moveTo(x, y); pen = true; } g.stroke();
    const sa = MC.lastFinite('sunAz'), se = MC.lastFinite('sunEl'); if (Number.isFinite(se)) { const [x, y] = pos(sa, se); g.fillStyle = C.orange; g.beginPath(); g.arc(x, y, 7, 0, 7); g.fill(); MC.txt(g, `Sun ${se.toFixed(1)}°`, x + 10, y + 4, C.orange, 'left', 10, true); }
    const ea = MC.S.W?.sky?.earth_azimuth_deg ?? 180, ee = MC.lastFinite('earthEl'); if (Number.isFinite(ee)) { const [x, y] = pos(ea, ee); g.fillStyle = C.blue; g.beginPath(); g.arc(x, y, 6, 0, 7); g.fill(); MC.txt(g, `Earth ${ee.toFixed(1)}°`, x + 10, y + 4, C.blue, 'left', 10, true); }
    MC.txt(g, 'centre = straight up · outer ring = horizon', 8, h - 6, C.dim, 'left', 9);
  },
};
P.skytr = {
  title: 'Sun and Earth height', src: 'feed', canvas: true,
  draw(g, w, h) { MC.stack(g, w, h, [{ title: 'Sun height', unit: '°', series: [{ k: 'sunEl', color: C.orange }] }, { title: 'Earth height', unit: '°', series: [{ k: 'earthEl' }] }, { title: 'Sunlit (1) / shadow (0)', series: [{ k: 'lit', color: C.blueL }], min: -0.1, max: 1.1, fmt: (v) => v.toFixed(0) }]); },
};
P.policy = {
  title: 'Policy diagnostics', src: 'simulated', canvas: true,
  draw(g, w, h) {
    const f = MC.S.last, soc = MC.at('soc'); if (!f || !Number.isFinite(soc)) return MC.empty(g, w, h, 'Policy diagnostics appear once the rover is deployed.');
    const lit = MC.at('lit') === 1, L = lim(), sl = (MC.at('slope') || 0) / L.slope_limit_deg, near = f.drill_target ? 1 : 0;
    const logit = [2 * soc + (lit ? 0.8 : -0.4) - sl, 0.5 + (1 - soc), 2 * (1 - soc) + (lit ? -1 : 0.6), near ? 2 : -2], ex = logit.map(Math.exp), z = ex.reduce((a, b) => a + b, 0), prob = ex.map((e) => e / z), names = ['Drive', 'Hold', 'Sleep', 'Drill'], chosen = MC.at('mode');
    names.forEach((nm, i) => { const y = 22 + i * ((h - 70) / 4); MC.txt(g, nm, 10, y + 10, i === chosen ? C.white : C.dim, 'left', 11); MC.bar(g, 64, y, w - 130, 12, prob[i], i === chosen ? C.blue : C.blueD); MC.txt(g, `${(prob[i] * 100).toFixed(0)} %`, w - 10, y + 10, C.text, 'right', 11, true); if (i === chosen) MC.txt(g, '◀ chosen', w - 56, y + 10, C.blueL, 'right', 9); });
    MC.txt(g, 'Reason given by the controller:', 10, h - 32, C.dim, 'left', 10); const r = f.reason || '—'; MC.txt(g, r.length > 90 ? r.slice(0, 88) + '…' : r, 10, h - 16, C.text, 'left', 11);
  },
};
P.train = {
  title: 'Training curves', src: 'feed', canvas: true,
  draw(g, w, h) {
    const T = MC.S.training; if (!T || !T.rows?.length) return MC.empty(g, w, h, 'No training log found (runs/rover/train_log.jsonl).');
    const rows = T.rows, last = rows[rows.length - 1], pick = (ks) => ks.find((k) => typeof last[k] === 'number'), kr = pick(['reward', 'mean_reward', 'return', 'ep_return', 'mean_return']), kl = pick(['loss', 'policy_loss', 'value_loss']);
    const mk = (key) => rows.map((r, i) => r[key]), lane = (title, arr, col) => ({ title, series: [{ arr, color: col }] }), tt = rows.map((_, i) => i); const lanes = []; if (kr) lanes.push(lane(kr, mk(kr), C.blue)); if (kl) lanes.push(lane(kl, mk(kl), C.orange)); if (!lanes.length) return MC.empty(g, w, h, 'No reward or loss column in the log.');
    const lh = h / lanes.length; lanes.forEach((sp, i) => { const saved = MC.cols.t, savedCur = MC.cur; MC.cols.t = tt; MC.cur = rows.length - 1; MC.lane(g, 0, i * lh, w, lh, { ...sp, t0: 0, t1: rows.length - 1 }); MC.cols.t = saved; MC.cur = savedCur; });
  },
};
})();
