// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Mission-control frontend (Vizard-style). It only speaks the protocol in lunar_ops/PROTOCOL.md:
// any backend that sends `world` and `frame` messages over /ws/ui (or a replay of them) drives it.
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { GLTFLoader } from './vendor/GLTFLoader.js';
import { OBJLoader } from './vendor/OBJLoader.js';
import { EffectComposer } from './vendor/EffectComposer.js';
import { RenderPass } from './vendor/RenderPass.js';
import { UnrealBloomPass } from './vendor/UnrealBloomPass.js';
import { OutputPass } from './vendor/OutputPass.js';

const $ = (id) => document.getElementById(id);
const Q = new URLSearchParams(location.search);
const DEG = Math.PI / 180, R_MOON = 1737.4;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const b64 = (s) => { const bin = atob(s); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; };
const pad = (n, k = 2) => String(Math.floor(n)).padStart(k, '0');
const fmtMET = (t) => { t = Math.max(0, t); return `T+ ${pad(t / 86400)}d ${pad(t % 86400 / 3600)}:${pad(t % 3600 / 60)}:${pad(t % 60)}`; };
const fmtSim = (t) => { t = Math.max(0, t); return `${pad(t / 86400)}:${pad(t % 86400 / 3600)}:${pad(t % 3600 / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`; };
const fmtShort = (t) => `${pad(t / 86400)}d ${pad(t % 86400 / 3600)}:${pad(t % 3600 / 60)}`;
const lerp3 = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
const RAMP_ICE = [[0.08, 0.04, 0.2], [0.35, 0.1, 0.5], [0.7, 0.2, 0.55], [0.98, 0.45, 0.35], [1.0, 0.85, 0.5]];
const RAMP_HAZ = [[0.15, 0.55, 0.35], [0.85, 0.8, 0.25], [0.95, 0.5, 0.2]];
function ramp(stops, v) { v = clamp(v, 0, 1) * (stops.length - 1); const i = Math.min(Math.floor(v), stops.length - 2); return lerp3(stops[i], stops[i + 1], v - i); }
function hash2(x, y) { let h = Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967295; }
function vnoise(x, y) { const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
  const a = hash2(xi, yi), b = hash2(xi + 1, yi), c = hash2(xi, yi + 1), d = hash2(xi + 1, yi + 1); return (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sy; }
const fbm = (x, y) => 0.5 * vnoise(x, y) + 0.25 * vnoise(2 * x, 2 * y) + 0.125 * vnoise(4 * x, 4 * y) + 0.0625 * vnoise(8 * x, 8 * y);

// ---------------------------------------------------------------- state
const S = {
  W: null, mode: 'none', ws: null, playing: true, speed: Number(Q.get('speed') || 600), frames: [], idx: -1, simT: 0, T0: 0, T1: 1,
  last: null, trail: [], phases: [], hist: [], layer: Q.get('layer') || 'terrain', cam: Q.get('cam') || 'auto', ex: 1, lit: null,
  override: false, keys: {}, path: null, rs: { x: 0, z: 0, h: 0 }, scene: 'orbit', orbitTrail: [], orbitPath: [], phaseNow: 'ORBIT',
  show: { sites: true, path: true, trail: true, stars: true, earth: true }, detail: Q.get('detail') !== '0', style: Q.get('style') || 'photo', ctxAz: null,
};

// ---------------------------------------------------------------- renderer + scenes
const canvas = $('gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = false; // shadows come from the model's horizon mask (see litTex), not a shadow map
renderer.outputColorSpace = THREE.SRGBColorSpace;

const oScene = new THREE.Scene(), sScene = new THREE.Scene();
const composer = new EffectComposer(renderer), renderPass = new RenderPass(sScene, null), bloom = new UnrealBloomPass(new THREE.Vector2(512, 512), 0.55, 0.6, 0.82);
composer.addPass(renderPass); composer.addPass(bloom); composer.addPass(new OutputPass());
const STYLES = { photo: { exp: 1.0, sun: 20, amb: 0.6, ambC: 0x23304a, bloom: false, vignette: false }, cine: { exp: 1.25, sun: 24, amb: 0.75, ambC: 0x2a3a5c, bloom: true, vignette: true },
  vizard: { exp: 1.1, sun: 9, amb: 2.6, ambC: 0x7d8796, bloom: false, vignette: false } };
function applyStyle(name) { S.style = STYLES[name] ? name : 'photo'; const st = STYLES[S.style];
  // With a real photo draped on the terrain, its own (averaged) shading carries the look: soft fill light, gentle Sun accent.
  const ph = S.W?.photo ? { sun: 0.3, amb: 2.6 } : { sun: 1, amb: 1 };
  renderer.toneMappingExposure = st.exp; if (sunLight) sunLight.intensity = st.sun * ph.sun; if (ambient) { ambient.intensity = st.amb * ph.amb; ambient.color.setHex(S.W?.photo ? 0xb8c0cc : st.ambC); }
  document.body.classList.toggle('vignette', st.vignette); }
function draw(scene, cam) { if (STYLES[S.style].bloom) { renderPass.scene = scene; renderPass.camera = cam; composer.render(); } else renderer.render(scene, cam); }
oScene.background = new THREE.Color(0x000000); sScene.background = new THREE.Color(0x000000);
const oCam = new THREE.PerspectiveCamera(38, 1, 20, 3e6), sCam = new THREE.PerspectiveCamera(46, 1, 0.5, 60000), rCam = new THREE.PerspectiveCamera(62, 1.6, 0.1, 60000);
const oCtl = new OrbitControls(oCam, canvas), sCtl = new OrbitControls(sCam, canvas);
for (const c of [oCtl, sCtl]) { c.enableDamping = true; c.dampingFactor = 0.08; }
oCtl.minDistance = 1900; oCtl.maxDistance = 40000; sCtl.maxPolarAngle = Math.PI * 0.497; sCtl.maxDistance = 9000;

function addStars(scene) {
  const n = 3500, p = new Float32Array(n * 3), c = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { const u = Math.random() * 2 - 1, a = Math.random() * 2 * Math.PI, s = Math.sqrt(1 - u * u), r = 2.5e6;
    p.set([r * s * Math.cos(a), r * u, r * s * Math.sin(a)], 3 * i); const k = 0.35 + 0.65 * Math.pow(Math.random(), 3); c.set([k, k * (0.92 + 0.1 * Math.random()), k], 3 * i); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(p, 3)); g.setAttribute('color', new THREE.BufferAttribute(c, 3));
  const pts = new THREE.Points(g, new THREE.PointsMaterial({ size: 1.7, sizeAttenuation: false, vertexColors: true, fog: false })); pts.frustumCulled = false; scene.add(pts); return pts;
}
const oStars = addStars(oScene), sStars = addStars(sScene);

// ---- orbit scene: NASA LROC colour + LOLA elevation on a sphere, scaled in km
const texLoader = new THREE.TextureLoader();
const moonColor = texLoader.load('assets/moon/moon_color_4k.jpg'); moonColor.colorSpace = THREE.SRGBColorSpace; moonColor.anisotropy = 8;
const moonBump = texLoader.load('assets/moon/moon_height_2k.png');
const moon = new THREE.Mesh(new THREE.SphereGeometry(R_MOON, 160, 80), new THREE.MeshStandardMaterial({ map: moonColor, bumpMap: moonBump, bumpScale: 5, roughness: 1, metalness: 0 }));
oScene.add(moon);
const oSun = new THREE.DirectionalLight(0xfff6e8, 3.6); oScene.add(oSun); oScene.add(new THREE.AmbientLight(0x1a2233, 0.55));
const earthTex = (() => { const c = document.createElement('canvas'); c.width = 256; c.height = 128; const g = c.getContext('2d');
  const gr = g.createLinearGradient(0, 0, 0, 128); gr.addColorStop(0, '#2f5fae'); gr.addColorStop(0.5, '#3b78c9'); gr.addColorStop(1, '#244b8f'); g.fillStyle = gr; g.fillRect(0, 0, 256, 128);
  for (let i = 0; i < 700; i++) { g.fillStyle = `rgba(255,255,255,${Math.random() * 0.22})`; g.beginPath(); g.ellipse(Math.random() * 256, Math.random() * 128, 4 + Math.random() * 22, 1 + Math.random() * 5, 0, 0, 7); g.fill(); }
  for (let i = 0; i < 14; i++) { g.fillStyle = 'rgba(92,120,70,0.75)'; g.beginPath(); g.ellipse(Math.random() * 256, 20 + Math.random() * 90, 6 + Math.random() * 18, 4 + Math.random() * 10, Math.random() * 3, 0, 7); g.fill(); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t; })();
const earthO = new THREE.Mesh(new THREE.SphereGeometry(6371 * 0.22, 48, 24), new THREE.MeshStandardMaterial({ map: earthTex, roughness: 0.9, emissive: 0x0b1a33, emissiveIntensity: 0.6 }));
earthO.position.set(-60000, 4000, 45000); oScene.add(earthO);   // illustrative scale (0.22 x radius), labelled in the UI
const siteRing = new THREE.Mesh(new THREE.RingGeometry(34, 44, 48), new THREE.MeshBasicMaterial({ color: 0x6fd3ff, side: THREE.DoubleSide, transparent: true, opacity: 0.9, depthTest: false }));
siteRing.renderOrder = 5; oScene.add(siteRing);
const orbitTrailLine = lineObj(0x7ee08e, 4000, oScene), orbitPathLine = lineObj(0x4b6a82, 1200, oScene, true);

function llr(lat, lon, r) { const la = lat * DEG, lo = lon * DEG; return new THREE.Vector3(r * Math.cos(la) * Math.cos(lo), r * Math.sin(la), -r * Math.cos(la) * Math.sin(lo)); }
function lineObj(color, max, scene, faint) {
  const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(max * 3), 3)); geo.setDrawRange(0, 0);
  const l = new THREE.Line(geo, new THREE.LineBasicMaterial({ color, transparent: true, opacity: faint ? 0.55 : 1, depthTest: false })); l.frustumCulled = false; l.renderOrder = 6; scene.add(l); return l;
}
function setLineV(line, pts) { const a = line.geometry.attributes.position.array, n = Math.min(pts.length, a.length / 3); for (let i = 0; i < n; i++) { a[3 * i] = pts[i].x; a[3 * i + 1] = pts[i].y; a[3 * i + 2] = pts[i].z; } line.geometry.setDrawRange(0, n); line.geometry.attributes.position.needsUpdate = true; }

// ---- labels and vehicle markers (real models replace the markers automatically when present)
function label(text, color = '#ffffff', w = 1.0) {
  const c = document.createElement('canvas'); c.width = 256; c.height = 64; const g = c.getContext('2d'); g.font = '600 30px Helvetica, Arial, sans-serif'; g.textAlign = 'center'; g.fillStyle = color;
  g.shadowColor = '#000'; g.shadowBlur = 7; g.fillText(text, 128, 42);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false, transparent: true })); s.scale.set(4 * w, 1 * w, 1); s.renderOrder = 20; return s;
}
function makeMarker(kind, color) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.OctahedronGeometry(0.5, 0), new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.55, roughness: 0.4 })); body.position.y = 0.6; g.add(body);
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.85, 1, 48), new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity: 0.9, depthTest: false })); ring.rotation.x = -Math.PI / 2; ring.position.y = 0.05; ring.renderOrder = 8; g.add(ring);
  const tag = label(kind.toUpperCase(), '#' + new THREE.Color(color).getHexString(), 0.9); tag.position.y = 2.6; g.add(tag); g.userData = { tag, body, isMarker: true }; return g;
}
const models = {};
async function loadModel(kind) {
  const cfg = await fetch('assets/models/models.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  for (const ext of ['glb', 'obj']) {
    try { const r = await fetch(`assets/models/${kind}.${ext}`, { method: 'HEAD' }); if (!r.ok) continue;
      const obj = ext === 'glb' ? (await new GLTFLoader().loadAsync(`assets/models/${kind}.glb`)).scene : await new OBJLoader().loadAsync(`assets/models/${kind}.obj`);
      const c = cfg[kind] || {}; obj.scale.setScalar(c.scale || 1); if (c.rotation_deg) obj.rotation.set(...c.rotation_deg.map((d) => d * DEG));
      obj.traverse((m) => { if (m.isMesh) { m.castShadow = true; m.receiveShadow = true; } }); models[kind] = obj; return obj; } catch (e) { /* try next */ }
  }
  return null;
}
function vehicleObject(kind, color) {
  const g = new THREE.Group(); g.userData.kind = kind;
  const fallback = makeMarker(kind, color); g.add(fallback); g.userData.fallback = fallback;
  loadModel(kind).then((m) => { if (m) { g.remove(fallback); g.add(m.clone(true)); g.userData.hasModel = true; g.userData.fallback = null; } }); return g;
}
const sizeM = { lander: 3.5, rover: 1.2 };
function scaleForView(g, camPos, minFrac = 0.035) { const d = camPos.distanceTo(g.getWorldPosition(new THREE.Vector3())); const base = sizeM[g.userData.kind] || 1; g.scale.setScalar(Math.max(1, (d * minFrac) / base)); }

