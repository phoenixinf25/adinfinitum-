// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Animated numbers using NumberFlow (vendor/number-flow, MIT, https://github.com/barvian/number-flow).
// Panels write placeholders with MC.nf(); after the HTML is set, MC.nfHydrate() swaps each placeholder for a persistent
// <number-flow> element, so a changing value rolls from the old digits to the new ones instead of jumping.
(function () {
'use strict';
const MC = (window.MC = window.MC || {});
MC.NumberFlow = null; MC.nfCache = new Map();
// Wrap every number in already-rendered text with <span class="num"> so only numbers use the monospace font.
MC.numify = function (root) {
  if (!root) return; const nodes = [], w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (n) => { const p = n.parentElement; if (!p || p.closest('.num, number-flow, script, style, select, option, input, textarea')) return NodeFilter.FILTER_REJECT; return /\d/.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT; } });
  while (w.nextNode()) nodes.push(w.currentNode);
  for (const n of nodes) { const parts = MC.splitNum(n.nodeValue); if (parts.every((p) => !p[1])) continue; const frag = document.createDocumentFragment(); for (const [s, isNum] of parts) { if (isNum) { const sp = document.createElement('span'); sp.className = 'num'; sp.textContent = s; frag.append(sp); } else frag.append(document.createTextNode(s)); } n.replaceWith(frag); }
};
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
// Placeholder for an animated number. key must be unique within the panel. Falls back to plain text when v is not a number.
MC.nf = function (key, v, o = {}) {
  const d = o.d ?? 0, suf = o.suf || '', pre = o.pre || '';
  if (!Number.isFinite(v)) return '<span class="nf-na">—</span>';
  return `<span class="nf" data-nf="${esc(key)}" data-v="${v}" data-d="${d}" data-suf="${esc(suf)}" data-pre="${esc(pre)}" data-sign="${o.sign ? 1 : 0}">${esc(pre)}${v.toFixed(d)}${esc(suf)}</span>`;
};
MC.nfHydrate = function (root, scope) {
  if (!MC.NumberFlow) return;
  for (const ph of root.querySelectorAll('[data-nf]')) {
    const k = `${scope}:${ph.dataset.nf}`; let el = MC.nfCache.get(k); if (!el) { el = new MC.NumberFlow(); MC.nfCache.set(k, el); }
    const d = Number(ph.dataset.d); el.format = { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: false, signDisplay: ph.dataset.sign === '1' ? 'exceptZero' : 'auto' };
    el.numberPrefix = ph.dataset.pre; el.numberSuffix = ph.dataset.suf; el.update(Number(ph.dataset.v)); ph.replaceWith(el);
  }
};
// A clock made of rolling digits: d days, hh:mm:ss. Returns a setter taking seconds.
MC.makeTimeFlow = function (host, withDays = true) {
  const parts = withDays ? [['d', ' d '], ['h', ':'], ['m', ':'], ['s', '']] : [['h', ':'], ['m', ':'], ['s', '']], els = {}; host.textContent = '';
  for (const [k, sep] of parts) { const nf = new MC.NumberFlow(); nf.format = k === 'd' ? { useGrouping: false } : { minimumIntegerDigits: 2, useGrouping: false }; els[k] = nf; host.append(nf); if (sep) host.append(document.createTextNode(sep)); }
  return (t, animateSeconds = true) => { t = Math.max(0, t || 0); for (const k in els) els[k].animated = animateSeconds; if (els.d) els.d.update(Math.floor(t / 86400)); els.h.update(Math.floor(t % 86400 / 3600)); els.m.update(Math.floor(t % 3600 / 60)); els.s.update(Math.floor(t % 60)); };
};
addEventListener('nf-ready', () => { MC.NumberFlow = window.__NumberFlow; MC.nfReady && MC.nfReady(); });
})();
