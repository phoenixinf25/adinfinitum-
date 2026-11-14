// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Charts drawn by OpenUI (vendor/openui, MIT, https://github.com/thesysdev/openui): its React chart components, with their
// built-in animation, are fed from the mission data through OpenUI Lang, a small declarative language.
(function () {
'use strict';
const MC = (window.MC = window.MC || {}), P = MC.panels, q = (s) => JSON.stringify(String(s)), r2 = (v) => (Number.isFinite(v) ? Math.round(v * 100) / 100 : 0);
const lim = () => MC.S.W?.limits || { battery_capacity_wh: 350, solar_peak_w: 50, slope_limit_deg: 20 };
const wait = (msg) => `root = Card([t])\nt = TextContent(${q(msg)}, "small")`;
// Average of an array over n equal slices of [i0, i1] (NaN slices become 0).
function slices(arr, i0, i1, n) { const out = [], step = (i1 - i0 + 1) / n; for (let k = 0; k < n; k++) { let s = 0, c = 0; for (let i = Math.floor(i0 + k * step); i < Math.floor(i0 + (k + 1) * step) || (c === 0 && i <= i1 && i < Math.floor(i0 + (k + 1) * step) + 1); i++) { const v = arr[i]; if (Number.isFinite(v)) { s += v; c++; } } out.push(c ? s / c : 0); } return out; }
function span(key) { const a = MC.cols[key]; let i0 = -1, i1 = -1; for (let i = 0; i <= MC.cur && i < a.length; i++) if (Number.isFinite(a[i])) { if (i0 < 0) i0 = i; i1 = i; } return i0 >= 0 && i1 > i0 ? [i0, i1] : null; }
const labels = (i0, i1, n) => { const t = MC.cols.t, out = [], step = (i1 - i0) / n, short = t[i1] - t[i0] < 3600, mmss = (s) => `${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`; for (let k = 0; k < n; k++) { const s = t[Math.floor(i0 + k * step)]; out.push(short ? mmss(s) : MC.fmtHMS(s).slice(0, 5)); } return out; };
const arr = (a) => '[' + a.map(r2).join(',') + ']', strs = (a) => '[' + a.map(q).join(',') + ']';
const ch = (p) => Math.max(70, (p.el.clientHeight || 200) - 62);

const oui = (id, title, src, lang) => { P[id] = { title, src, oui: true, lang }; };
oui('ouiPower', 'Solar vs load', 'feed', (p) => { const s = span('solar'); if (!s) return wait('Rover power appears after landing.'); const n = 14, L = labels(s[0], s[1], n); return `root = Card([c])\nc = LineChart(${strs(L)}, [a, b], "natural", "time since landing (h:min)", "W", ${ch(p)})\na = Series("Solar W", ${arr(slices(MC.cols.solar, s[0], s[1], n))})\nb = Series("Load W", ${arr(slices(MC.cols.load, s[0], s[1], n))})`; });
oui('ouiBattery', 'Battery', 'feed', (p) => { const s = span('soc'); if (!s) return wait('Battery appears after landing.'); const n = 14, L = labels(s[0], s[1], n); return `root = Card([c])\nc = AreaChart(${strs(L)}, [a, b], "natural", "time since landing (h:min)", "%", ${ch(p)})\na = Series("Battery %", ${arr(slices(MC.cols.soc.map((v) => v * 100), s[0], s[1], n))})\nb = Series("Save-power level", ${arr(new Array(n).fill(20))})`; });
oui('ouiThermal', 'Temperatures', 'simulated', (p) => { const n = 14, i1 = MC.cur; if (i1 < 3) return wait('Waiting for data…'); const L = labels(0, i1, n), ser = MC.THERMAL.map((t, k) => `s${k} = Series(${q(t.name + ' °C')}, ${arr(slices(MC.sim.temp[t.k], 0, i1, n))})`); return `root = Card([c])\nc = LineChart(${strs(L)}, [${MC.THERMAL.map((_, k) => 's' + k).join(', ')}], "natural", "time since start (h:min)", "°C", ${ch(p)})\n${ser.join('\n')}`; });
oui('ouiEnergy', 'Energy by subsystem', 'simulated split', (p) => { const s = span('load'); if (!s) return wait('Rover energy appears after landing.'); const n = 8, c = MC.cols, L = labels(s[0], s[1], n), cats = Object.keys(MC.SPLIT.drive), acc = cats.map(() => new Array(n).fill(0)), step = (s[1] - s[0] + 1) / n;
  for (let i = s[0]; i <= s[1]; i++) { const k = Math.min(n - 1, Math.floor((i - s[0]) / step)), dt = i ? Math.max(0, c.t[i] - c.t[i - 1]) : 0, sp = MC.SPLIT[MC.MODES[c.mode[i]] || 'hold']; if (!Number.isFinite(c.load[i])) continue; cats.forEach((nm, j) => { acc[j][k] += c.load[i] * sp[nm] * dt / 3600; }); }
  return `root = Card([c])\nc = BarChart(${strs(L)}, [${cats.map((_, j) => 's' + j).join(', ')}], "stacked", "time since landing (h:min)", "Wh", ${ch(p)})\n${cats.map((nm, j) => `s${j} = Series(${q(nm + ' Wh')}, ${arr(acc[j])})`).join('\n')}`; });
oui('ouiSplit', 'Power split now', 'simulated split', () => { const load = MC.at('load'); if (!Number.isFinite(load)) return wait('Rover power appears after landing.'); const sp = MC.SPLIT[MC.MODES[MC.at('mode')] || 'hold'], cats = Object.keys(sp).filter((k) => sp[k] > 0); return `root = Card([c])\nc = PieChart(${strs(cats)}, ${arr(cats.map((k) => load * sp[k]))}, "donut")`; });
oui('ouiRadar', 'Health check (100 = best)', 'derived', () => { if (!Number.isFinite(MC.at('soc'))) return wait('Health check appears after landing.'); const L = lim(), lk = MC.link(), tb = MC.sim.temp.battery[MC.cur];
  const names = ['Battery', 'Solar input', 'Earth link', 'Thermal margin', 'Slope margin', 'Hazard margin'], vals = [MC.at('soc') * 100, MC.at('solar') / L.solar_peak_w * 100, lk.margin / 14 * 100, (tb + 10) / 40 * 100, (1 - MC.at('slope') / L.slope_limit_deg) * 100, (1 - MC.at('haz')) * 100].map((v) => Math.max(0, Math.min(100, v)));
  return `root = Card([c])\nc = RadarChart(${strs(names)}, [s])\ns = Series("Health", ${arr(vals)})`; });
oui('ouiTargets', 'Round trip to each target', 'derived', (p) => { const W = MC.S.W; if (!W || MC.cur < 0) return wait('Waiting…'); const x = MC.lastFinite('x'), y = MC.lastFinite('y'), px = Number.isFinite(x) ? x : W.start.x_m, py = Number.isFinite(y) ? y : W.start.y_m, used = MC.lastFinite('used'), dist = MC.lastFinite('dist'), k = Number.isFinite(used) && dist > 50 ? Math.min(3, Math.max(0.1, used / dist)) : 0.35, usable = Math.max(0, (MC.lastFinite('wh') || 0) - 0.2 * lim().battery_capacity_wh);
  const T = (W.targets || []).map((t) => ({ id: t.id, rt: 2 * Math.hypot(t.x_m - px, t.y_m - py) * k })).sort((a, b) => a.rt - b.rt).slice(0, 5); return `root = Card([c, n])\nc = HorizontalBarChart(${strs(T.map((t) => t.id))}, [a], "grouped", "Wh", "")\na = Series("Round trip Wh (estimate)", ${arr(T.map((t) => t.rt))})\nn = TextContent(${q('The 5 nearest targets. Usable energy now: ' + usable.toFixed(0) + ' Wh (battery above the 20 % floor).')}, "small")`; });
oui('ouiScatter', 'Targets: distance vs ice score', 'derived', () => { const W = MC.S.W, f = MC.S.last; if (!W || !f) return wait('Waiting…'); const x = MC.lastFinite('x'), y = MC.lastFinite('y'), px = Number.isFinite(x) ? x : W.start.x_m, py = Number.isFinite(y) ? y : W.start.y_m, open = [], done = [];
  for (const t of W.targets || []) (f.targets?.find((q2) => q2.id === t.id)?.sampled ? done : open).push(`Point(${r2(Math.hypot(t.x_m - px, t.y_m - py))}, ${r2(t.ice_score)}, ${r2(t.depth_m ?? 40)})`);
  const sets = [open.length ? `o = ScatterSeries("Open", [${open.join(', ')}])` : '', done.length ? `d = ScatterSeries("Sampled", [${done.join(', ')}])` : ''].filter(Boolean); return `root = Card([c])\nc = ScatterChart([${[open.length ? 'o' : '', done.length ? 'd' : ''].filter(Boolean).join(', ')}], "distance from rover (m)", "ice score")\n${sets.join('\n')}`; });
oui('ouiLander', 'Descent altitude', 'feed', (p) => { const s = span('alt'); if (!s) return wait('Descent altitude appears during the landing.'); const n = 16, L = labels(s[0], s[1], n); return `root = Card([c])\nc = AreaChart(${strs(L)}, [a], "natural", "time (min:s)", "m", ${ch(p)})\na = Series("Altitude m", ${arr(slices(MC.cols.alt, s[0], s[1], n))})`; });
oui('ouiEngines', 'Engine throttle', 'feed', () => { const eng = MC.lastFinite('eng'), th = MC.lastFinite('thrust'); if (!Number.isFinite(eng)) return wait('Engines appear during the landing.'); const per = th / Math.max(eng, 1) / 800 * 100, v = [0, 1, 2, 3, 4].map((i) => (eng < 5 && [1, 3].includes(i) ? 0 : per)); return `root = Card([c])\nc = RadialChart(["E1","E2","E3","E4","E5"], ${arr(v)})`; });
oui('ouiTime', 'Time in each activity', 'derived', () => { const c = MC.cols, cnt = [0, 0, 0, 0]; for (let i = 0; i <= MC.cur; i++) if (c.mode[i] >= 0) cnt[c.mode[i]]++; if (cnt.every((v) => v === 0)) return wait('Activity appears after landing.'); return `root = Card([c])\nc = SingleStackedBarChart(["Driving","Waiting","Sleeping","Drilling"], ${arr(cnt)})`; });

// A short notice built from OpenUI's Callout component; it slides in with OpenUI's animation and fades out with OpenUI's callout fade.
MC.toast = function (variant, title, desc) {
  const O = window.__OpenUI, host = document.getElementById('toasts'); if (!O || !host) return;
  const el = document.createElement('div'); el.className = 'toast'; host.appendChild(el); const root = O.createRoot(el);
  root.render(O.React.createElement(O.Renderer, { response: `root = Card([c])\nc = Callout(${q(variant)}, ${q(title)}, ${q(desc)})`, library: O.openuiChatLibrary }));
  setTimeout(() => { el.classList.add('out'); setTimeout(() => { try { root.unmount(); } catch (e) { /* already gone */ } el.remove(); }, 700); }, 4600);
  while (host.children.length > 4) host.firstChild.remove();
};
// Render one OpenUI panel; called by the app loop. Re-renders only when the Lang text changed, so the chart animates between states.
MC.ouiRender = function (p, now) {
  const O = window.__OpenUI; if (!O) { if (!p.msgd) { p.el.innerHTML = '<div class="msg">Loading chart library…</div>'; p.msgd = true; } return; }
  if (now - (p.t || 0) < 900 && p.last) return; p.t = now; const lang = p.def.lang(p); if (lang === p.last) return; p.last = lang;
  if (!p.root) { p.el.innerHTML = ''; p.root = O.createRoot(p.el); } p.root.render(O.React.createElement(O.Renderer, { response: lang, library: O.openuiChatLibrary }));
};
})();