// ---- surface scene
let terrain = null, terrainGeo = null, ctxMesh = null, ctxGeo = null, rocks = null, sunLight = null, sunDisc = null, earthS = null, ambient = null;
let landerS = null, roverS = null, plume = null, trailLine = null, pathLine = null, descentLine = null;
// Terrain material: physically based, with direct sunlight multiplied by a shadow mask texture
// (main tile: the simulator's horizon mask; surrounding landscape: computed here from the DEM).
function makeTerrainMat(u) {
  const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 1, metalness: 0 });
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, u);
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nuniform vec2 litOrigin; uniform vec2 litSize; varying vec2 vLitUv;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvLitUv = (position.xz - litOrigin) / litSize;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nuniform sampler2D litTex; varying vec2 vLitUv;')
      .replace('#include <lights_fragment_end>', '#include <lights_fragment_end>\nfloat litF = texture2D(litTex, clamp(vLitUv, 0.0, 1.0)).r; reflectedLight.directDiffuse *= litF; reflectedLight.directSpecular *= litF;');
  };
  return m;
}
const mainU = { litTex: { value: null }, litOrigin: { value: new THREE.Vector2() }, litSize: { value: new THREE.Vector2(1, 1) } };
const ctxU = { litTex: { value: null }, litOrigin: { value: new THREE.Vector2() }, litSize: { value: new THREE.Vector2(1, 1) } };
const matPBR = makeTerrainMat(mainU), matCtx = makeTerrainMat(ctxU), matLayer = new THREE.MeshBasicMaterial({ vertexColors: true });
function maskTexture(u, data, cols, rows) {
  let t = u.litTex.value; if (!t || t.image.width !== cols || t.image.height !== rows) { t = new THREE.DataTexture(data, cols, rows, THREE.RedFormat, THREE.UnsignedByteType); t.minFilter = t.magFilter = THREE.LinearFilter; u.litTex.value = t; }
  else t.image.data.set(data); t.needsUpdate = true; return t;
}
function setLitTexture(mask) { const W = S.W, n = W.rows * W.cols, d = new Uint8Array(n); for (let i = 0; i < n; i++) d[i] = mask ? (mask[i] ? 255 : 0) : 255; maskTexture(mainU, d, W.cols, W.rows); mainU.litOrigin.value.set(-W.half_x, -W.half_y); mainU.litSize.value.set(2 * W.half_x, 2 * W.half_y); tintRocks(); }
// Cast shadows on a height grid by marching toward the Sun (row 0 = north, x east).
function shadowMask(h, R, C, sp, azDeg, elDeg) {
  const out = new Uint8Array(R * C), tanE = Math.tan(elDeg * DEG), dc = Math.sin(azDeg * DEG) / sp, dr = -Math.cos(azDeg * DEG) / sp, ds = []; for (let d = sp; d < 9000; d *= 1.22) ds.push(d);
  for (let r = 0; r < R; r++) for (let c = 0; c < C; c++) { const i = r * C + c, base = h[i]; let lit = 255;
    for (const d of ds) { const rr = Math.round(r + dr * d), cc = Math.round(c + dc * d); if (rr < 0 || cc < 0 || rr >= R || cc >= C) break; if ((h[rr * C + cc] - base) / d > tanE) { lit = 0; break; } } out[i] = lit; }
  return out;
}
// Fine regolith relief (VISUAL DETAIL, NOT DATA): tileable small craters + noise, as a mipmapped normal map.
const detailNormal = (() => {
  const N = 512, hgt = new Float32Array(N * N), rnd = (s) => { s = Math.sin(s * 12.9898) * 43758.5453; return s - Math.floor(s); };
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) hgt[y * N + x] = 0.35 * fbm(x / 9, y / 9) + 0.12 * fbm(x / 2.5, y / 2.5);
  for (let k = 0; k < 220; k++) { const cx = rnd(k + 1) * N, cy = rnd(k + 77) * N, rad = 3 + Math.pow(rnd(k + 33), 3) * 40, dep = 0.6 + rnd(k + 9) * 0.4;
    for (let y = -rad * 1.4; y <= rad * 1.4; y++) for (let x = -rad * 1.4; x <= rad * 1.4; x++) { const d = Math.hypot(x, y) / rad; if (d > 1.4) continue;
      const px = ((Math.round(cx + x) % N) + N) % N, py = ((Math.round(cy + y) % N) + N) % N; hgt[py * N + px] += d < 1 ? -dep * (1 - d * d) : 0.25 * dep * Math.exp(-(((d - 1) / 0.18) ** 2)); } }
  const c = document.createElement('canvas'); c.width = c.height = N; const g = c.getContext('2d'), img = g.createImageData(N, N);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) { const hx = hgt[y * N + ((x + 1) % N)] - hgt[y * N + ((x - 1 + N) % N)], hy = hgt[((y + 1) % N) * N + x] - hgt[((y - 1 + N) % N) * N + x];
    const nx = -hx * 2.2, ny = -hy * 2.2, nz = 1, l = Math.hypot(nx, ny, nz), p = 4 * (y * N + x); img.data[p] = (nx / l * 0.5 + 0.5) * 255; img.data[p + 1] = (ny / l * 0.5 + 0.5) * 255; img.data[p + 2] = (nz / l * 0.5 + 0.5) * 255; img.data[p + 3] = 255; }
  g.putImageData(img, 0, 0); const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; t.colorSpace = THREE.NoColorSpace; return t;
})();
function applyDetail() {
  for (const m of [matPBR, matCtx]) { m.normalMap = S.detail ? detailNormal : null; m.normalScale = new THREE.Vector2(0.9, 0.9); m.needsUpdate = true; }
  if (rocks) rocks.visible = S.detail && S.layer === 'terrain'; setBanner();
}
const siteObjs = [];

