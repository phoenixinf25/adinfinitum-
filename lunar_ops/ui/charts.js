// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Chart primitives drawn on canvas. Palette: midnight black, electric blue, cantaloupe orange.
(function () {
'use strict';
const MC = (window.MC = window.MC || {});

MC.C = { bg: '#060a13', blue: '#2f7dff', blueL: '#8db9ff', blueD: '#14357a', blueDD: '#0b1a3a', orange: '#ffa566', orangeD: '#5e3a1f', dim: '#6f7f9c', text: '#cfd9ee', grid: '#101a2e', white: '#ffffff' };
const C = MC.C, MONO = '"JetBrains Mono", ui-monospace, Menlo, Consolas, monospace', SANS = '"Instrument Sans", -apple-system, "Segoe UI", Helvetica, Arial, sans-serif';
// No sharp corners: every rectangle drawn on any chart canvas gets rounded ends (tiny rectangles become round-ended lines).
(function () {
  const P = CanvasRenderingContext2D.prototype; if (!P.roundRect || P.__soft) return; P.__soft = true; const fr = P.fillRect, sr = P.strokeRect;
  const shape = (x, y, w, h) => { if (w < 0) { x += w; w = -w; } if (h < 0) { y += h; h = -h; } const p = new Path2D(); p.roundRect(x, y, w, h, Math.min(9, w / 2, h / 2)); return p; };
  P.fillRect = function (x, y, w, h) { if (!w || !h) return; if (x <= 0 && y <= 0 && w >= this.canvas.clientWidth - 1 && h >= this.canvas.clientHeight - 1) return fr.call(this, x, y, w, h); this.fill(shape(x, y, w, h)); };
  P.strokeRect = function (x, y, w, h) { if (!w || !h) return; this.stroke(shape(x, y, w, h)); };
})();
// Numbers get the monospace font, everything else the sans font. Splits a string into [text, isNumber] parts.
MC.splitNum = function (t) {
  const re = /\d[\d.,:]*\d|\d/g, out = []; let last = 0, m; t = String(t);
  while ((m = re.exec(t))) { let s = m.index; const e = s + m[0].length, prev = t[s - 1]; if (prev && /[A-Za-z_]/.test(prev)) continue; if ((prev === '-' || prev === '−') && (s === 1 || /[\s(\[]/.test(t[s - 2]))) s--; if (s > last) out.push([t.slice(last, s), 0]); out.push([t.slice(s, e), 1]); last = e; }
  if (last < t.length) out.push([t.slice(last), 0]); return out;
};

MC.clamp = (v, a, b) => Math.min(b, Math.max(a, v));
MC.fit = function (c) {
  const cw = c.clientWidth, ch = c.clientHeight; if (!cw || !ch) return null;
  const dpr = window.devicePixelRatio || 1, w = Math.round(cw * dpr), h = Math.round(ch * dpr);
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  const g = c.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.lineJoin = 'round'; g.lineCap = 'round'; g.fillStyle = C.bg; g.fillRect(0, 0, cw, ch); return { g, w: cw, h: ch };
};
const fontOf = (size, num) => (num ? `500 ${(size * 0.94).toFixed(1)}px ${MONO}` : `${size}px ${SANS}`);
MC.txtWidth = function (g, t, size = 10) { let w = 0; for (const [s, n] of MC.splitNum(t)) { g.font = fontOf(size, n); w += g.measureText(s).width; } return w; };
MC.txt = function (g, t, x, y, col = C.dim, align = 'left', size = 10) {
  const parts = MC.splitNum(t); g.fillStyle = col; g.textBaseline = 'alphabetic'; g.textAlign = 'left'; const ws = parts.map(([s, n]) => { g.font = fontOf(size, n); return g.measureText(s).width; }), total = ws.reduce((a, b) => a + b, 0);
  let cx = align === 'right' ? x - total : align === 'center' ? x - total / 2 : x; parts.forEach(([s, n], i) => { g.font = fontOf(size, n); g.fillText(s, cx, y); cx += ws[i]; });
};
MC.empty = (g, w, h, msg) => MC.txt(g, msg, w / 2, h / 2, C.dim, 'center', 12);
const HEAT = [[8, 14, 32], [18, 46, 108], [47, 125, 255], [141, 185, 255]];
MC.heatRGB = function (v) { v = MC.clamp(v, 0, 1) * 3; const i = Math.min(2, Math.floor(v)), f = v - i, a = HEAT[i], b = HEAT[i + 1]; return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]; };
MC.heat = (v) => { const [r, g, b] = MC.heatRGB(v); return `rgb(${r | 0},${g | 0},${b | 0})`; };
MC.fmtT = (t) => { t = Math.max(0, t); return `${Math.floor(t / 86400)}d ${String(Math.floor(t % 86400 / 3600)).padStart(2, '0')}:${String(Math.floor(t % 3600 / 60)).padStart(2, '0')}`; };
MC.fmtHMS = (t) => { t = Math.max(0, t); return `${String(Math.floor(t % 86400 / 3600)).padStart(2, '0')}:${String(Math.floor(t % 3600 / 60)).padStart(2, '0')}:${String(Math.floor(t % 60)).padStart(2, '0')}`; };

// One time-series lane. sp: {title, unit, series:[{k|arr, color, scale, label}], min, max, fmt, fill, hline, t0, t1}
MC.lane = function (g, x, y, w, h, sp) {
  const t = MC.cols.t, n = t.length, cur = MC.cur, LM = 38, RM = 6, px = x + LM, pw = w - LM - RM, top = y + 13, ph = h - 16;
  const S = sp.series.map((s) => ({ ...s, a: s.arr || MC.cols[s.k], sc: s.scale ?? 1 }));
  let lo = sp.min, hi = sp.max;
  if (lo == null || hi == null) { let a = Infinity, b = -Infinity; for (const s of S) for (let i = 0; i < n; i++) { if (t[i] < sp.t0 || t[i] > sp.t1) continue; const v = s.a[i] * s.sc; if (Number.isFinite(v)) { if (v < a) a = v; if (v > b) b = v; } } if (!Number.isFinite(a)) { a = 0; b = 1; } if (b - a < 1e-9) b = a + 1; const pad = (b - a) * 0.08; lo = lo ?? a - pad; hi = hi ?? b + pad; }
  const X = (tt) => px + (tt - sp.t0) / ((sp.t1 - sp.t0) || 1) * pw, Y = (v) => top + (1 - (v - lo) / (hi - lo)) * ph;
  g.strokeStyle = C.grid; g.lineWidth = 1; g.beginPath(); for (let i = 0; i <= 3; i++) { const yy = top + ph * i / 3; g.moveTo(px, yy); g.lineTo(px + pw, yy); } g.stroke();
  if (lo < 0 && hi > 0) { g.strokeStyle = C.blueD; g.beginPath(); g.moveTo(px, Y(0)); g.lineTo(px + pw, Y(0)); g.stroke(); }
  if (sp.hline != null) { g.strokeStyle = C.orange; g.setLineDash([4, 3]); g.beginPath(); g.moveTo(px, Y(sp.hline)); g.lineTo(px + pw, Y(sp.hline)); g.stroke(); g.setLineDash([]); }
  const stride = Math.max(1, Math.floor(n / (pw * 1.5)));
  g.save(); g.beginPath(); g.rect(px, top - 1, pw, ph + 2); g.clip();
  const path = (s, i0, i1) => { let pen = false; g.beginPath(); for (let i = i0; i <= i1; i += stride) { const v = s.a[i] * s.sc; if (!Number.isFinite(v)) { pen = false; continue; } const xx = X(t[i]), yy = Y(v); pen ? g.lineTo(xx, yy) : g.moveTo(xx, yy); pen = true; } };
  S.forEach((s, si) => {
    const col = s.color || (si ? C.orange : C.blue);
    if (cur < n - 1) { g.globalAlpha = 0.28; g.strokeStyle = col; g.lineWidth = 1; path(s, 0, n - 1); g.stroke(); g.globalAlpha = 1; }
    if (cur >= 0) { path(s, 0, cur); if (sp.fill && si === 0) { g.save(); g.lineTo(X(t[cur]), top + ph); g.lineTo(X(t[0]), top + ph); g.fillStyle = col + '24'; g.fill(); g.restore(); path(s, 0, cur); } g.strokeStyle = col; g.lineWidth = 1.6; g.stroke(); }
  });
  if (cur >= 0 && cur < n) { const cx = X(t[cur]); g.strokeStyle = C.white; g.globalAlpha = 0.55; g.beginPath(); g.moveTo(cx, top); g.lineTo(cx, top + ph); g.stroke(); g.globalAlpha = 1; }
  g.restore();
  MC.txt(g, sp.title, x + 6, y + 10, C.dim, 'left', 10);
  let rx = x + w - RM; if (!sp.noValues) for (let si = S.length - 1; si >= 0; si--) { const s = S[si], v = cur >= 0 ? s.a[cur] * s.sc : NaN, str = (Number.isFinite(v) ? (sp.fmt ? sp.fmt(v) : v.toFixed(1)) : '—') + (sp.unit ? ' ' + sp.unit : ''); MC.txt(g, str, rx, y + 10, s.color || (si ? C.orange : C.blue), 'right', 11, true); rx -= str.length * 6.6 + 12; if (s.label) { MC.txt(g, s.label, rx + 6, y + 10, C.dim, 'right', 9); rx -= s.label.length * 5.2 + 6; } }
  MC.txt(g, hi.toFixed(Math.abs(hi) < 10 ? 1 : 0), px - 4, top + 8, C.dim, 'right', 9, true); MC.txt(g, lo.toFixed(Math.abs(lo) < 10 ? 1 : 0), px - 4, top + ph, C.dim, 'right', 9, true);
};
// A stack of lanes sharing one time axis, with a phase bar and time ticks at the bottom.
MC.stack = function (g, w, h, lanes, o = {}) {
  const n = MC.n(); if (n < 2) { MC.empty(g, w, h, 'Waiting for data…'); return; }
  let t0 = MC.cols.t[0], t1 = MC.cols.t[n - 1]; if (o.focus) { const a = MC.cols[o.focus]; let i0 = -1, i1 = -1; for (let i = 0; i < n; i++) if (Number.isFinite(a[i])) { if (i0 < 0) i0 = i; i1 = i; } if (i0 >= 0 && i1 > i0) { const m = (MC.cols.t[i1] - MC.cols.t[i0]) * 0.02; t0 = MC.cols.t[i0] - m; t1 = MC.cols.t[i1] + m; } }
  const barH = o.noPhase ? 0 : 18, lh = (h - barH) / lanes.length;
  lanes.forEach((sp, i) => MC.lane(g, 0, i * lh, w, lh, { ...sp, t0, t1 }));
  if (!barH) return;
  const LM = 38, pw = w - LM - 6, y = h - barH + 2, X = (tt) => LM + (tt - t0) / ((t1 - t0) || 1) * pw;
  for (let i = 0; i < n; i++) { const a = MC.cols.t[i], b = i + 1 < n ? MC.cols.t[i + 1] : a, ph = MC.cols.ph[i]; if (b < t0 || a > t1) continue; g.fillStyle = ['#14357a', '#1b4aa6', '#2f7dff', '#5c9bff', '#8db9ff'][ph]; g.fillRect(X(a), y, Math.max(1, X(b) - X(a) + 0.5), 5); }
  for (let k = 0; k <= 5; k++) { const tt = t0 + (t1 - t0) * k / 5; MC.txt(g, MC.fmtT(tt), X(tt), h - 2, C.dim, k === 0 ? 'left' : k === 5 ? 'right' : 'center', 9, true); }
};
// Round gauge: sweep 240 degrees. o: {label, unit, min, max, warnAbove, warnBelow, fmt}
MC.gauge = function (g, cx, cy, r, v, o) {
  const a0 = Math.PI * 0.8, a1 = Math.PI * 2.2, f = Number.isFinite(v) ? MC.clamp((v - o.min) / (o.max - o.min), 0, 1) : 0;
  const warn = Number.isFinite(v) && ((o.warnAbove != null && v > o.warnAbove) || (o.warnBelow != null && v < o.warnBelow)), col = warn ? C.orange : C.blue;
  g.lineWidth = Math.max(4, r * 0.16); g.lineCap = 'round'; g.strokeStyle = C.blueDD; g.beginPath(); g.arc(cx, cy, r, a0, a1); g.stroke();
  if (f > 0) { g.strokeStyle = col; g.beginPath(); g.arc(cx, cy, r, a0, a0 + (a1 - a0) * f); g.stroke(); }
  g.lineCap = 'butt'; MC.txt(g, Number.isFinite(v) ? (o.fmt ? o.fmt(v) : v.toFixed(0)) : '—', cx, cy + r * 0.12, warn ? C.orange : C.white, 'center', Math.max(11, r * 0.5), true);
  MC.txt(g, o.unit || '', cx, cy + r * 0.52, C.dim, 'center', Math.max(8, r * 0.26)); MC.txt(g, o.label, cx, cy + r * 1.28, C.text, 'center', Math.max(9, r * 0.26));
};
// Horizontal bar with value text.
MC.bar = function (g, x, y, w, h, f, col = C.blue) { g.fillStyle = C.blueDD; g.fillRect(x, y, w, h); g.fillStyle = col; g.fillRect(x, y, w * MC.clamp(f, 0, 1), h); };
})();