function gridGeometry(R, C, posFn, skipFn) {
  const g = new THREE.BufferGeometry(), pos = new Float32Array(R * C * 3), uv = new Float32Array(R * C * 2);
  const uv1 = new Float32Array(R * C * 2);
  for (let r = 0; r < R; r++) for (let c = 0; c < C; c++) { const i = r * C + c, p = posFn(r, c); pos.set(p, 3 * i); uv[2 * i] = p[0] / 40; uv[2 * i + 1] = p[2] / 40; uv1[2 * i] = c / (C - 1); uv1[2 * i + 1] = 1 - r / (R - 1); }
  const idx = []; for (let r = 0; r < R - 1; r++) for (let c = 0; c < C - 1; c++) { if (skipFn && skipFn(r, c)) continue; const a = r * C + c, b = a + 1, d = a + C, e = d + 1; idx.push(a, d, b, b, d, e); }
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('uv', new THREE.BufferAttribute(uv, 2)); g.setAttribute('uv1', new THREE.BufferAttribute(uv1, 2)); g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(R * C * 3), 3));
  g.setIndex(idx); g.computeVertexNormals(); return g;
}
const PHOTO_GAIN = 0.62; // albedo scale applied to the LROC mosaic (8-bit stretched brightness -> surface albedo)
function regolith(x, y, slope) { return 0.30 + 0.13 * fbm(x / 140, y / 140) + 0.06 * fbm(x / 22, y / 22) + 0.04 * Math.min(slope / 25, 1); }

function buildWorld() {
  const W = S.W, R = W.rows, C = W.cols;
  for (const o of [terrain, ctxMesh, rocks, landerS, roverS, plume, trailLine, pathLine, descentLine, sunDisc, earthS, sunLight, ambient]) if (o) sScene.remove(o);
  for (const o of siteObjs) sScene.remove(o.g); siteObjs.length = 0;
  if (terrainGeo) terrainGeo.dispose(); if (ctxGeo) { ctxGeo.dispose(); ctxGeo = null; ctxMesh = null; }
  terrainGeo = gridGeometry(R, C, (r, c) => [c * W.mpp - W.half_x, (W.height[r * C + c] - W.h0) * S.ex, r * W.mpp - W.half_y]);
  terrain = new THREE.Mesh(terrainGeo, matPBR); sScene.add(terrain);
  const photo = (url, m) => { if (!url) { m.map = null; m.needsUpdate = true; return; } const t = texLoader.load(url); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = renderer.capabilities.getMaxAnisotropy(); t.channel = 1; m.map = t; m.needsUpdate = true; };
  photo(W.photo?.tile, matPBR); photo(W.photo?.context, matCtx);
  if (W.ctx) { // real surrounding landscape (same NASA DEM, 20 m), with the main tile cut out
    const X = W.ctx, n = X.rows, m = X.cols, x0 = X.offset_x_m - (m - 1) / 2 * X.mpp, y0 = X.offset_y_m + (n - 1) / 2 * X.mpp;
    const inside = (r, c) => { const xa = x0 + c * X.mpp, ya = y0 - r * X.mpp, xb = xa + X.mpp, yb = ya - X.mpp; return xa > -W.half_x + 10 && xb < W.half_x - 10 && ya < W.half_y - 10 && yb > -W.half_y + 10; };
    ctxGeo = gridGeometry(n, m, (r, c) => [x0 + c * X.mpp, (X.height[r * m + c] - W.h0) * S.ex - 0.8, -(y0 - r * X.mpp)], inside);
    ctxMesh = new THREE.Mesh(ctxGeo, matCtx); sScene.add(ctxMesh); ctxU.litOrigin.value.set(x0, -y0); ctxU.litSize.value.set((m - 1) * X.mpp, (n - 1) * X.mpp); S.ctxAz = null;
  }
  sunLight = new THREE.DirectionalLight(0xffffff, 20); setLitTexture(null); ambient = new THREE.AmbientLight(0x23304a, 0.6);
  sScene.add(sunLight); sScene.add(sunLight.target); sScene.add(ambient);
  sunDisc = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 12), new THREE.MeshBasicMaterial({ color: 0xfff1c9 })); sScene.add(sunDisc);
  earthS = new THREE.Mesh(new THREE.SphereGeometry(1, 40, 20), new THREE.MeshStandardMaterial({ map: earthTex, roughness: 0.9, emissive: 0x0b1a33, emissiveIntensity: 0.5 })); sScene.add(earthS);

  // Rocks (VISUAL DETAIL, NOT DATA): power-law sizes, denser on slopes and crater rims.
  const rockGeo = new THREE.IcosahedronGeometry(1, 1); const rp = rockGeo.attributes.position; for (let i = 0; i < rp.count; i++) { const k = 0.75 + 0.5 * hash2(i, 7); rp.setXYZ(i, rp.getX(i) * k, rp.getY(i) * k * 0.7, rp.getZ(i) * k); } rockGeo.computeVertexNormals();
  const NR = 6000; rocks = new THREE.InstancedMesh(rockGeo, new THREE.MeshStandardMaterial({ roughness: 1, metalness: 0 }), NR); const M = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(); rocks.userData.cells = [];
  let placed = 0, tries = 0; while (placed < NR && tries < NR * 8) { tries++; const c = hash2(tries, 1) * (C - 1), r = hash2(tries, 2) * (R - 1), i = Math.round(r) * C + Math.round(c), sl = W.slope[i];
    if (hash2(tries, 3) > 0.25 + Math.min(sl / 18, 1) * 0.75) continue; const x = c * W.mpp - W.half_x, y = W.half_y - r * W.mpp, s = 0.12 + 1.3 * Math.pow(hash2(tries, 4), 4);
    e.set(hash2(tries, 5) * 6, hash2(tries, 6) * 6, hash2(tries, 8) * 6); q.setFromEuler(e); M.compose(new THREE.Vector3(x, groundY(x, y) + s * 0.25, -y), q, new THREE.Vector3(s, s, s)); rocks.setMatrixAt(placed, M); rocks.userData.cells.push(i); placed++; }
  rocks.count = placed; rocks.instanceMatrix.needsUpdate = true; sScene.add(rocks); tintRocks();

  landerS = vehicleObject('lander', 0xffc15a); landerS.visible = false; sScene.add(landerS);
  roverS = vehicleObject('rover', 0x6fd3ff); roverS.visible = false; sScene.add(roverS);
  plume = new THREE.Mesh(new THREE.ConeGeometry(0.9, 1, 20, 1, true), new THREE.MeshBasicMaterial({ color: 0xffc070, transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
  plume.geometry.translate(0, -0.5, 0); plume.visible = false; sScene.add(plume);
  for (const t of W.targets) {
    const g = new THREE.Group(); const ring = new THREE.Mesh(new THREE.RingGeometry(5, 6.6, 40), new THREE.MeshBasicMaterial({ color: 0xffb454, side: THREE.DoubleSide, transparent: true, opacity: 0.9, depthTest: false }));
    ring.rotation.x = -Math.PI / 2; ring.renderOrder = 7; g.add(ring);
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 60, 6), new THREE.MeshBasicMaterial({ color: 0xffb454, transparent: true, opacity: 0.4 })); beam.position.y = 30; g.add(beam);
    const tg = label(t.id, '#ffd596', 12); tg.position.y = 68; g.add(tg); sScene.add(g); siteObjs.push({ g, t, ring, beam });
  }
  placeSites();
  trailLine = lineObj(0x7ee08e, 9000, sScene); pathLine = lineObj(0x6fd3ff, 200, sScene, true); descentLine = lineObj(0xffc15a, 400, sScene, true);
  const span = Math.max(W.half_x, W.half_y);
  sCam.position.set(-span * 0.5, span * 0.35, span * 0.95); sCtl.target.set(0, 0, 0); sCtl.update();
  applyDetail(); applyStyle(S.style); recolor(); drawMini();
}
function tintRocks() { if (!rocks || !S.W) return; const c = new THREE.Color(), lit = S.lit; rocks.userData.cells.forEach((cell, k) => { const v = 0.24 + 0.1 * hash2(k, 11), on = !lit || lit[cell]; c.setRGB(on ? v : v * 0.06, on ? v * 0.98 : v * 0.06, on ? v * 0.95 : v * 0.07); rocks.setColorAt(k, c); }); if (rocks.instanceColor) rocks.instanceColor.needsUpdate = true; }
function updateContextShadows(f) {
  const W = S.W; if (!W?.ctx || !f?.sun) return; const az = f.sun.az_deg; if (S.ctxAz !== null && Math.abs(((az - S.ctxAz + 540) % 360) - 180) < 1) return; S.ctxAz = az;
  maskTexture(ctxU, shadowMask(W.ctx.height, W.ctx.rows, W.ctx.cols, W.ctx.mpp, az, f.sun.elev_deg), W.ctx.cols, W.ctx.rows);
}

function updateGeometry() { buildWorld(); }
function groundY(x, y) { // metres in the scene frame at tile position (x east, y north)
  const W = S.W; if (!W) return 0; const c = clamp((x + W.half_x) / W.mpp, 0, W.cols - 1.001), r = clamp((W.half_y - y) / W.mpp, 0, W.rows - 1.001);
  const c0 = Math.floor(c), r0 = Math.floor(r), fc = c - c0, fr = r - r0, h = W.height, C = W.cols;
  return ((h[r0 * C + c0] * (1 - fc) + h[r0 * C + c0 + 1] * fc) * (1 - fr) + (h[(r0 + 1) * C + c0] * (1 - fc) + h[(r0 + 1) * C + c0 + 1] * fc) * fr - W.h0) * S.ex;
}
function placeSites() { for (const o of siteObjs) o.g.position.set(o.t.x_m, groundY(o.t.x_m, o.t.y_m) + 0.4, -o.t.y_m); }

function recolor() {
  if (!terrainGeo) return; const W = S.W, R = W.rows, C = W.cols, N = terrainGeo.attributes.normal.array, col = terrainGeo.attributes.color.array;
  const layer = S.layer, lit = S.lit, lim = W.limits.slope_limit_deg, az = (S.last?.sun?.az_deg ?? 20) * DEG, el = 14 * DEG, fadeEdge = !W.ctx;
  const L = [Math.cos(el) * Math.sin(az), Math.sin(el), -Math.cos(el) * Math.cos(az)];
  terrain.material = layer === 'terrain' ? matPBR : matLayer; if (rocks) rocks.visible = S.detail && layer === 'terrain';
  for (let i = 0; i < R * C; i++) {
    const r = (i / C) | 0, c = i - r * C, x = c * W.mpp, y = r * W.mpp, slope = W.slope[i]; let out;
    if (layer === 'terrain') { let fd = 1; if (fadeEdge) { const edge = Math.min(x, y, (C - 1) * W.mpp - x, (R - 1) * W.mpp - y), f = clamp(edge / 220, 0, 1); fd = f * f * (3 - 2 * f); }
      const a = W.photo ? PHOTO_GAIN * fd : regolith(x, y, slope) * fd; out = [a, a, a * 0.985]; }
    else {
      const sh = clamp(N[3 * i] * L[0] + N[3 * i + 1] * L[1] + N[3 * i + 2] * L[2], 0, 1) * 0.75 + 0.25, isLit = lit ? lit[i] === 1 : true, psr = W.psr[i] === 1;
      if (layer === 'illum') out = isLit ? [1 * (0.4 + 0.6 * sh), 0.82 * (0.4 + 0.6 * sh), 0.42 * (0.4 + 0.6 * sh)] : [0.04, 0.08, 0.2 + 0.1 * sh];
      else if (layer === 'psr') out = psr ? [0.2, 0.5, 1].map((v) => v * (0.45 + 0.55 * sh)) : [0.5 * sh, 0.5 * sh, 0.52 * sh];
      else if (layer === 'ice') out = psr ? ramp(RAMP_ICE, W.ice[i] / 255).map((v) => v * (0.5 + 0.5 * sh)) : [0.3 * sh, 0.3 * sh, 0.32 * sh];
      else { const s = slope / lim; out = s >= 1 ? [0.95, 0.2, 0.25] : ramp(RAMP_HAZ, s).map((v) => v * (0.55 + 0.45 * sh)); }
    }
    col[3 * i] = out[0]; col[3 * i + 1] = out[1]; col[3 * i + 2] = out[2];
  }
  terrainGeo.attributes.color.needsUpdate = true;
  if (ctxGeo) { const X = W.ctx, n = X.rows, m = X.cols, cc = ctxGeo.attributes.color.array; for (let r = 0; r < n; r++) for (let c = 0; c < m; c++) { const i = r * m + c, edge = Math.min(r, c, n - 1 - r, m - 1 - c) * X.mpp, f = clamp(edge / 900, 0, 1), fd = f * f * (3 - 2 * f), a = (W.photo?.context ? PHOTO_GAIN : regolith(c * X.mpp, r * X.mpp, 8)) * fd * (layer === 'terrain' ? 1 : 0.45); cc.set([a, a, a * 0.985], 3 * i); } ctxGeo.attributes.color.needsUpdate = true; }
  drawMini(); drawLegend();
}

// ---------------------------------------------------------------- minimap + legend
const mini = $('mini'), mg = mini.getContext('2d'); let miniBase = null;
function drawMini() {
  const W = S.W; if (!W) return; const n = mini.width, step = W.cols / n, img = mg.createImageData(n, n);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const i = Math.floor(y * step) * W.cols + Math.floor(x * step), p = 4 * (y * n + x), isLit = S.lit ? S.lit[i] === 1 : true, psr = W.psr[i] === 1; let c;
    if (S.layer === 'ice') c = psr ? ramp(RAMP_ICE, W.ice[i] / 255) : [0.14, 0.14, 0.16];
    else if (S.layer === 'psr') c = psr ? [0.2, 0.5, 1] : [0.22, 0.22, 0.24];
    else if (S.layer === 'hazard') { const s = W.slope[i] / W.limits.slope_limit_deg; c = s >= 1 ? [0.95, 0.2, 0.25] : ramp(RAMP_HAZ, s); }
    else if (S.layer === 'illum') c = isLit ? [1, 0.82, 0.42] : [0.05, 0.09, 0.22];
    else { const hh = clamp((W.height[i] - W.hmin) / (W.hmax - W.hmin), 0, 1), k = (0.2 + 0.6 * hh) * (isLit ? 1 : 0.45); c = [k, k, k * 1.03]; }
    img.data[p] = c[0] * 255; img.data[p + 1] = c[1] * 255; img.data[p + 2] = c[2] * 255; img.data[p + 3] = 255;
  }
  miniBase = img; drawMiniOverlay();
}
function drawMiniOverlay() {
  const W = S.W; if (!W || !miniBase) return; mg.putImageData(miniBase, 0, 0); const n = mini.width, X = (x) => (x + W.half_x) / (2 * W.half_x) * n, Y = (y) => (W.half_y - y) / (2 * W.half_y) * n;
  mg.strokeStyle = '#7ee08e'; mg.lineWidth = 1.5; mg.beginPath(); S.trail.forEach((p, i) => (i ? mg.lineTo(X(p[0]), Y(p[1])) : mg.moveTo(X(p[0]), Y(p[1])))); mg.stroke();
  if (S.path && S.path.length) { mg.strokeStyle = '#6fd3ff'; mg.setLineDash([4, 3]); mg.beginPath(); S.path.forEach((p, i) => (i ? mg.lineTo(X(p[0]), Y(p[1])) : mg.moveTo(X(p[0]), Y(p[1])))); mg.stroke(); mg.setLineDash([]); }
  for (const t of W.targets) { const done = S.last?.targets?.find((q) => q.id === t.id)?.sampled; mg.strokeStyle = mg.fillStyle = done ? '#7ee08e' : '#ffb454'; mg.lineWidth = 2; mg.beginPath(); mg.arc(X(t.x_m), Y(t.y_m), 6, 0, 7); mg.stroke(); mg.font = '10px ui-monospace,monospace'; mg.fillText(t.id, X(t.x_m) + 8, Y(t.y_m) + 3); }
  const f = S.last; if (f?.pose) { const p = f.pose, x = X(p.x_m), y = Y(p.y_m); mg.save(); mg.translate(x, y); mg.rotate(p.heading_deg * DEG); mg.fillStyle = '#6fd3ff'; mg.strokeStyle = '#fff'; mg.lineWidth = 1.5; mg.beginPath(); mg.moveTo(0, -9); mg.lineTo(6, 7); mg.lineTo(-6, 7); mg.closePath(); mg.fill(); mg.stroke(); mg.restore(); }
  if (f?.lander && S.phaseNow === 'DESCENT') { mg.fillStyle = '#ffc15a'; mg.beginPath(); mg.arc(X(f.lander.x_m), Y(f.lander.y_m), 5, 0, 7); mg.fill(); }
  if (f?.sun) { const sa = f.sun.az_deg * DEG; mg.strokeStyle = '#ffd866'; mg.lineWidth = 2; mg.beginPath(); mg.moveTo(n - 28, 28); mg.lineTo(n - 28 + 18 * Math.sin(sa), 28 - 18 * Math.cos(sa)); mg.stroke(); mg.fillStyle = '#ffd866'; mg.fillText('Sun', n - 40, 54); }
}
function drawLegend() {
  const L = $('legend'), css = (st) => `linear-gradient(90deg, ${st.map((s) => `rgb(${s.map((v) => Math.round(v * 255)).join(',')})`).join(',')})`;
  const M = { illum: ['Illumination now: Sun above local horizon', css([[0.05, 0.09, 0.3], [1, 0.82, 0.42]]), 'shadow', 'lit'], psr: ['Permanently shadowed region (DEM-derived estimate)', css([[0.5, 0.5, 0.52], [0.2, 0.5, 1]]), 'sunlit terrain', 'PSR'],
    ice: ['Ice-evidence score inside PSR (modelled)', css(RAMP_ICE), 'weak', 'strong'], hazard: ['Slope vs rover limit', css([...RAMP_HAZ, [0.95, 0.2, 0.25]]), '0°', `${S.W?.limits.slope_limit_deg ?? 20}° (blocked)`] }[S.layer];
  L.style.display = M && S.scene === 'surf' ? 'block' : 'none'; if (M) L.innerHTML = `<div>${M[0]}</div><div class="ramp" style="background:${M[1]}"></div><div class="row"><span>${M[2]}</span><span>${M[3]}</span></div>`;
}

// ---------------------------------------------------------------- HUD
function log(t, kind, msg) {
  const li = document.createElement('li'), kk = ['abort', 'dead', 'sample', 'agent'].includes(kind) ? kind : (kind === 'decision' ? '' : 'event');
  li.innerHTML = `<time>${fmtMET(t).slice(3)}</time><span class="k ${kk}">${kind}</span><span></span>`; li.lastChild.textContent = msg; const ol = $('log'); ol.prepend(li); while (ol.children.length > 250) ol.lastChild.remove();
}
function renderSites(f) {
  const ul = $('sites'), W = S.W; if (!W || !f.targets) return;
  if (ul.children.length !== W.targets.length) { ul.innerHTML = ''; for (const t of W.targets) { const li = document.createElement('li'); li.dataset.id = t.id;
    li.innerHTML = `<b>${t.id}</b><div><div class="meter"><i style="width:${Math.round(t.ice_score * 100)}%"></i></div><small>score ${t.ice_score.toFixed(2)} · depth ${(t.depth_m ?? 0).toFixed(0)} m</small></div><span class="chip open">OPEN</span>`; ul.appendChild(li); } }
  for (const li of ul.children) { const t = f.targets.find((q) => q.id === li.dataset.id), chip = li.querySelector('.chip'), act = f.drill_target === li.dataset.id;
    if (t?.sampled) { chip.className = 'chip done'; chip.textContent = 'SAMPLED'; } else if (act) { chip.className = 'chip active'; chip.textContent = 'DRILLING'; } else { chip.className = 'chip open'; chip.textContent = 'OPEN'; } }
  const n = f.targets.filter((q) => q.sampled).length; $('w-sites').dataset.title = `Ice-evidence sites · ${n}/${W.targets.length} sampled`;
}
const spark = $('spark').getContext('2d');
function drawSpark() {
  const w = 280, h = 46, H = S.hist; spark.clearRect(0, 0, w, h); if (H.length < 2) return; spark.strokeStyle = '#2a3038'; for (const y of [12, 24, 36]) { spark.beginPath(); spark.moveTo(0, y); spark.lineTo(w, y); spark.stroke(); }
  const t0 = H[0][0], t1 = H[H.length - 1][0], X = (t) => (t - t0) / Math.max(t1 - t0, 1) * (w - 2) + 1; spark.strokeStyle = '#6fd3ff'; spark.fillStyle = '#6fd3ff22'; spark.lineWidth = 1.5; spark.beginPath();
  H.forEach((p, i) => (i ? spark.lineTo(X(p[0]), h - 3 - p[1] * (h - 6)) : spark.moveTo(X(p[0]), h - 3 - p[1] * (h - 6)))); spark.stroke(); spark.lineTo(w, h); spark.lineTo(0, h); spark.fill();
  spark.fillStyle = '#ffd866aa'; for (const p of H) if (p[2]) spark.fillRect(X(p[0]), 0, 1, 3);
}
function setPhase(f) {
  const last = S.phases[S.phases.length - 1]; if (last && last.phase === f.phase) return; S.phases.push({ t: f.t_s, phase: f.phase });
  const ol = $('timeline'), li = document.createElement('li'); li.innerHTML = `<b>${fmtShort(f.t_s)}</b>`; li.append(f.phase); ol.querySelectorAll('.cur').forEach((e) => e.classList.remove('cur')); li.classList.add('cur'); ol.prepend(li);
}
function kvs(pairs) { $('vehicle').innerHTML = pairs.map(([k, v]) => `<div><small>${k}</small><b>${v}</b></div>`).join(''); }
function renderModels(list) {
  const ul = $('models'); ul.innerHTML = ''; let att = 0;
  for (const m of list || []) { const cls = m.status === 'attached' ? 'attached' : m.status === 'fallback' ? 'fallback' : 'none'; if (cls === 'attached') att++;
    const li = document.createElement('li'), params = m.params ? ` · ${m.params >= 1e6 ? (m.params / 1e6).toFixed(1) + 'M' : Math.round(m.params / 1e3) + 'k'} params` : '';
    li.innerHTML = `<div><b></b><span class="kind"></span></div><span class="chip ${cls}"></span><small></small>`; li.querySelector('b').textContent = m.name; li.querySelector('.kind').textContent = m.kind;
    li.querySelector('.chip').textContent = m.status.toUpperCase(); li.querySelector('small').textContent = `${m.role}${params}${m.status === 'fallback' && m.fallback ? ' · using ' + m.fallback : ''}`; ul.appendChild(li); }
  $('w-stack').dataset.title = `AI stack · ${att}/${(list || []).length} attached`;
}

// ---------------------------------------------------------------- applying frames
function sceneFor(phase) { return phase === 'ORBIT' || phase === 'DEORBIT' ? 'orbit' : 'surf'; }
function applyFrame(f, light = false) {
  S.last = f; S.phaseNow = f.mission_phase || 'ROVER OPS'; S.scene = S.W ? sceneFor(S.phaseNow) : 'orbit';
  for (const e of f.events || []) log(e.t_s, e.kind, e.msg);
  if (f.pose) { const p = f.pose, tr = S.trail; if (!tr.length || Math.hypot(tr[tr.length - 1][0] - p.x_m, tr[tr.length - 1][1] - p.y_m) > 0.5) tr.push([p.x_m, p.y_m]); S.path = f.path || S.path; }
  if (f.orbit) { const o = f.orbit, v = llr(o.lat_deg, o.lon_deg, R_MOON + o.alt_km), tr = S.orbitTrail; if (!tr.length || tr[tr.length - 1].distanceTo(v) > 8) tr.push(v); }
  S.hist.push([f.t_s, f.battery_frac ?? 0, f.lit ? 1 : 0]); if (S.hist.length > 400) S.hist.shift(); setPhase(f);
  if (light) return;
  if (f.lit_bits_b64 && S.W) { const bits = b64(f.lit_bits_b64), n = S.W.rows * S.W.cols, m = new Uint8Array(n); for (let i = 0; i < n; i++) m[i] = (bits[i >> 3] >> (7 - (i & 7))) & 1; S.lit = m; setLitTexture(m); if (S.layer === 'illum') recolor(); }
  updateContextShadows(f);
  $('met').textContent = fmtMET(f.t_s); $('phase').textContent = f.phase || '—'; $('simclock').textContent = fmtSim(f.t_s);
  const c = $('control'), src = f.aborted ? 'SAFE MODE' : (f.control || '—').toUpperCase(); c.textContent = `CONTROL · ${src}`; c.className = 'badge ' + (f.aborted ? 'safe' : f.control === 'agent' ? 'ai' : f.control === 'operator' ? 'op' : 'base');
  for (const li of $('ribbon').children) { const order = ['ORBIT', 'DEORBIT', 'DESCENT', 'LANDED', 'ROVER OPS'], me = order.indexOf(li.dataset.p), now = order.indexOf(S.phaseNow); li.classList.toggle('on', me === now); li.classList.toggle('done', me < now); }
  if (f.battery_frac !== undefined) {
    $('batpct').textContent = `${(f.battery_frac * 100).toFixed(0)}%`; $('batwh').textContent = `${f.battery_wh.toFixed(0)} / ${S.W.limits.battery_capacity_wh} Wh`; const bb = $('batbar'); bb.style.width = `${f.battery_frac * 100}%`;
    bb.style.background = f.battery_frac < 0.25 ? 'var(--red)' : f.battery_frac < 0.5 ? 'var(--amber)' : 'var(--green)'; $('solar').textContent = `${f.solar_w.toFixed(0)} W`; $('load').textContent = `${f.load_w.toFixed(0)} W`;
    const net = f.solar_w - f.load_w; $('net').textContent = `${net >= 0 ? '+' : ''}${net.toFixed(0)} W`; $('net').style.color = net >= 0 ? 'var(--green)' : 'var(--amber)'; drawSpark();
  }
  if (f.orbit) { const o = f.orbit; kvs([['Altitude', `${o.alt_km.toFixed(1)} km`], ['Speed', `${o.speed_m_s.toFixed(0)} m/s`], ['Latitude', `${o.lat_deg.toFixed(1)}°`], ['Longitude', `${o.lon_deg.toFixed(1)}°`], ['Orbit no.', o.orbit_no ?? '—'], ['Model', 'Keplerian (modelled)']]); }
  else if (f.lander) { const l = f.lander; kvs([['Altitude', `${l.alt_m.toFixed(0)} m`], ['Vertical speed', `${l.vz_m_s.toFixed(1)} m/s`], ['Horizontal speed', `${Math.hypot(l.vx_m_s, l.vy_m_s).toFixed(1)} m/s`], ['Mass', `${l.mass_kg.toFixed(0)} kg`], ['Source', 'Basilisk telemetry']]); renderEngines(l); }
  else if (f.pose) { const p = f.pose; kvs([['Mode', f.mode.toUpperCase()], ['Speed', `${(f.speed_m_s * 100).toFixed(2)} cm/s`], ['Slope', `${f.slope_deg.toFixed(1)}°`], ['Heading', `${p.heading_deg.toFixed(0)}°`], ['Position E,N', `${p.x_m.toFixed(0)}, ${p.y_m.toFixed(0)} m`], ['Driven', `${f.distance_m.toFixed(0)} m`], ['Sun', f.lit ? 'LIT' : 'SHADOW'], ['Earth link', f.earth_visible ? 'UP' : 'DOWN'], ['In PSR', f.in_psr ? 'YES' : 'no'], ['Ice evidence here', f.ice_score.toFixed(2)]]); }
  if (f.targets) renderSites(f);
  drawMiniOverlay(); S.ready = true;
}
function renderEngines(l) {
  const el = $('engines'); if (!el.children.length) for (let i = 0; i < 5; i++) { const d = document.createElement('div'); d.innerHTML = `<span>E${i + 1}</span><i></i>`; el.appendChild(d); }
  const failed = [1, 3]; // Basilisk file: engine 1 failed, the opposite engine shut down for balance (engines_ok 5 -> 3)
  [...el.children].forEach((d, i) => { const off = l.engines_ok < 5 && failed.includes(i); d.classList.toggle('off', off); d.querySelector('i').style.height = off ? '4%' : `${clamp(l.thrust_n / (800 * Math.max(l.engines_ok, 1)) * 100, 3, 100)}%`; });
  $('thr').textContent = `${l.thrust_n.toFixed(0)} N`; $('fuel').textContent = `${l.fuel_kg.toFixed(0)} kg`; $('engok').textContent = `${l.engines_ok}/5`;
}

// ---------------------------------------------------------------- data sources
function loadWorld(m) {
  S.worldMsg = m;
  const h = new Float32Array(b64(m.height_f32).buffer); let lo = 1e9, hi = -1e9; for (const v of h) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const ctx = m.context ? { ...m.context, height: new Float32Array(b64(m.context.height_f32).buffer) } : null;
  S.W = { ...m, height: h, slope: b64(m.slope_u8), psr: b64(m.psr_u8), ice: b64(m.ice_u8), hazard: b64(m.hazard_u8), hmin: lo, hmax: hi, h0: (lo + hi) / 2, site: m.site || { lat_deg: -89.7, lon_deg: 0 }, ctx };
  if (Q.get('detail') === null) S.detail = !m.photo; setBanner();
  renderModels(m.models); S.lit = null; S.trail = []; S.phases = []; S.hist = []; S.orbitTrail = []; $('timeline').innerHTML = ''; $('log').innerHTML = ''; $('sites').innerHTML = ''; S.last = null; S.path = null;
  buildWorld(); frameOrbitCamera();
}
function setBanner() {
  const pv = S.W?.provenance || {}; $('banner').innerHTML = `<b>${(pv.terrain || 'PROVENANCE UNKNOWN').toUpperCase()}</b>Ice: ${pv.ice_evidence || 'unknown'} · Sun: ${pv.illumination || 'unknown'} · Rover: ${pv.rover || 'unknown'}`
    + (S.W?.photo ? ` · Surface photo: ${S.W.photo.provenance}` : '') + (S.detail ? ' · <b style="margin-left:6px">ROCKS AND FINE TEXTURE: VISUAL DETAIL, NOT DATA</b>' : '');
}
function notice(html) { const n = $('notice'); n.hidden = !html; n.innerHTML = html || ''; }
function setConn(kind, text) { const c = $('conn'); c.className = 'badge ' + kind; c.textContent = text; }
function renderModelsMsg(m) { renderModels(m.models); }

function startReplay(world, frames) {
  S.mode = 'replay'; loadWorld(world); S.frames = frames; S.idx = -1; S.T0 = frames[0]?.t_s ?? 0; S.T1 = frames[frames.length - 1]?.t_s ?? 1; S.simT = S.T0; S.playing = true;
  S.orbitPath = frames.filter((f) => f.orbit).map((f) => llr(f.orbit.lat_deg, f.orbit.lon_deg, R_MOON + f.orbit.alt_km)); setLineV(orbitPathLine, S.orbitPath);
  if (descentLine) { const y0 = groundY(S.W.start.x_m, S.W.start.y_m); setLineV(descentLine, frames.filter((f) => f.lander).map((f) => new THREE.Vector3(f.lander.x_m, y0 + f.lander.alt_m, -f.lander.y_m))); }
  setConn('replay', '● REPLAY · recorded run'); $('abort').disabled = true; $('override').disabled = true; $('play').textContent = '❚❚'; $('seek').disabled = false;
  const seek = Q.get('seek'); if (seek !== null && frames.length) { S.simT = S.T0 + (S.T1 - S.T0) * Number(seek); S.playing = false; $('play').textContent = '▶'; seekTo(S.simT); }
}
function advanceTo(t) { let moved = false; while (S.idx + 1 < S.frames.length && S.frames[S.idx + 1].t_s <= t) { S.idx++; applyFrame(S.frames[S.idx], S.idx + 1 < S.frames.length && S.frames[S.idx + 1].t_s <= t); moved = true; } return moved; }
function seekTo(t) {
  S.idx = -1; S.trail = []; S.phases = []; S.hist = []; S.orbitTrail = []; $('timeline').innerHTML = ''; $('log').innerHTML = ''; S.simT = t; advanceTo(t); $('seek').value = String(((t - S.T0) / Math.max(S.T1 - S.T0, 1)) * 1000); if (S.last) recolor();
}
async function tryReplay() {
  try {
    const [w, r] = await Promise.all([fetch('sample/world.json'), fetch('sample/run.jsonl')]); if (!w.ok || !r.ok) throw new Error('no sample');
    const world = await w.json(); const frames = (await r.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l)); notice(''); startReplay(world, frames);
  } catch (e) { setConn('off', '● NO BACKEND'); notice('<b>No backend connected.</b><br><br>Start one that speaks <code>lunar_ops/PROTOCOL.md</code>, for example<br><code>python -m lunar_ops.server</code><br>then reload. The UI connects to <code>/ws/ui</code> automatically.'); }
}
function connectLive(url) {
  return new Promise((resolve) => {
    let opened = false; const ws = new WebSocket(url); const to = setTimeout(() => { if (!opened) { ws.close(); resolve(false); } }, 1500);
    ws.onopen = () => { opened = true; clearTimeout(to); S.ws = ws; S.mode = 'live'; setConn('live', '● LIVE · backend'); notice(''); $('abort').disabled = false; $('override').disabled = false; $('seek').disabled = true; resolve(true); };
    ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.type === 'world') loadWorld(m); else if (m.type === 'frame' && S.W) applyFrame(m); else if (m.type === 'models') renderModelsMsg(m); else if (m.type === 'state') { S.playing = m.playing; $('play').textContent = m.playing ? '❚❚' : '▶'; } };
    ws.onerror = () => { if (!opened) resolve(false); };
    ws.onclose = () => { if (opened) { setConn('off', '● DISCONNECTED'); S.mode = 'none'; notice('<b>Backend disconnected.</b><br>Reload to reconnect.'); } };
  });
}
function send(o) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(o)); }

// ---------------------------------------------------------------- widgets (drag, minimise, close)
const widgets = [...document.querySelectorAll('.widget')];
let zTop = 40;
for (const w of widgets) {
  const x = document.createElement('div'); x.className = 'wx'; x.innerHTML = '<i title="Minimise">–</i><i title="Close">×</i>'; w.appendChild(x);
  x.children[0].onclick = () => { w.classList.toggle('min'); layoutAll(); }; x.children[1].onclick = () => { w.classList.add('hidden'); syncMenus(); };
  w.addEventListener('pointerdown', (e) => { w.style.zIndex = ++zTop; if (e.target === w || e.offsetY < 24) { w.setPointerCapture(e.pointerId); w.dataset.drag = `${e.clientX - w.offsetLeft},${e.clientY - w.offsetTop}`; w.dataset.moved = '1'; } });
  w.addEventListener('pointermove', (e) => { const d = w.dataset.drag; if (!d) return; const [dx, dy] = d.split(',').map(Number), v = $('view').getBoundingClientRect(); w.style.left = `${clamp(e.clientX - dx, 0, v.width - 60)}px`; w.style.top = `${clamp(e.clientY - dy, 0, v.height - 30)}px`; });
  w.addEventListener('pointerup', () => { delete w.dataset.drag; });
}
const LEFT = ['w-mission', 'w-vehicle', 'w-sites', 'w-stack'], RIGHT = ['w-engines', 'w-power', 'w-map', 'w-cam'];
function layoutAll() {
  const V = $('view').getBoundingClientRect(); const col = (ids, side) => { let y = 10; for (const id of ids) { const w = $(id); if (w.classList.contains('hidden')) continue; if (!w.dataset.moved) { w.style.top = `${y}px`; w.style[side] = '10px'; w.style[side === 'left' ? 'right' : 'left'] = 'auto'; } y += w.offsetHeight + 8; } };
  col(LEFT, 'left'); col(RIGHT, 'right'); const lg = $('w-log'); if (!lg.dataset.moved) { lg.style.left = `${Math.max(300, (V.width - 640) / 2)}px`; lg.style.bottom = '10px'; lg.style.top = 'auto'; }
}
function defaultWidgets() {
  for (const w of widgets) { delete w.dataset.moved; w.classList.remove('hidden', 'min'); }
  $('w-sites').classList.add('min'); $('w-stack').classList.add('min'); updatePhaseWidgets();
}
function updatePhaseWidgets() {
  const inOrbit = S.phaseNow === 'ORBIT' || S.phaseNow === 'DEORBIT', desc = S.phaseNow === 'DESCENT';
  $('w-engines').classList.toggle('hidden', !desc || S.userHidden?.engines); $('w-power').classList.toggle('hidden', inOrbit || desc || S.userHidden?.power);
  $('w-cam').classList.toggle('hidden', inOrbit || desc || S.userHidden?.cam); $('w-map').classList.toggle('hidden', inOrbit || S.userHidden?.map); $('w-sites').classList.toggle('hidden', inOrbit || desc);
  layoutAll();
}

// ---------------------------------------------------------------- menus
const MENUS = {
  File: () => [['Open recording (.jsonl)…', () => $('filepick').click()], ['Connect to backend…', () => { const u = prompt('WebSocket URL', `ws://${location.hostname || '127.0.0.1'}:8600/ws/ui`); if (u) connectLive(u); }], '-', ['Save screenshot', () => { const a = document.createElement('a'); a.download = 'mission-control.png'; a.href = canvas.toDataURL('image/png'); a.click(); }]],
  View: () => [...[['w-mission', 'Mission'], ['w-vehicle', 'Vehicle'], ['w-power', 'Power'], ['w-engines', 'Lander engines'], ['w-sites', 'Ice-evidence sites'], ['w-stack', 'AI stack'], ['w-map', 'Map'], ['w-cam', 'Rover camera'], ['w-log', 'Decision log']].map(([id, t]) => [t, () => { $(id).classList.toggle('hidden'); if (!$(id).classList.contains('hidden')) { S.userHidden = S.userHidden || {}; } layoutAll(); }, !$(id).classList.contains('hidden')]), '-', ...[['photo', 'Style: Photoreal'], ['cine', 'Style: Cinematic'], ['vizard', 'Style: Vizard (clean)']].map(([v, t]) => [t, () => applyStyle(v), S.style === v]), ['Visual detail (rocks, fine texture)', () => { S.detail = !S.detail; applyDetail(); }, S.detail], '-', ['Reset layout', defaultWidgets]],
  Time: () => [...[1, 60, 600, 3000, 12000].map((v) => [`${v}×`, () => setSpeed(v), S.speed === v]), '-', ['Restart', () => $('reset')?.click?.() ?? restart()]],
  Cameras: () => [['auto', 'Auto (cinematic, by phase)'], ['free', 'Free orbit'], ['chase', 'Chase vehicle'], ['top', 'Top-down (surface)'], ['rover', 'Rover camera (full screen)']].map(([v, t]) => [t, () => { S.cam = v; }, S.cam === v]),
  Layers: () => [['terrain', 'Terrain (lit)'], ['illum', 'Illumination'], ['psr', 'Shadow (PSR)'], ['ice', 'Ice evidence'], ['hazard', 'Hazard']].map(([v, t]) => [t, () => { S.layer = v; recolor(); }, S.layer === v]).concat(['-', ['Ice-evidence site markers', () => { S.show.sites = !S.show.sites; }, S.show.sites], ['Planned path', () => { S.show.path = !S.show.path; }, S.show.path], ['Rover trail', () => { S.show.trail = !S.show.trail; }, S.show.trail]]),
  Skybox: () => [['Stars', () => { S.show.stars = !S.show.stars; }, S.show.stars], ['Earth', () => { S.show.earth = !S.show.earth; }, S.show.earth], '-', ...[1, 2, 4].map((v) => [`Vertical exaggeration ×${v}`, () => { S.ex = v; if (S.W) { updateGeometry(); recolor(); placeSites(); } }, S.ex === v])],
};
function syncMenus() { /* menus are rebuilt on open */ }
function buildMenus() {
  const host = $('menus');
  for (const [name, items] of Object.entries(MENUS)) {
    const m = document.createElement('div'); m.className = 'menu'; m.innerHTML = `<span>${name}</span><div class="dd"></div>`; host.appendChild(m);
    m.onclick = (e) => { if (e.target.closest('.dd')) return; const open = m.classList.contains('open'); document.querySelectorAll('.menu.open').forEach((x) => x.classList.remove('open')); if (!open) { fill(m, items); m.classList.add('open'); } };
  }
  addEventListener('pointerdown', (e) => { if (!e.target.closest('.menu')) document.querySelectorAll('.menu.open').forEach((x) => x.classList.remove('open')); });
}
function fill(m, items) {
  const dd = m.querySelector('.dd'); dd.innerHTML = '';
  for (const it of items()) { if (it === '-') { dd.appendChild(document.createElement('hr')); continue; } const [t, fn, on] = it; const d = document.createElement('div'); d.textContent = t; if (on) d.classList.add('chk'); d.onclick = () => { fn(); m.classList.remove('open'); }; dd.appendChild(d); }
}
function setSpeed(v) { S.speed = v; $('speedlab').textContent = `${v >= 1000 ? v / 1000 + 'k' : v}×`; send({ type: 'cmd', cmd: 'speed', value: v }); }
function restart() { if (S.mode === 'replay') { seekTo(S.T0); } else send({ type: 'cmd', cmd: 'reset' }); }
const SPEEDS = [1, 60, 600, 3000, 12000];
$('step-back').onclick = () => setSpeed(SPEEDS[Math.max(0, SPEEDS.indexOf(S.speed) - 1)] ?? 600);
$('step-fwd').onclick = () => setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(S.speed) + 1)] ?? 3000);
$('play').onclick = () => { S.playing = !S.playing; $('play').textContent = S.playing ? '❚❚' : '▶'; send({ type: 'cmd', cmd: S.playing ? 'play' : 'pause' }); };
$('seek').oninput = (e) => { if (S.mode === 'replay') seekTo(S.T0 + (S.T1 - S.T0) * Number(e.target.value) / 1000); };
$('abort').onclick = () => { if (confirm('Latch SAFE MODE? The rover will stop and abandon any drill.')) send({ type: 'cmd', cmd: 'abort' }); };
$('override').onchange = (e) => { S.override = e.target.checked; send({ type: 'cmd', cmd: 'override', on: S.override }); };
$('filepick').onchange = async (e) => { const f = e.target.files[0]; if (!f || !S.W) return; const frames = (await f.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((m) => m.type === 'frame'); if (frames.length) startReplay(S.worldMsg, frames); };
addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target === document.body) { e.preventDefault(); $('play').click(); } S.keys[e.code] = true; }); addEventListener('keyup', (e) => { S.keys[e.code] = false; });
setInterval(() => { if (!S.override || S.mode !== 'live') return; const k = S.keys; send({ type: 'cmd', cmd: 'drive', v: k.KeyW ? 1 : 0, omega: (k.KeyD ? 1 : 0) - (k.KeyA ? 1 : 0) }); }, 200);

// ---------------------------------------------------------------- cameras + main loop
function frameOrbitCamera() {
  const site = S.W.site, n = llr(0, site.lon_deg + 90, 1); // face-on to the polar orbit plane
  oCam.position.copy(n.multiplyScalar(5600)).add(new THREE.Vector3(0, -1500, 0)); oCtl.target.set(0, 0, 0); oCtl.update();
  siteRing.position.copy(llr(site.lat_deg, site.lon_deg, R_MOON + 1)); siteRing.lookAt(siteRing.position.clone().multiplyScalar(2));
}
const orbitVeh = vehicleObject('lander', 0xffc15a); oScene.add(orbitVeh);
function resize() { const r = canvas.getBoundingClientRect(); renderer.setSize(r.width, r.height, false); composer.setSize(r.width, r.height); for (const c of [oCam, sCam]) { c.aspect = r.width / Math.max(r.height, 1); c.updateProjectionMatrix(); } layoutAll(); }
addEventListener('resize', resize);

function skyPlace(f) {
  const az = (f.sun?.az_deg ?? 20) * DEG, el = (f.sun?.elev_deg ?? 1.5) * DEG, d = 9000, dir = new THREE.Vector3(Math.cos(el) * Math.sin(az), Math.sin(el), -Math.cos(el) * Math.cos(az));
  if (sunLight) { sunLight.position.copy(dir.clone().multiplyScalar(5000)); sunLight.target.position.set(0, 0, 0); sunDisc.position.copy(dir.clone().multiplyScalar(d)); sunDisc.scale.setScalar(d * Math.tan(0.265 * DEG)); }
  const eaz = (S.W?.sky?.earth_azimuth_deg ?? 180) * DEG, eel = (f.earth_elev_deg ?? 0) * DEG; if (earthS) { earthS.position.set(d * Math.cos(eel) * Math.sin(eaz), d * Math.sin(eel), -d * Math.cos(eel) * Math.cos(eaz)); earthS.scale.setScalar(d * Math.tan(0.95 * DEG)); earthS.visible = S.show.earth; }
  oSun.position.set(Math.cos(az) * 1e5, 8e3, -Math.sin(az) * 1e5);
}
let tPrev = performance.now(), lastMode = '', lastCam = '', snap = false;
function frameLoop(now) {
  const dt = Math.min((now - tPrev) / 1000, 0.1); tPrev = now;
  if (S.mode === 'replay' && S.playing && S.frames.length) { S.simT += dt * S.speed; advanceTo(S.simT); if (S.idx >= S.frames.length - 1) { S.playing = false; $('play').textContent = '▶'; } $('seek').value = String(((S.simT - S.T0) / Math.max(S.T1 - S.T0, 1)) * 1000); }
  $('state').textContent = S.playing ? 'PLAYING' : 'PAUSED'; $('state').style.color = S.playing ? 'var(--green)' : 'var(--amber)'; $('speedlab').textContent = `${S.speed >= 1000 ? S.speed / 1000 + 'k' : S.speed}×`;
  const f = S.last, inOrbit = !S.W || S.scene === 'orbit'; if (lastMode !== S.phaseNow) { lastMode = S.phaseNow; snap = true; updatePhaseWidgets(); } if (lastCam !== S.cam) { lastCam = S.cam; snap = true; }
  const ka = snap ? 1 : 1 - Math.pow(0.02, dt);
  oStars.visible = sStars.visible = S.show.stars; earthO.visible = S.show.earth;
  const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setViewport(0, 0, w, h); renderer.setScissorTest(false);
  if (inOrbit) {
    let camName = 'LUNAR ORBIT · MODELLED (illustrative scale)';
    if (f?.orbit) { const o = f.orbit, v = llr(o.lat_deg, o.lon_deg, R_MOON + o.alt_km); orbitVeh.position.copy(v); scaleForView(orbitVeh, oCam.position, 0.07);
      const prev = S.orbitTrail.length > 2 ? S.orbitTrail[S.orbitTrail.length - 3] : null; if (prev) { orbitVeh.lookAt(v.clone().add(v.clone().sub(prev))); }
      setLineV(orbitTrailLine, S.orbitTrail); orbitVeh.visible = true; skyPlace(f);
      if (S.cam === 'auto' && S.phaseNow === 'DEORBIT') { // approach: camera sinks toward the landing site as the coast lowers the orbit
        const p = clamp((100 - o.alt_km) / 85, 0, 1), site = llr(S.W.site.lat_deg, S.W.site.lon_deg, R_MOON), up = site.clone().normalize(), side = new THREE.Vector3().crossVectors(up, new THREE.Vector3(0, 0, 1)).normalize();
        const cp = site.clone().add(up.clone().multiplyScalar(3400 * (1 - p) + 260)).add(side.multiplyScalar(2600 * (1 - p) + 180)); oCam.position.lerp(cp, ka); oCtl.target.lerp(site.clone().lerp(v, 0.35), ka); camName = 'APPROACH · LANDING SITE'; }
      if (S.cam === 'chase') { const radial = v.clone().normalize(), tang = prev ? v.clone().sub(prev).normalize() : new THREE.Vector3(1, 0, 0); oCam.position.lerp(v.clone().add(radial.multiplyScalar(260)).add(tang.multiplyScalar(-420)), ka); oCtl.target.lerp(v, ka); camName = 'CHASE · ORBIT'; } }
    siteRing.visible = true; const k = oCam.position.length() / 5000; siteRing.scale.setScalar(clamp(k, 0.5, 6));
    oCtl.update(); $('camlabel').textContent = camName; draw(oScene, oCam);
  } else {
    let name = 'SURFACE · ORBIT CAM';
    if (f && sunLight) { skyPlace(f); }
    const showLander = S.phaseNow === 'DESCENT' && f?.lander, showRover = f?.pose && S.phaseNow !== 'DESCENT';
    const landed = S.phaseNow === 'LANDED' || S.phaseNow === 'ROVER OPS';
    landerS.visible = !!showLander || landed; roverS.visible = !!showRover && !(S.cam === 'rover'); plume.visible = false;
    if (landed && !showLander) { const sx = S.W.start.x_m + 6, sy = S.W.start.y_m + 4; landerS.position.set(sx, groundY(sx, sy), -sy); scaleForView(landerS, sCam.position, 0.02); }
    if (showLander) { const l = f.lander, gy = groundY(l.x_m, l.y_m), y = groundY(S.W.start.x_m, S.W.start.y_m) + l.alt_m, p = new THREE.Vector3(l.x_m, y, -l.y_m); landerS.position.copy(p); scaleForView(landerS, sCam.position, 0.06);
      if (l.thrust_n > 0) { plume.visible = true; plume.position.copy(p); plume.scale.set(1 + l.thrust_n / 3000, 4 + l.thrust_n / 120, 1 + l.thrust_n / 3000); } void gy; }
    if (showRover) { const p = f.pose, rs = S.rs; if (Math.hypot(p.x_m - rs.x, -p.y_m - rs.z) > 25) { rs.x = p.x_m; rs.z = -p.y_m; rs.h = p.heading_deg * DEG; snap = true; } const k = 1 - Math.pow(0.001, dt); rs.x += (p.x_m - rs.x) * k; rs.z += (-p.y_m - rs.z) * k; let dh = ((p.heading_deg * DEG - rs.h + Math.PI) % (2 * Math.PI)) - Math.PI; if (dh < -Math.PI) dh += 2 * Math.PI; rs.h += dh * k;
      roverS.position.set(rs.x, groundY(rs.x, -rs.z), rs.z); roverS.rotation.y = -rs.h; scaleForView(roverS, sCam.position, 0.03); }
    const focus = showLander ? landerS.position : showRover ? roverS.position : null;
    if (S.cam === 'auto' && showRover && !showLander) { // drone view: high oblique, slowly circling the rover
      const a = now / 1000 * 0.03, R0 = 330, rp = roverS.position, cp = new THREE.Vector3(rp.x + Math.sin(a) * R0, 0, rp.z + Math.cos(a) * R0);
      cp.y = Math.max(rp.y + 170, groundY(cp.x, -cp.z) + 90); sCam.position.lerp(cp, ka); sCtl.target.lerp(rp.clone(), ka); name = 'DRONE VIEW · ROVER'; }
    else if (S.cam === 'auto' && showLander) { // descent: above and behind the lander, looking down onto the landing area
      const l = f.lander, lp = landerS.position, hv = new THREE.Vector3(l.vx_m_s, 0, -l.vy_m_s); if (hv.lengthSq() < 1) hv.set(1, 0, 0); hv.normalize();
      const cp = lp.clone().add(hv.multiplyScalar(-320)).add(new THREE.Vector3(0, 210, 0)); cp.y = Math.max(cp.y, groundY(cp.x, -cp.z) + 160);
      const gyl = groundY(l.x_m, l.y_m); sCam.position.lerp(cp, ka); sCtl.target.lerp(new THREE.Vector3(lp.x, gyl + (lp.y - gyl) * 0.35, lp.z), ka); name = 'DESCENT · TRAILING VIEW'; }
    else if (S.cam === 'chase') { if (focus) { const hd = showRover ? -S.rs.h : 0, b = showLander ? 140 : 26; const cp = focus.clone().add(new THREE.Vector3(Math.sin(hd) * b, b * 0.32 + 2, Math.cos(hd) * b + (showLander ? 80 : 0)));
        sCam.position.lerp(cp, ka); sCtl.target.lerp(focus, ka); name = showLander ? 'CHASE · LANDER' : 'CHASE · ROVER'; } }
    else if (S.cam === 'top' && focus) { sCam.position.lerp(new THREE.Vector3(focus.x, 1400, focus.z + 1), ka); sCtl.target.lerp(focus, ka); name = 'TOP-DOWN'; }
    sCtl.update();
    for (const o of siteObjs) { o.g.visible = S.show.sites; const d = sCam.position.distanceTo(o.g.position); o.g.scale.setScalar(clamp(d / 450, 0.6, 14));
      const done = f?.targets?.find((q) => q.id === o.t.id)?.sampled, act = f?.drill_target === o.t.id, c = done ? 0x7ee08e : act ? 0x6fd3ff : 0xffb454; o.ring.material.color.setHex(c); o.beam.material.color.setHex(c); }
    if (descentLine) descentLine.visible = S.phaseNow === 'DESCENT';
    if (trailLine) { trailLine.visible = S.show.trail; pathLine.visible = S.show.path; const pts = S.trail.map((q) => new THREE.Vector3(q[0], groundY(q[0], q[1]) + 0.7, -q[1])); setLineV(trailLine, pts); setLineV(pathLine, (S.path || []).map((q) => new THREE.Vector3(q[0], groundY(q[0], q[1]) + 0.9, -q[1]))); pathLine.computeLineDistances?.(); }
    if (S.cam === 'rover' && showRover) { rCam.aspect = w / h; rCam.updateProjectionMatrix(); const rp = roverS.position, hd = -S.rs.h; rCam.position.set(rp.x, rp.y + 1.3, rp.z); rCam.lookAt(rp.x - Math.sin(hd) * 20, rp.y + 0.8, rp.z - Math.cos(hd) * 20); draw(sScene, rCam); name = 'ROVER CAMERA'; }
    else draw(sScene, sCam);
    // picture-in-picture: onboard rover camera (rendered into the widget slot)
    const cw = $('w-cam'); if (showRover && !cw.classList.contains('hidden') && !cw.classList.contains('min') && S.cam !== 'rover') {
      const r = $('camslot').getBoundingClientRect(), v = canvas.getBoundingClientRect(), x = r.left - v.left, y = v.height - (r.bottom - v.top), ww = r.width, hh = r.height, rp = roverS.position, hd = -S.rs.h;
      rCam.aspect = ww / hh; rCam.updateProjectionMatrix(); rCam.position.set(rp.x, rp.y + 1.3, rp.z); rCam.lookAt(rp.x - Math.sin(hd) * 20, rp.y + 0.8, rp.z - Math.cos(hd) * 20);
      const sv = roverS.visible; roverS.visible = false; renderer.setScissorTest(true); renderer.setViewport(x, y, ww, hh); renderer.setScissor(x, y, ww, hh); renderer.render(sScene, rCam); renderer.setScissorTest(false); renderer.setViewport(0, 0, w, h); roverS.visible = sv;
      $('camhud').textContent = `RVR-CAM · ${f.lit ? 'SUN IN VIEW' : 'SHADOW'} · ${f.pose.heading_deg.toFixed(0)}°`; }
    $('camlabel').textContent = Q.get('debug') ? `${name} cam(${sCam.position.x.toFixed(0)},${sCam.position.y.toFixed(0)},${sCam.position.z.toFixed(0)}) rover(${roverS.position.x.toFixed(0)},${roverS.position.y.toFixed(0)},${roverS.position.z.toFixed(0)}) vis=${roverS.visible} sc=${roverS.scale.x.toFixed(1)} tgt(${sCtl.target.x.toFixed(0)},${sCtl.target.y.toFixed(0)},${sCtl.target.z.toFixed(0)})` : name;
  }
  snap = false; requestAnimationFrame(frameLoop);
}

// ---------------------------------------------------------------- boot
buildMenus(); defaultWidgets(); resize(); drawLegend(); requestAnimationFrame(frameLoop);
(async () => {
  const explicit = Q.get('ws'), auto = location.protocol.startsWith('http') ? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/ui` : null, url = explicit || (Q.get('replay') ? null : auto);
  if (url && await connectLive(url)) return; await tryReplay();
})();
window.__lunar = { S, applyFrame, THREE };
