// Copyright (c) 2026, Adinfinitium team. ISC-style permission notice as in index.html.
// Adinfinitium mission showcase: one calm, cinematic film from lunar orbit to the rover on the surface.
// Data: the recorded run (orbit, Basilisk descent telemetry, rover traverse) and the LOLA tile from lunar_ops/ui/sample,
// ghost runs from /api/ghosts. Everything shown is MODELLED (simulated) except the terrain and the site image (observed).
import * as THREE from 'three';
import { GLTFLoader } from './vendor/GLTFLoader.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { EffectComposer } from './vendor/EffectComposer.js';
import { RenderPass } from './vendor/RenderPass.js';
import { UnrealBloomPass } from './vendor/UnrealBloomPass.js';
import { OutputPass } from './vendor/OutputPass.js';
import { ShaderPass } from './vendor/ShaderPass.js';

const $ = (id) => document.getElementById(id), Q = new URLSearchParams(location.search);
const DEG = Math.PI / 180, R_MOON = 1737.4e3; // [m] mean lunar radius
const EARTH_R = 6371e3, EARTH_D = 384400e3; // [m] Earth radius, mean Earth-Moon distance
const DOCK_Y = 1.663; // [m] lander origin above the propulsion-module origin when docked (from the two models)
const LANDER_FEET = 1.45, ROVER_WHEELS = 0.219; // [m] model origin height above the ground contact
const clamp = (v, a, b) => Math.min(b, Math.max(a, v)), lerp = (a, b, t) => a + (b - a) * t, smooth = (t) => t * t * (3 - 2 * t);
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const win = (u, a, b, f = 0.08) => smooth(clamp((u - a) / f, 0, 1)) * smooth(clamp((b - u) / f, 0, 1)); // soft on/off window

// ------------------------------------------------------------------------------------------------ renderer
const canvas = $('gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, logarithmicDepthBuffer: true, powerPreference: 'high-performance' });
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
const camera = new THREE.PerspectiveCamera(36, 1, 0.05, 3e9);
const controls = new OrbitControls(camera, canvas); controls.enableDamping = true; controls.dampingFactor = 0.07; controls.enabled = false;
const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 })), renderPass = new RenderPass(null, camera); // 4x MSAA: clean edges
const bloom = new UnrealBloomPass(new THREE.Vector2(512, 512), 0.5, 0.6, 0.9);
// Film grade: gentle vignette, cool shadows / warm highlights and fine animated grain, applied after tone mapping.
const grade = new ShaderPass({ uniforms: { tDiffuse: { value: null }, uTime: { value: 0 }, uRes: { value: new THREE.Vector2(1, 1) } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `uniform sampler2D tDiffuse; uniform float uTime; uniform vec2 uRes; varying vec2 vUv;
    float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
    void main(){ vec3 c = texture2D(tDiffuse, vUv).rgb; float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
      c = mix(c * vec3(0.94, 0.98, 1.06), c * vec3(1.04, 1.0, 0.95), smoothstep(0.15, 0.8, l)); // cool shadows, warm highlights
      vec2 q = vUv - 0.5; q.x *= uRes.x / uRes.y; c *= 1.0 - 0.32 * smoothstep(0.35, 1.05, length(q)); // vignette
      c += (h(vUv * uRes + fract(uTime) * 91.7) - 0.5) * 0.022; // fine grain
      gl_FragColor = vec4(c, 1.0); }` });
composer.addPass(renderPass); composer.addPass(bloom); composer.addPass(new OutputPass()); composer.addPass(grade);
const S = { quality: Q.get('quality') || 'high', cam: 'cine', playing: true, T: 0, zoom: 1, labels: true, ready: false, chapter: -1 };
function resize() {
  const dpr = window.devicePixelRatio || 1, pr = S.quality === 'ultra' ? Math.min(dpr * 1.5, 3) : Math.min(dpr, 2);
  renderer.setPixelRatio(pr); renderer.setSize(innerWidth, innerHeight, false); composer.setPixelRatio(pr); composer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); grade.uniforms.uRes.value.set(innerWidth * pr, innerHeight * pr);
}
addEventListener('resize', resize);

// ------------------------------------------------------------------------------------------------ shared look
function envMap() { // soft studio reflections so metal and foil read well; not a light source in the story
  const pm = new THREE.PMREMGenerator(renderer), env = new THREE.Scene(); env.background = new THREE.Color(0x05080f);
  const panel = (c, k, p, s) => { const m = new THREE.Mesh(new THREE.BoxGeometry(...s), new THREE.MeshBasicMaterial({ color: new THREE.Color(c).multiplyScalar(k) })); m.position.set(...p); env.add(m); };
  panel(0xffffff, 7, [6, 4, 3], [2, 2, 0.2]); panel(0x4d7dff, 2.5, [-6, 2, -3], [2, 3, 0.2]); panel(0xffa566, 1.4, [0, -5, 6], [3, 0.2, 2]); panel(0x8db9ff, 1.2, [0, 7, 0], [4, 0.2, 4]);
  return pm.fromScene(env, 0.04).texture;
}
const ENV = envMap();
function radial(stops, size = 256) {
  const c = document.createElement('canvas'); c.width = c.height = size; const g = c.getContext('2d'), gr = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [o, col] of stops) gr.addColorStop(o, col); g.fillStyle = gr; g.fillRect(0, 0, size, size); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const GLOW = radial([[0, 'rgba(255,255,255,1)'], [0.15, 'rgba(255,236,190,.9)'], [0.4, 'rgba(255,170,90,.35)'], [1, 'rgba(255,120,40,0)']]);
const SUNGLOW = radial([[0, 'rgba(255,255,255,1)'], [0.08, 'rgba(255,248,230,1)'], [0.25, 'rgba(255,230,190,.35)'], [1, 'rgba(255,210,160,0)']]);
const PUFF = radial([[0, 'rgba(255,255,255,.9)'], [0.5, 'rgba(220,230,255,.35)'], [1, 'rgba(200,210,240,0)']], 128);
const DUST = radial([[0, 'rgba(190,180,165,.75)'], [0.6, 'rgba(160,150,140,.25)'], [1, 'rgba(140,130,120,0)']], 128);
function stars(scene) {
  const n = 9000, p = new Float32Array(n * 3), col = new Float32Array(n * 3), v = new THREE.Vector3();
  for (let i = 0; i < n; i++) { v.randomDirection().multiplyScalar(1.5e9); p.set([v.x, v.y, v.z], i * 3); const k = 0.35 + 0.65 * Math.pow(Math.random(), 3), w = Math.random(); col.set([k * (0.85 + 0.15 * w), k * 0.9, k * (0.95 + 0.05 * (1 - w))], i * 3); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(p, 3)); g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const pts = new THREE.Points(g, new THREE.PointsMaterial({ size: 1.6, sizeAttenuation: false, vertexColors: true, depthWrite: false, fog: false })); pts.frustumCulled = false; scene.add(pts); return pts;
}
function earthTexture() {
  const c = document.createElement('canvas'); c.width = 1024; c.height = 512; const g = c.getContext('2d'); g.fillStyle = '#0d2c5c'; g.fillRect(0, 0, 1024, 512);
  const blob = (x, y, r, col, a) => { g.globalAlpha = a; g.fillStyle = col; g.beginPath(); g.ellipse(x, y, r, r * (0.5 + Math.random() * 0.5), Math.random() * 3, 0, 7); g.fill(); };
  for (let i = 0; i < 140; i++) blob(Math.random() * 1024, 90 + Math.random() * 330, 10 + Math.random() * 60, ['#3d5a2b', '#6b5a3a', '#4c6b33'][i % 3], 0.85);
  for (let i = 0; i < 260; i++) blob(Math.random() * 1024, Math.random() * 512, 6 + Math.random() * 40, '#ffffff', 0.18 + Math.random() * 0.25);
  g.globalAlpha = 1; g.fillStyle = '#e8eef6'; g.fillRect(0, 0, 1024, 26); g.fillRect(0, 486, 1024, 26); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const EARTH_TEX = earthTexture();
function addEarth(scene, dir) {
  const e = new THREE.Mesh(new THREE.SphereGeometry(EARTH_R, 64, 32), new THREE.MeshStandardMaterial({ map: EARTH_TEX, roughness: 0.85, metalness: 0, emissive: 0x0a1630, emissiveIntensity: 0.25, fog: false }));
  e.add(new THREE.Mesh(new THREE.SphereGeometry(EARTH_R * 1.04, 64, 32), new THREE.MeshBasicMaterial({ color: 0x5f9bff, transparent: true, opacity: 0.18, side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false, fog: false })));
  e.userData.dir = dir.clone().normalize(); e.position.copy(e.userData.dir).multiplyScalar(EARTH_D); e.rotation.z = 0.4; scene.add(e); return e;
}
function addSun(scene, dir) {
  const light = new THREE.DirectionalLight(0xfff3e2, 3.6); light.castShadow = true; light.shadow.mapSize.set(4096, 4096); light.shadow.bias = -0.0002; light.shadow.normalBias = 0.02;
  const sc = light.shadow.camera; sc.left = -40; sc.right = 40; sc.top = 40; sc.bottom = -40; sc.near = 1; sc.far = 4000;
  scene.add(light, light.target); const disc = new THREE.Sprite(new THREE.SpriteMaterial({ map: SUNGLOW, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, fog: false }));
  disc.scale.setScalar(9e7); scene.add(disc); const sun = { light, disc, dir: dir.clone().normalize() };
  sun.place = (focus, dist = 900, span = 40) => { light.position.copy(focus).addScaledVector(sun.dir, dist); light.target.position.copy(focus); disc.position.copy(focus).addScaledVector(sun.dir, 1.2e9);
    if (sc.right !== span) { sc.left = -span; sc.right = span; sc.top = span; sc.bottom = -span; sc.updateProjectionMatrix(); } };
  return sun;
}

// ------------------------------------------------------------------------------------------------ engine fire
// A plume is two nested cones with a flickering additive shader, a glow sprite at the exit and an orange point light.
const plumeVS = `varying vec2 vUv; varying vec3 vN; varying vec3 vV;
  void main(){ vUv = uv; vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position, 1.0); vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`;
const plumeFS = `uniform float uTime; uniform float uPower; uniform float uAlpha; uniform float uSeed; uniform vec3 uHot; uniform vec3 uMid; uniform vec3 uTail;
  varying vec2 vUv; varying vec3 vN; varying vec3 vV;
  float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f); return mix(mix(h(i), h(i + vec2(1, 0)), f.x), mix(h(i + vec2(0, 1)), h(i + vec2(1, 1)), f.x), f.y); }
  void main(){
    float along = vUv.y;                                   // 1 at the nozzle exit, 0 at the tail
    float facing = pow(abs(dot(normalize(vN), normalize(vV))), 1.8); // soft edges: no hard silhouette
    float flick = 0.82 + 0.18 * n(vec2(vUv.x * 7.0 + uSeed, along * 5.0 - uTime * 11.0));
    float a = pow(along, 2.0) * facing * flick * uPower * uAlpha;
    vec3 c = mix(uTail, uMid, smoothstep(0.0, 0.55, along)); c = mix(c, uHot, smoothstep(0.7, 1.0, along));
    gl_FragColor = vec4(c * a, a); }`;
const gw = new THREE.Vector3();
function makeEngine(bellInner) { // placed at a nozzle exit; the fire grows along local -Y
  const g = new THREE.Group(), mats = [];
  // [radius at exit, radius at tail, length, alpha, hot, mid, tail colour]
  for (const [r0, r1, len, al, hot, mid, tail] of [[0.12, 0.2, 0.9, 0.9, 0xfffaf0, 0xffd29a, 0xff9a50], [0.17, 1.15, 3.6, 0.2, 0xffe2b8, 0xffa864, 0x6f86ff]]) {
    const geo = new THREE.CylinderGeometry(r0, r1, len, 40, 10, true); geo.translate(0, -len / 2, 0);
    const m = new THREE.ShaderMaterial({ vertexShader: plumeVS, fragmentShader: plumeFS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      uniforms: { uTime: { value: 0 }, uPower: { value: 1 }, uAlpha: { value: al }, uSeed: { value: Math.random() * 10 }, uHot: { value: new THREE.Color(hot) }, uMid: { value: new THREE.Color(mid) }, uTail: { value: new THREE.Color(tail) } } });
    const mesh = new THREE.Mesh(geo, m); mesh.frustumCulled = false; mesh.renderOrder = 5; g.add(mesh); mats.push(m);
  }
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: 0xffe0b0, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true })); glow.position.y = -0.05; g.add(glow);
  const light = new THREE.PointLight(0xffb070, 0, 45, 1.8); light.position.y = -0.5; g.add(light);
  if (bellInner) { bellInner.material = bellInner.material.clone(); bellInner.material.emissive = new THREE.Color(0xff6a20); }
  g.level = 0; // smoothed throttle so engines spool up and down instead of snapping
  g.set = (p, t, dt = 0.016) => { g.level += (clamp(p, 0, 1.3) - g.level) * clamp(dt * 5, 0, 1); const k = g.level; g.visible = k > 0.01;
    for (const m of mats) { m.uniforms.uPower.value = k; m.uniforms.uTime.value = t; }
    g.scale.set(1 + 0.12 * k, 0.65 + 0.55 * k, 1 + 0.12 * k); g.getWorldPosition(gw); const far = gw.distanceTo(camera.position) * 0.006; // keeps the flame readable from far away
    glow.material.opacity = 0.7 * clamp(k, 0, 1); glow.scale.setScalar(Math.max(0.45 + 0.25 * k, far * k) * (0.95 + 0.05 * Math.sin(t * 37)));
    light.intensity = 4.5 * k; if (bellInner) bellInner.material.emissiveIntensity = 1.3 * k; };
  return g;
}
function makePuffs(scene, n = 120, tex = PUFF, size = 0.5) { // small CPU particle pool (thruster puffs, landing dust)
  const geo = new THREE.BufferGeometry(), pos = new Float32Array(n * 3); geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({ map: tex, size, sizeAttenuation: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.8 });
  const pts = new THREE.Points(geo, mat); pts.frustumCulled = false; scene.add(pts); const P = Array.from({ length: n }, () => ({ p: new THREE.Vector3(), v: new THREE.Vector3(), life: 0 }));
  return { pts, mat, emit(origin, vel, spread, life = 1) { const q = P.find((x) => x.life <= 0); if (!q) return; q.p.copy(origin); q.v.copy(vel).add(new THREE.Vector3((Math.random() - 0.5) * spread, (Math.random() - 0.5) * spread, (Math.random() - 0.5) * spread)); q.life = life * (0.6 + 0.4 * Math.random()); },
    step(dt, drag = 0.4) { let k = 0; for (const q of P) { if (q.life > 0) { q.life -= dt; q.v.multiplyScalar(1 - drag * dt); q.p.addScaledVector(q.v, dt); } pos.set(q.life > 0 ? [q.p.x, q.p.y, q.p.z] : [0, -1e9, 0], k * 3); k++; } geo.attributes.position.needsUpdate = true; } };
}

// ------------------------------------------------------------------------------------------------ data
let BASE = '../';
async function getJSON(paths) { for (const p of paths) { try { const r = await fetch(p); if (r.ok) { BASE = p.replace(/sample\/.*$/, ''); return r; } } catch (e) { /* try next */ } } throw new Error('mission data not found'); }
function b64f32(s) { const bin = atob(s), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return new Float32Array(a.buffer); }
function series(frames, pick) { // linear interpolation of numeric fields over t_s
  const T = frames.map((f) => f.t_s), V = frames.map(pick);
  return (t) => { if (t <= T[0]) return V[0]; const n = T.length - 1; if (t >= T[n]) return V[n]; let lo = 0, hi = n; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (T[m] <= t) lo = m; else hi = m; } const u = (t - T[lo]) / ((T[hi] - T[lo]) || 1);
    const a = V[lo], b = V[hi], o = {}; for (const k in a) o[k] = typeof a[k] === 'number' && typeof b[k] === 'number' ? lerp(a[k], b[k], u) : (u < 0.5 ? a[k] : b[k]); return o; };
}
const loader = new GLTFLoader();
const loadModel = (n) => loader.loadAsync(`models/${n}_B.glb`).then((g) => { g.scene.traverse((m) => { if (m.isMesh) { m.castShadow = true; m.receiveShadow = true; if (m.material) m.material.envMapIntensity = 0.55; } }); return g.scene; });
function nozzles(model, re) { // exit points (bottom centre) of the parts whose names match re, in the model's own frame
  model.updateMatrixWorld(true); const out = []; model.traverse((o) => { if (o.isMesh && re.test(o.name)) { const b = new THREE.Box3().setFromObject(o), c = b.getCenter(new THREE.Vector3()); out.push({ name: o.name, p: model.worldToLocal(new THREE.Vector3(c.x, b.min.y, c.z)) }); } });
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

// ------------------------------------------------------------------------------------------------ scenes
const orbit = new THREE.Scene(), surf = new THREE.Scene(); orbit.environment = ENV; surf.environment = ENV; orbit.environmentIntensity = 0.35; surf.environmentIntensity = 0.3;
stars(orbit); stars(surf);
const TL = new THREE.TextureLoader();
const tex = (url, srgb = true) => { const t = TL.load(url); if (srgb) t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 16; return t; };
let W, frames, OB, DS, RV, models = {}, ghostFiles = [];
const moonGroup = new THREE.Group(); orbit.add(moonGroup);
const orbitSun = addSun(orbit, new THREE.Vector3(0.62, -0.3, 0.72)), orbitEarth = addEarth(orbit, new THREE.Vector3(-0.35, 0.2, -0.92));
orbit.add(new THREE.HemisphereLight(0x8fb0ff, 0x1a120a, 0.15));
const stack = new THREE.Group(), pmHolder = new THREE.Group(), landerOrbit = new THREE.Group(); orbit.add(stack, pmHolder, landerOrbit);
let surfSun, hRef = 0;
const landerSurf = new THREE.Group(), roverG = new THREE.Group(); surf.add(landerSurf, roverG);
const fx = { orbitEngines: [], pmEngine: null, rcs: null, descent: [], dust: null };

function llr(lat, lon, r) { const la = lat * DEG, lo = lon * DEG; return new THREE.Vector3(r * Math.cos(la) * Math.cos(lo), r * Math.sin(la), -r * Math.cos(la) * Math.sin(lo)); }
// Moon material: looks the equirectangular map up per pixel from the surface direction, so the poles (where we fly)
// do not pinch or smear the way a sphere's own texture coordinates do.
// Near the south pole the Moon also samples the LROC WAC south-pole mosaic (polar stereographic, observed), which is
// about 11x sharper there than the global map; it blends into the global map between 70 and 72 degrees south.
const POLAR = { tex: null, half: 0, on: { value: 0 } };
function moonMaterial(map) {
  const m = new THREE.MeshStandardMaterial({ map, roughness: 1, metalness: 0, color: new THREE.Color(1.2, 1.2, 1.2) });
  m.onBeforeCompile = (sh) => {
    sh.uniforms.polarMap = { value: POLAR.tex }; sh.uniforms.polarHalf = { value: POLAR.half }; sh.uniforms.polarOn = POLAR.on; sh.uniforms.moonR = { value: R_MOON };
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vMoonP; varying vec3 vMoonW;').replace('#include <begin_vertex>', '#include <begin_vertex>\nvMoonP = position; vMoonW = (modelMatrix * vec4(position, 1.0)).xyz;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', `#include <common>
varying vec3 vMoonP; varying vec3 vMoonW;
uniform sampler2D polarMap; uniform float polarHalf; uniform float polarOn; uniform float moonR;
float mh(vec3 p){ return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
float mn(vec3 p){ vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(mh(i), mh(i + vec3(1,0,0)), f.x), mix(mh(i + vec3(0,1,0)), mh(i + vec3(1,1,0)), f.x), f.y), mix(mix(mh(i + vec3(0,0,1)), mh(i + vec3(1,0,1)), f.x), mix(mh(i + vec3(0,1,1)), mh(i + vec3(1,1,1)), f.x), f.y), f.z); }`).replace('#include <map_fragment>', `
      vec3 qm = normalize(vMoonP); float um = atan(qm.z, -qm.x) / 6.28318530718; float uA = fract(um);
      vec2 uvm = vec2(uA, 1.0 - acos(clamp(qm.y, -1.0, 1.0)) / 3.14159265359);
      vec2 dA = vec2(dFdx(uA), dFdy(uA)), dB = vec2(dFdx(um), dFdy(um)); vec2 du = (abs(dA.x) + abs(dA.y) < abs(dB.x) + abs(dB.y)) ? dA : dB;
      vec4 sampledDiffuseColor = textureGrad(map, uvm, vec2(du.x, dFdx(uvm.y)), vec2(du.y, dFdy(uvm.y)));
      if (polarOn > 0.5 && qm.y < -0.92) { // south of ~67 deg S: polar stereographic lookup, x = rho sin(lon), y = rho cos(lon)
        float colat = acos(clamp(-qm.y, -1.0, 1.0)), rho = 2.0 * moonR * tan(colat * 0.5), lonm = atan(-qm.z, qm.x);
        vec2 uvp = vec2(0.5 + rho * sin(lonm) / (2.0 * polarHalf), 0.5 + rho * cos(lonm) / (2.0 * polarHalf));
        float wP = smoothstep(-0.9397, -0.9659, qm.y); // blends in from 70 to 75 deg S
        vec4 pc = texture2D(polarMap, uvp); sampledDiffuseColor = mix(sampledDiffuseColor, vec4(pc.rgb * 1.08, 1.0), wP); }
      diffuseColor *= sampledDiffuseColor;
      // fine surface variation below the map's ~2.7 km pixels, faded in only up close: VISUAL DETAIL, NOT DATA
      float near = 1.0 - smoothstep(4.0e5, 1.5e6, length(vMoonW - cameraPosition));
      vec3 pd = vMoonP / 2500.0; float dn = mn(pd) * 0.5 + mn(pd * 3.1) * 0.3 + mn(pd * 9.7) * 0.2;
      diffuseColor.rgb *= mix(1.0, 0.82 + 0.36 * dn, near);`);
  };
  return m;
}
function gridGeometry(R, C, pos, uv, skip) {
  const p = new Float32Array(R * C * 3), t = new Float32Array(R * C * 2), idx = [];
  for (let r = 0; r < R; r++) for (let c = 0; c < C; c++) { const k = r * C + c; p.set(pos(r, c), k * 3); t.set(uv(r, c), k * 2); }
  for (let r = 0; r < R - 1; r++) for (let c = 0; c < C - 1; c++) { if (skip && skip(r, c)) continue; const a = r * C + c, b = a + 1, d = a + C, e = d + 1; idx.push(a, d, b, b, d, e); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(p, 3)); g.setAttribute('uv', new THREE.BufferAttribute(t, 2)); g.setIndex(idx); g.computeVertexNormals(); return g;
}
function heightAt(x, y) { const c = clamp((x + W.half_x) / W.mpp, 0, W.cols - 1.001), r = clamp((W.half_y - y) / W.mpp, 0, W.rows - 1.001), c0 = Math.floor(c), r0 = Math.floor(r), fc = c - c0, fr = r - r0, H = W.height, C = W.cols;
  return lerp(lerp(H[r0 * C + c0], H[r0 * C + c0 + 1], fc), lerp(H[(r0 + 1) * C + c0], H[(r0 + 1) * C + c0 + 1], fc), fr) - hRef; }
const groundY = (x, y) => heightAt(x, y);
const toScene = (x, y, h) => new THREE.Vector3(x, h, -y); // tile frame (x east, y north) to scene (y up, -z north)
function groundNormal(x, y) { const e = 3, dx = (groundY(x + e, y) - groundY(x - e, y)) / (2 * e), dy = (groundY(x, y + e) - groundY(x, y - e)) / (2 * e); return new THREE.Vector3(-dx, 1, dy).normalize(); }

const marks = []; let trail, descentLine;
// Rover bay and deploy ramp are parts of lander_B: bay inside the -X side (floor y = -0.82 m), ramp panel hinged at
// x = -1.0 m, y = -0.775 m. The panel swings down until its tip touches the ground at the footpad level (y = -1.45 m).
const BAY = { x: -0.5, floor: -0.82, lip: -1.0, hingeY: -0.775, ground: -LANDER_FEET, len: 1.0 }; // [m] in the lander frame
const RAMP_OPEN = Math.PI / 2 + Math.asin((BAY.hingeY - BAY.ground) / BAY.len); // [rad] rotation that lays the ramp on the ground
function rigRamp(inst) { inst.updateMatrixWorld(true); const panel = inst.getObjectByName('ramp_panel'); if (!panel) return null; const pivot = new THREE.Group(); pivot.position.set(BAY.lip, BAY.hingeY, 0); inst.add(pivot); pivot.updateMatrixWorld(true); pivot.attach(panel); return pivot; }
function bellsOf(inst) { const out = []; inst.traverse((o) => { if (o.isMesh && /^engine_.*_bell_inner$/.test(o.name)) out.push(o); }); return out.sort((a, b) => a.name.localeCompare(b.name)); }
// Contact path of the rover's wheels in the lander frame: along the bay floor, over the lip, down the ramp, onto the ground.
const tipX = BAY.lip - Math.cos(RAMP_OPEN - Math.PI / 2) * BAY.len;
const DEPLOY = [new THREE.Vector3(BAY.x, BAY.floor, 0), new THREE.Vector3(BAY.lip, BAY.hingeY - 0.02, 0), new THREE.Vector3(tipX, BAY.ground, 0), new THREE.Vector3(tipX - 2.4, BAY.ground, 0)];
const DEPLOY_LEN = DEPLOY.reduce((s, p, i) => s + (i ? p.distanceTo(DEPLOY[i - 1]) : 0), 0);
function deployPoint(s) { s = clamp(s, 0, DEPLOY_LEN); for (let i = 1; i < DEPLOY.length; i++) { const d = DEPLOY[i].distanceTo(DEPLOY[i - 1]); if (s <= d || i === DEPLOY.length - 1) return DEPLOY[i - 1].clone().lerp(DEPLOY[i], clamp(s / d, 0, 1)); s -= d; } return DEPLOY[DEPLOY.length - 1].clone(); }
function deployPose(s) { // rover centre and orientation in the lander frame, using its front and rear wheel contacts (0.74 m apart)
  const f = deployPoint(s + 0.37), b = deployPoint(s - 0.37), fwd = f.clone().sub(b).normalize(), up = new THREE.Vector3(fwd.y, -fwd.x, 0); if (up.y < 0) up.negate();
  return { p: f.clone().add(b).multiplyScalar(0.5).addScaledVector(up, ROVER_WHEELS), up, fwd };
}

function detailNormals(size = 512) { // tileable fine regolith bumps as a normal map: VISUAL DETAIL, NOT DATA
  const h = new Float32Array(size * size), rnd = (i) => { const x = Math.sin(i * 12.9898) * 43758.5453; return x - Math.floor(x); };
  for (let o = 0; o < 4; o++) { const cell = size >> (o + 2), amp = 1 / (o + 1); for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) { const cx = Math.floor(x / cell), cy = Math.floor(y / cell), n = (size / cell) | 0,
    fx = x / cell - cx, fy = y / cell - cy, g = (a, b) => rnd(((a % n) + n) % n + (((b % n) + n) % n) * 131 + o * 977), s = (t) => t * t * (3 - 2 * t);
    h[y * size + x] += amp * ((g(cx, cy) * (1 - s(fx)) + g(cx + 1, cy) * s(fx)) * (1 - s(fy)) + (g(cx, cy + 1) * (1 - s(fx)) + g(cx + 1, cy + 1) * s(fx)) * s(fy)); } }
  const d = new Uint8Array(size * size * 4); for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) { const at = (a, b) => h[((b + size) % size) * size + ((a + size) % size)], dx = (at(x + 1, y) - at(x - 1, y)) * 2.2, dy = (at(x, y + 1) - at(x, y - 1)) * 2.2, l = Math.hypot(dx, dy, 1), k = (y * size + x) * 4;
    d[k] = (-dx / l * 0.5 + 0.5) * 255; d[k + 1] = (-dy / l * 0.5 + 0.5) * 255; d[k + 2] = (1 / l * 0.5 + 0.5) * 255; d[k + 3] = 255; }
  const t = new THREE.DataTexture(d, size, size); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.generateMipmaps = true; t.minFilter = THREE.LinearMipmapLinearFilter; t.magFilter = THREE.LinearFilter; t.anisotropy = 16; t.needsUpdate = true; return t;
}
function buildSurface() {
  const R = W.rows, C = W.cols, td = DS.last; hRef = 0; hRef = heightAt(td.x, td.y);
  const photo = tex(`${BASE}assets/site01/photo_1m.jpg`), ctxPhoto = tex(`${BASE}assets/site01/photo_ctx_2m.jpg`);
  const geo = gridGeometry(R, C, (r, c) => [c * W.mpp - W.half_x, W.height[r * C + c] - hRef, r * W.mpp - W.half_y], (r, c) => [c / (C - 1), 1 - r / (R - 1)]);
  const nm = detailNormals(); nm.repeat.set(160, 160); nm.channel = 1; geo.setAttribute('uv1', geo.attributes.uv.clone()); // detail tiles 160x across the tile (about 16 m per repeat)
  const terrain = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: photo, normalMap: nm, normalScale: new THREE.Vector2(0.55, 0.55), color: new THREE.Color(1.7, 1.7, 1.75), roughness: 1, metalness: 0 })); terrain.receiveShadow = true; surf.add(terrain);
  if (W.context) { const X = W.context, n = X.rows, m = X.cols, H = b64f32(X.height_f32), x0 = X.offset_x_m - (m - 1) / 2 * X.mpp, y0 = X.offset_y_m + (n - 1) / 2 * X.mpp, HALF = 2560;
    const inside = (r, c) => { const xa = x0 + c * X.mpp, ya = y0 - r * X.mpp; return xa > -W.half_x + 25 && xa + X.mpp < W.half_x - 25 && ya < W.half_y - 25 && ya - X.mpp > -W.half_y + 25; };
    const cg = gridGeometry(n, m, (r, c) => [x0 + c * X.mpp, H[r * m + c] - hRef - 0.6, -(y0 - r * X.mpp)], (r, c) => [clamp((x0 + c * X.mpp + HALF) / (2 * HALF), 0, 1), clamp((y0 - r * X.mpp + HALF) / (2 * HALF), 0, 1)], inside);
    const ctx = new THREE.Mesh(cg, new THREE.MeshStandardMaterial({ map: ctxPhoto, color: new THREE.Color(1.6, 1.6, 1.65), roughness: 1 })); ctx.receiveShadow = true; surf.add(ctx); }
  const s = RV.sun; const az = s.az * DEG, el = Math.max(s.el, 0.5) * DEG; // sun azimuth and elevation from the recorded run
  surfSun = addSun(surf, new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el))); surfSun.light.intensity = 3.0;
  surf.add(new THREE.HemisphereLight(0xa9c2ff, 0x3a2f24, 1.7)); // earthshine and scattered fill, so shadowed ground stays readable addEarth(surf, new THREE.Vector3(0.0, 0.12, 1)); surf.fog = new THREE.FogExp2(0x02040a, 0.00005);
  for (const t of W.targets || []) { // ice-evidence targets: a soft ring and a thin beam
    const g = new THREE.Group(); const ring = new THREE.Mesh(new THREE.RingGeometry(3.2, 4.2, 64), new THREE.MeshBasicMaterial({ color: 0xffa566, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false })); ring.rotation.x = -Math.PI / 2; ring.position.y = 0.3; g.add(ring);
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 40, 12, 1, true), new THREE.MeshBasicMaterial({ color: 0xffa566, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false })); beam.position.y = 20; g.add(beam);
    g.position.copy(toScene(t.x_m, t.y_m, groundY(t.x_m, t.y_m))); g.userData = { t, ring, beam }; surf.add(g); marks.push(g); label(g, `Ice target ${t.id}`, 'warn', 5, { maxD: 900 }); }
  const tg = new THREE.TubeGeometry(RV.curve, RV.segs, 0.3, 8, false); trail = new THREE.Mesh(tg, new THREE.MeshBasicMaterial({ color: 0x2f7dff, transparent: true, opacity: 0.8 })); surf.add(trail);
  const dp = DS.frames.map((f) => toScene(f.lander.x_m, f.lander.y_m, f.lander.alt_m + LANDER_FEET));
  descentLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints(dp), new THREE.LineDashedMaterial({ color: 0xffa566, dashSize: 6, gapSize: 5, transparent: true, opacity: 0.55 })); descentLine.computeLineDistances(); surf.add(descentLine);
}

// ------------------------------------------------------------------------------------------------ labels
const labels = [];
function label(obj, text, cls = '', dy = 2, o = {}) { const el = document.createElement('div'); el.className = `lbl ${cls}`; el.textContent = text; $('labels').appendChild(el); const L = { obj, el, dy, ...o }; labels.push(L); return L; }
function sceneOf(o) { while (o.parent) o = o.parent; return o; }
function shownChain(o) { for (; o; o = o.parent) if (!o.visible) return false; return true; }
const lv = new THREE.Vector3(), lu = new THREE.Vector3();
function drawLabels(scene) {
  for (const L of labels) {
    let show = shownChain(L.obj) && L.on !== false && sceneOf(L.obj) === scene; if (show) { L.obj.getWorldPosition(lv); const d = lv.distanceTo(camera.position); if ((L.maxD && d > L.maxD) || (L.minD && d < L.minD)) show = false; }
    if (show) { lu.set(0, 1, 0).applyQuaternion(L.obj.getWorldQuaternion(new THREE.Quaternion())); lv.addScaledVector(lu, L.dy).project(camera); show = lv.z < 1 && Math.abs(lv.x) < 1.02 && Math.abs(lv.y) < 1.02; }
    L.el.style.opacity = show ? 1 : 0; if (show) L.el.style.transform = `translate(${Math.round((lv.x * 0.5 + 0.5) * innerWidth + 14)}px, ${Math.round((-lv.y * 0.5 + 0.5) * innerHeight)}px) translateY(-50%)`;
  }
}

// ------------------------------------------------------------------------------------------------ story
const CH = [];
function warp(u, pts) { for (let i = 1; i < pts.length; i++) if (u <= pts[i][0]) { const [a, b] = [pts[i - 1], pts[i]]; return lerp(a[1], b[1], (u - a[0]) / ((b[0] - a[0]) || 1)); } return 1; }
function buildStory() {
  const ph = (p) => frames.filter((f) => f.mission_phase === p), o = ph('ORBIT'), d = ph('DEORBIT'), ds = ph('DESCENT');
  const later = o.filter((f) => f.t_s > o[0].t_s + 3000), pole = (later.length ? later : o).reduce((m, f) => (f.orbit.lat_deg < m.orbit.lat_deg ? f : m)); // a pass right over the south pole
  CH.push({ id: 'orbit', dur: 38, a: pole.t_s - 560, b: pole.t_s + 520, title: 'Lunar orbit', text: 'The lander rides on the propulsion module, 100 km above the Moon, in an orbit over both poles.' });
  CH.push({ id: 'sep', dur: 16, a: d[0].t_s, b: d[0].t_s, title: 'Separation', text: 'Small thrusters push the lander away. The propulsion module stays behind in orbit.' });
  CH.push({ id: 'deorbit', dur: 24, a: d[0].t_s, b: d[d.length - 1].t_s, warp: [[0, 0], [0.32, 0.004], [1, 1]], title: 'Deorbit burn', text: 'The lander turns around and fires its engines to drop towards the south pole.' });
  CH.push({ id: 'descent', dur: 36, a: ds[0].t_s, b: ds[ds.length - 1].t_s, warp: [[0, 0], [0.7, 0.84], [1, 1]], title: 'Powered descent', text: 'Five engines brake from 1,955 m. One engine fails; the opposite one shuts down so the lander stays balanced.' });
  CH.push({ id: 'surface', dur: 62, a: 0, b: 1, title: 'Rover on the surface', text: 'The ramp swings down and the rover drives out of the lander, then across real NASA terrain towards signs of ice.' });
  CH.push({ id: 'ghosts', dur: 30, a: 0, b: 1, title: 'Ghost runs', text: 'Simulated attempts side by side. Blue is the best run; orange runs stop where they failed.' });
  let t = 0; for (const c of CH) { c.T0 = t; t += c.dur; c.T1 = t; } S.total = t;
}
function chapterAt(T) { for (let i = 0; i < CH.length; i++) if (T < CH[i].T1) return i; return CH.length - 1; }

// ------------------------------------------------------------------------------------------------ camera rig (heavily damped for calm motion)
const cam = { pos: new THREE.Vector3(), look: new THREE.Vector3(), up: new THREE.Vector3(0, 1, 0), wantUp: new THREE.Vector3(0, 1, 0), init: false }; // up follows the local vertical so the Moon stays below
function aim(pos, look, k, dt) { k = 1 - Math.pow(1 - k, dt * 60); if (!S.playing) k = Math.max(k, 0.35); if (!cam.init) { cam.pos.copy(pos); cam.look.copy(look); cam.init = true; } else { cam.pos.lerp(pos, k); cam.look.lerp(look, k); } }
function applyCamera() { if (!cam.init || !S.playing || cam.up.dot(cam.wantUp) < 0.2) cam.up.copy(cam.wantUp); else cam.up.lerp(cam.wantUp, 0.06).normalize(); /* no blend through zero */ camera.up.copy(cam.up); if (S.cam === 'free') return; camera.position.copy(cam.pos); camera.lookAt(cam.look); }

// ------------------------------------------------------------------------------------------------ orbit, separation, deorbit
const Y = new THREE.Vector3(0, 1, 0);
function orbitBasis(t) { const p = OB.at(t), p2 = OB.at(t + 30); const P = llr(p.lat, p.lon, R_MOON + p.alt * 1000), P2 = llr(p2.lat, p2.lon, R_MOON + p2.alt * 1000); const up = P.clone().normalize(); return { P, up, fwd: P2.sub(P).projectOnPlane(up).normalize(), p }; }
function orient(obj, up, fwd) { const z = fwd.clone().negate(), x = new THREE.Vector3().crossVectors(up, z).normalize(), y = new THREE.Vector3().crossVectors(z, x); obj.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z)); }
function updateOrbit(c, u, sim, dt, wall) {
  const B = orbitBasis(sim); cam.wantUp.copy(B.up); moonGroup.position.copy(B.P).negate(); orbitEarth.position.copy(orbitEarth.userData.dir).multiplyScalar(EARTH_D).sub(B.P); // the vehicle stays at the origin, the Moon moves
  orbitSun.place(new THREE.Vector3(), 200, 30); const side = new THREE.Vector3().crossVectors(B.up, B.fwd), zf = S.zoom;
  for (const e of fx.orbitEngines) e.set(0, wall, dt); fx.pmEngine.set(0, wall, dt);
  if (c.id === 'orbit') {
    stack.visible = true; pmHolder.visible = false; landerOrbit.visible = false; orient(stack, B.up, B.fwd); models.stackLander.position.y = DOCK_Y; models.stackPM.position.y = 0; models.stackPM.rotation.z = 0;
    // opening shot: the whole Moon, then a slow fly-in to the docked pair
    const k = ease(clamp(u / 0.55, 0, 1)), dist = Math.exp(lerp(Math.log(6.2e6), Math.log(22 * zf), k)), dir = B.up.clone().multiplyScalar(0.55).addScaledVector(side, 0.75).addScaledVector(B.fwd, -0.4).normalize();
    const moonC = moonGroup.position.clone(), look = moonC.clone().lerp(B.up.clone().multiplyScalar(0.8), smooth(clamp((u - 0.05) / 0.5, 0, 1)));
    const orbitA = u > 0.55 ? (u - 0.55) * 1.4 : 0; const chase = B.fwd.clone().multiplyScalar(-Math.cos(orbitA) * 0.7).addScaledVector(side, Math.cos(orbitA) * 0.7 + Math.sin(orbitA) * 0.5).addScaledVector(B.up, 0.28).normalize();
    const p = (u < 0.55 ? dir : dir.clone().lerp(chase, smooth(clamp((u - 0.55) / 0.3, 0, 1))).normalize()).multiplyScalar(dist);
    aim(p, look, u < 0.6 ? 1 : 0.04, dt);
  }
  if (c.id === 'sep') {
    stack.visible = true; pmHolder.visible = false; landerOrbit.visible = false; orient(stack, B.up, B.fwd); const k = ease(clamp((u - 0.18) / 0.72, 0, 1)); models.stackLander.position.y = DOCK_Y + 16 * k; models.stackPM.position.y = -1.0 * k; models.stackPM.rotation.z = 0.06 * k;
    if (u > 0.15 && u < 0.4) for (const n of models.landerRcsDown) fx.rcs.emit(models.stackLander.localToWorld(n.clone()), B.up.clone().multiplyScalar(-2.2), 0.5, 0.9);
    aim(side.clone().multiplyScalar(26 * zf).addScaledVector(B.fwd, -12 * zf).addScaledVector(B.up, (4 + 7 * k) * zf), B.up.clone().multiplyScalar(2 + 8 * k), 0.03, dt);
  }
  if (c.id === 'deorbit') {
    stack.visible = false; pmHolder.visible = true; landerOrbit.visible = true;
    const B0 = orbitBasis(c.a), s0 = { P: B0.P, up: B0.up, fwd: B0.fwd, t: c.a }, n = new THREE.Vector3().crossVectors(s0.up, s0.fwd).normalize(), w = 1633.5 / (R_MOON + 100e3); // [rad/s] circular-orbit rate of the module
    const ang = w * (sim - s0.t), pmP = s0.P.clone().normalize().multiplyScalar(R_MOON + 100e3).applyAxisAngle(n, ang).addScaledVector(s0.up.clone().applyAxisAngle(n, ang), -17.4); // the module stays ~17 m below where the lander separated pmHolder.position.copy(pmP).sub(B.P); orient(pmHolder, pmP.clone().normalize(), s0.fwd.clone().applyAxisAngle(n, ang));
    // the lander turns so its engines face forward (retrograde), burns, then turns back
    const turn = win(u, 0.02, 0.36, 0.07), burn = win(u, 0.1, 0.28, 0.03), q0 = new THREE.Object3D(), q1 = new THREE.Object3D(); orient(q0, B.up, B.fwd); orient(q1, B.fwd.clone().negate(), B.up); landerOrbit.quaternion.copy(q0.quaternion).slerp(q1.quaternion, turn);
    for (const e of fx.orbitEngines) e.set(burn, wall, dt);
    if (u < 0.4) aim(side.clone().multiplyScalar(17 * zf).addScaledVector(B.fwd, 7 * zf).addScaledVector(B.up, 3 * zf), new THREE.Vector3(), 0.03, dt);
    else aim(B.fwd.clone().multiplyScalar(-26 * zf).addScaledVector(B.up, 8 * zf).addScaledVector(side, 6 * zf), B.fwd.clone().multiplyScalar(40).addScaledVector(B.up, -14), 0.02, dt);
  }
  fx.rcs.step(dt, 0.6); controls.target.set(0, 0, 0);
}

// ------------------------------------------------------------------------------------------------ descent
const descentTilt = new THREE.Quaternion(), landerYaw = new THREE.Quaternion();
function placeRoverInBay(s) { const P = deployPose(s), o = new THREE.Object3D(); orient(o, P.up, P.fwd); roverG.position.copy(landerSurf.localToWorld(P.p.clone())); roverG.quaternion.copy(landerSurf.quaternion).multiply(o.quaternion); }
function updateDescent(c, u, sim, dt, wall) {
  cam.wantUp.set(0, 1, 0);
  const f = DS.at(sim), P = toScene(f.x, f.y, f.alt + LANDER_FEET); landerSurf.position.copy(P); landerSurf.visible = true; roverG.visible = true; descentLine.visible = true; trail.visible = false; ghostG.visible = false; models.ramp.rotation.z = 0;
  const vh = new THREE.Vector3(f.vx, 0, -f.vy), tiltA = clamp(Math.atan2(vh.length(), Math.max(Math.abs(f.vz), 2)) * 0.6, 0, 0.3), axis = vh.lengthSq() > 1e-4 ? new THREE.Vector3().crossVectors(Y, vh).normalize().negate() : new THREE.Vector3(1, 0, 0);
  descentTilt.setFromAxisAngle(axis, tiltA * clamp(f.alt / 80, 0, 1)).multiply(landerYaw); landerSurf.quaternion.slerp(descentTilt, 1 - Math.pow(0.9, dt * 60)); landerSurf.updateMatrixWorld(true); placeRoverInBay(0); models.roverLabel.on = false;
  const per = f.thrust / Math.max(f.eng, 1) / 800, off = f.eng < 5 ? new Set([1, 3]) : new Set(); // [-] throttle per 800 N engine; after the failure an opposite pair (1, 3) is off
  fx.descent.forEach((e, i) => e.set(f.alt > 0.3 && !off.has(i) ? per : 0, wall + i, dt));
  const g = groundY(f.x, f.y), near = clamp(1 - f.alt / 40, 0, 1); if (near > 0 && f.alt > 0.3) for (let k = 0; k < 14 * near; k++) { const a = Math.random() * Math.PI * 2, r0 = 1.5 + 2 * Math.random(), sp = 9 + 16 * Math.random(); fx.dust.emit(toScene(f.x + Math.cos(a) * r0, f.y + Math.sin(a) * r0, g + 0.1), new THREE.Vector3(Math.cos(a) * sp, 0.1 + Math.random() * 0.4, -Math.sin(a) * sp), 0.4, 1.1); } // a thin sheet of dust blown outwards along the ground
  fx.dust.step(dt, 0.5);
  const zf = S.zoom, k = smooth(u), d = lerp(240, 16, k) * zf, h = lerp(120, 0.9, k) * zf, ang = 0.9 - u * 0.9; // ends low so the flames under the deck stay in view
  aim(P.clone().add(new THREE.Vector3(Math.sin(ang) * d, h, Math.cos(ang) * d)), P.clone().add(new THREE.Vector3(0, -f.alt * 0.2 * (1 - k) - 0.8 * k, 0)), 0.03, dt);
  surfSun.place(P, 600, 45); controls.target.copy(P);
}

// ------------------------------------------------------------------------------------------------ rover (moves by distance driven along a smoothed copy of the recorded path)
function updateSurface(c, u, sim, dt, wall) {
  cam.wantUp.set(0, 1, 0);
  const td = DS.last; landerSurf.visible = true; landerSurf.position.copy(toScene(td.x, td.y, LANDER_FEET)); landerSurf.quaternion.slerp(landerYaw, 0.2); landerSurf.updateMatrixWorld(true);
  fx.descent.forEach((e) => e.set(0, wall, dt)); descentLine.visible = false; ghostG.visible = false; roverG.visible = true; trail.visible = true;
  models.roverLabel.on = u > 0.16; const ramp = smooth(clamp((u - 0.05) / 0.08, 0, 1)); models.ramp.rotation.z = RAMP_OPEN * ramp; // the ramp swings down on its hinge
  const out = smooth(clamp((u - 0.14) / 0.14, 0, 1)), join = smooth(clamp((u - 0.28) / 0.06, 0, 1)), prog = smooth(clamp((u - 0.34) / 0.58, 0, 1));
  let x, y, fwd; const R = roverG.position;
  if (u < 0.28) { placeRoverInBay(out * DEPLOY_LEN); x = R.x; y = -R.z; fwd = new THREE.Vector3(-1, 0, 0).applyQuaternion(landerSurf.quaternion); }
  else { // from the foot of the ramp onto the recorded path, then along it by distance driven
    const foot = landerSurf.localToWorld(deployPose(DEPLOY_LEN).p.clone()), s = lerp(RV.s0, 1, prog), p = RV.curve.getPointAt(s), tan = RV.curve.getTangentAt(Math.min(s, 0.999));
    const tgt = join < 1 ? foot.clone().lerp(p, join) : p; x = tgt.x; y = -tgt.z; const n = groundNormal(x, y);
    fwd = (join < 1 ? p.clone().sub(foot).setY(0).normalize().lerp(tan, join) : tan).clone().projectOnPlane(n).normalize(); const o = new THREE.Object3D(); orient(o, n, fwd);
    R.set(x, groundY(x, y) + ROVER_WHEELS, tgt.z); roverG.quaternion.slerp(o.quaternion, 1 - Math.pow(0.85, dt * 60));
    trail.geometry.setDrawRange(RV.trailStart, Math.max(0, Math.floor(RV.segs * s) * 8 * 6 - RV.trailStart)); }
  if (u < 0.28) trail.geometry.setDrawRange(0, 0);
  const t = RV.tOfS(lerp(RV.s0, 1, prog)), f = RV.frame(t); for (const g of marks) { const done = u > 0.34 && f?.targets?.find((q) => q.id === g.userData.t.id)?.sampled, col = done ? 0x2f7dff : 0xffa566; g.userData.ring.material.color.setHex(col); g.userData.beam.material.color.setHex(col); }
  fx.dust.step(dt, 0.5); const zf = S.zoom, L = landerSurf.position, bay = new THREE.Vector3(-1, 0, 0).applyQuaternion(landerSurf.quaternion), side = new THREE.Vector3().crossVectors(Y, bay).normalize();
  if (u < 0.34) aim(L.clone().addScaledVector(bay, 6.5 * zf).addScaledVector(side, 4.5 * zf).add(new THREE.Vector3(0, 1.6 * zf, 0)), L.clone().addScaledVector(bay, 1.6 + 1.8 * out).add(new THREE.Vector3(0, -0.6, 0)), 0.03, dt); // side view of the bay and ramp
  else if (u < 0.82) { const a = (u - 0.34) * 1.6, sd = new THREE.Vector3().crossVectors(Y, fwd).normalize(); aim(R.clone().addScaledVector(fwd, -6.5 * zf).addScaledVector(sd, (2.5 + 2 * Math.sin(a)) * zf).add(new THREE.Vector3(0, 2.4 * zf, 0)), R.clone().addScaledVector(fwd, 3).add(new THREE.Vector3(0, 0.3, 0)), 0.02, dt); }
  else { const mid = L.clone().lerp(R, 0.5); aim(mid.clone().add(new THREE.Vector3(-140 * zf, 110 * zf, 160 * zf)), mid, 0.012, dt); }
  surfSun.place(R, 600, 40); controls.target.copy(R);
}

// ------------------------------------------------------------------------------------------------ ghost runs (only what the files contain; nothing invented)
const ghostG = new THREE.Group(); surf.add(ghostG); const ghostRuns = [];
const SUCCESS = new Set(['returned', 'ok', 'reached_ice_only']), OUTCOME = { returned: 'returned', reached_ice_only: 'reached the ice, did not return', died_battery: 'battery empty', blocked: 'blocked', timeout: 'ran out of time', ok: 'landed OK', hard_vertical: 'landed too hard', hard_horizontal: 'landed sliding sideways', steep_slope: 'landed on a steep slope', hazard_cell: 'landed in a hazard cell', out_of_fuel: 'out of fuel', out_of_bounds: 'left the allowed area' };
function buildGhosts() {
  for (const file of ghostFiles) for (const run of file.runs.slice(0, 12)) {
    const ok = SUCCESS.has(run.outcome), col = run.best ? 0x2f7dff : ok ? 0x8db9ff : 0xffa566, kind = file.kind;
    const pt = (i) => { const [x, y, z] = run.xyz_m[i]; return kind === 'rover' ? toScene(x, y, groundY(x, y) + ROVER_WHEELS) : toScene(x, y, Math.abs(z) > 300 ? z - hRef : z + groundY(x, y)); };
    const pts = run.t_s.map((_, i) => pt(i)), line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: run.best ? 1 : 0.7 })); ghostG.add(line);
    const body = new THREE.Group(), model = (kind === 'rover' ? models.rover : models.lander).clone(true); body.add(model);
    model.traverse((m) => { if (m.isMesh) { m.material = m.material.clone(); m.material.transparent = !run.best; m.material.opacity = run.best ? 1 : 0.38; m.material.depthWrite = run.best; m.material.emissive = new THREE.Color(col); m.material.emissiveIntensity = run.best ? 0.08 : 0.35; } });
    ghostG.add(body); const L = label(body, `${run.best ? 'Best · ' : ''}${run.id}`, run.best ? 'best' : ok ? '' : 'warn', kind === 'rover' ? 1.4 : 4); ghostRuns.push({ run, body, line, pts, L });
  }
  ghostG.visible = false;
}
function updateGhosts(c, u, sim, dt, wall) {
  cam.wantUp.set(0, 1, 0);
  landerSurf.visible = true; roverG.visible = false; trail.visible = false; descentLine.visible = false; ghostG.visible = true; const tmax = Math.max(1, ...ghostRuns.map((g) => g.run.t_s[g.run.t_s.length - 1])), t = smooth(u) * tmax, box = new THREE.Box3();
  for (const g of ghostRuns) { const T = g.run.t_s, stop = g.run.fail_t_s != null ? Math.min(t, g.run.fail_t_s) : t; let i = 0; while (i < T.length - 2 && T[i + 1] <= stop) i++; const a = g.pts[i], b = g.pts[Math.min(i + 1, T.length - 1)], w = clamp((stop - T[i]) / ((T[i + 1] - T[i]) || 1), 0, 1);
    g.body.position.copy(a).lerp(b, w); if (b.distanceToSquared(a) > 1e-6) { const o = new THREE.Object3D(); orient(o, Y, b.clone().sub(a).setY(0).normalize()); g.body.quaternion.slerp(o.quaternion, 0.2); }
    g.line.geometry.setDrawRange(0, i + 2); const frozen = g.run.fail_t_s != null && t >= g.run.fail_t_s; g.L.el.textContent = `${g.run.best ? 'Best · ' : ''}${g.run.id}${frozen ? ' · ' + (OUTCOME[g.run.outcome] || g.run.outcome) : ''}`; box.expandByPoint(g.body.position); }
  const ctr = box.isEmpty() ? landerSurf.position.clone() : box.getCenter(new THREE.Vector3()), sz = box.isEmpty() ? 60 : Math.max(40, box.getSize(new THREE.Vector3()).length()), a = wall * 0.04;
  aim(ctr.clone().add(new THREE.Vector3(Math.cos(a) * sz * 0.9 * S.zoom, sz * 0.7 * S.zoom, Math.sin(a) * sz * 0.9 * S.zoom)), ctr, 0.02, dt); surfSun.place(ctr, 600, Math.max(40, sz)); controls.target.copy(ctr);
}

// ------------------------------------------------------------------------------------------------ title card and timeline
function hud(c) {
  const tin = S.T - c.T0, op = smooth(clamp((tin - 0.4) / 1.0, 0, 1)) * smooth(clamp((6.5 - tin) / 1.2, 0, 1));
  if ($('title-h').textContent !== c.title) { $('title-h').textContent = c.title; $('title-p').textContent = c.text; $('title-i').textContent = `${String(CH.indexOf(c) + 1).padStart(2, '0')} / ${String(CH.length).padStart(2, '0')}`; } $('title').style.opacity = String(op); $('title').style.transform = `translateY(${(1 - op) * 10}px)`;
  $('seek').value = String(Math.round(S.T / S.total * 1000)); const s = Math.floor(S.T); $('clock').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

// ------------------------------------------------------------------------------------------------ main loop
let last = performance.now(), wall = 0, active = null;
const fade = { want: null, a: 0 }; // frame-driven fade through black when the story changes scene
function fadeTo(scene) { if (!active) { active = scene; renderPass.scene = scene; renderer.toneMappingExposure = scene === surf ? 1.3 : 1.05; bloom.strength = scene === surf ? 0.28 : 0.34; return; } if (scene !== active) fade.want = scene; }
function stepFade(dt) {
  if (fade.want) { fade.a = Math.min(1, fade.a + dt / 0.5); if (fade.a >= 1) { active = fade.want; renderPass.scene = active; fade.want = null; cam.init = false; renderer.toneMappingExposure = active === surf ? 1.3 : 1.05; bloom.strength = active === surf ? 0.28 : 0.34; } }
  else fade.a = Math.max(0, fade.a - dt / 0.7);
  $('fade').style.opacity = String(fade.a);
}
function tick(now) {
  requestAnimationFrame(tick); const dt = Math.min((now - last) / 1000, 0.05); last = now; wall += dt;
  if (S.ready) {
    if (S.playing) { S.T += dt; if (S.T >= S.total) S.T = 0; }
    const ci = chapterAt(S.T), c = CH[ci], u = clamp((S.T - c.T0) / c.dur, 0, 1), sim = lerp(c.a, c.b, c.warp ? warp(u, c.warp) : u);
    if (ci !== S.chapter) { S.chapter = ci; cam.init = false; }
    fadeTo(['orbit', 'sep', 'deorbit'].includes(c.id) ? orbit : surf);
    const shown = active === orbit ? (['orbit', 'sep', 'deorbit'].includes(c.id) ? c : CH[2]) : c; // keep drawing the old scene while it fades out
    if (active === orbit) updateOrbit(shown, shown === c ? u : 1, shown === c ? sim : CH[2].b, dt, wall);
    else if (shown.id === 'descent') updateDescent(shown, u, sim, dt, wall); else if (shown.id === 'surface') updateSurface(shown, u, sim, dt, wall); else if (shown.id === 'ghosts') updateGhosts(shown, u, sim, dt, wall); else updateDescent(CH[3], 0, CH[3].a, dt, wall);
    stepFade(dt); applyCamera(); if (S.cam === 'free') controls.update(); hud(c); drawLabels(active);
    if (Q.get('debug')) document.title = JSON.stringify({ ch: c.id, u: +u.toFixed(3), cam: camera.position.toArray().map((v) => +v.toFixed(1)), fade: +fade.a.toFixed(2) });
  }
  grade.uniforms.uTime.value = wall; if (renderPass.scene) composer.render(); else renderer.clear();
}

// ------------------------------------------------------------------------------------------------ controls (auto-hide like a video player)
let idle = 0; const wake = () => { document.body.classList.add('ui-on'); clearTimeout(idle); idle = setTimeout(() => { if (!document.querySelector('#bar:hover')) document.body.classList.remove('ui-on'); }, 2500); };
addEventListener('mousemove', wake); addEventListener('pointerdown', wake); wake();
const setPlay = (p) => { S.playing = p; $('play').textContent = p ? '❚❚' : '▶'; $('play').setAttribute('aria-label', p ? 'Pause' : 'Play'); };
$('play').onclick = () => setPlay(!S.playing);
$('seek').oninput = (e) => { S.T = Number(e.target.value) / 1000 * S.total; cam.init = false; };
const seg = (id, fn) => { for (const b of $(id).children) b.onclick = () => { for (const x of $(id).children) x.classList.toggle('on', x === b); fn(b.dataset.v); }; };
seg('cam', (v) => { S.cam = v; controls.enabled = v === 'free'; if (v === 'free') controls.target.copy(cam.look); });
seg('quality', (v) => { S.quality = v; resize(); });
const zoom = (f) => { if (S.cam === 'free') { const d = camera.position.clone().sub(controls.target).multiplyScalar(f); camera.position.copy(controls.target).add(d); } else S.zoom = clamp(S.zoom * f, 0.35, 3.5); };
$('zin').onclick = () => zoom(0.8); $('zout').onclick = () => zoom(1.25);
$('labelsBtn').onclick = () => { S.labels = !S.labels; document.body.classList.toggle('nolabels', !S.labels); $('labelsBtn').classList.toggle('on', S.labels); };
$('full').onclick = () => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen());
canvas.addEventListener('wheel', (e) => { if (S.cam === 'cine') { e.preventDefault(); S.zoom = clamp(S.zoom * Math.exp(e.deltaY * 0.001), 0.35, 3.5); } }, { passive: false });
addEventListener('keydown', (e) => {
  wake(); if (e.code === 'Space') { e.preventDefault(); setPlay(!S.playing); } if (e.code === 'KeyF') $('full').click(); if (e.code === 'KeyH') document.body.classList.toggle('clean');
  if (e.code === 'Equal' || e.code === 'NumpadAdd') zoom(0.87); if (e.code === 'Minus' || e.code === 'NumpadSubtract') zoom(1.15);
  if (e.code === 'ArrowRight' || e.code === 'ArrowLeft') { const i = clamp(chapterAt(S.T) + (e.code === 'ArrowRight' ? 1 : -1), 0, CH.length - 1); S.T = CH[i].T0 + 0.01; cam.init = false; }
});

// ------------------------------------------------------------------------------------------------ boot
async function boot() {
  resize(); requestAnimationFrame(tick);
  const wr = await getJSON(['../sample/world.json', '../ui/sample/world.json']); W = await wr.json(); W.height = b64f32(W.height_f32);
  frames = (await (await fetch(`${BASE}sample/run.jsonl`)).text()).split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((m) => m.type === 'frame');
  const of = frames.filter((f) => f.orbit), df = frames.filter((f) => f.lander), rf = frames.filter((f) => f.pose);
  OB = { at: series(of, (f) => ({ lat: f.orbit.lat_deg, lon: f.orbit.lon_deg, alt: f.orbit.alt_km })) };
  DS = { frames: df, at: series(df, (f) => ({ x: f.lander.x_m, y: f.lander.y_m, alt: f.lander.alt_m, vx: f.lander.vx_m_s, vy: f.lander.vy_m_s, vz: f.lander.vz_m_s, thrust: f.lander.thrust_n, eng: f.lander.engines_ok })), t1: df[df.length - 1].t_s };
  DS.last = DS.at(DS.t1);
  // rover path: arc length of the recorded positions, so the film moves the rover by distance driven (steady, readable)
  // instead of by clock time (long stops while it waits for sunlight, then jumps).
  const rp = [], rt = [], rs = []; let acc = 0;
  for (const f of rf) { const q = new THREE.Vector3(f.pose.x_m, 0, -f.pose.y_m); if (rp.length) { const dd = q.distanceTo(rp[rp.length - 1]); if (dd < 0.5) continue; acc += dd; } rp.push(q); rt.push(f.t_s); rs.push(acc); }
  RV = { frames: rf, curve: new THREE.CatmullRomCurve3(rp, false, 'centripetal'), segs: Math.max(200, rp.length * 16), sun: { az: rf[0].sun?.az_deg ?? 20, el: rf[0].sun?.elev_deg ?? 1.5 },
    tOfS: (s) => { const want = s * acc; let i = 0; while (i < rs.length - 1 && rs[i + 1] < want) i++; return rt[i]; }, frame: (t) => { let b = rf[0]; for (const f of rf) { if (f.t_s > t) break; b = f; } return b; } };
  RV.curve.arcLengthDivisions = RV.segs;
  RV.sAt = (m) => clamp(m / RV.curve.getLength(), 0, 1);
  try { const pj = await (await fetch('assets/moon/polar_south.json')).json(); POLAR.half = pj.half_m; POLAR.tex = tex('assets/moon/' + pj.image); POLAR.tex.generateMipmaps = true; POLAR.on.value = 1; } catch (e) { /* no polar mosaic: global map only */ }
  const moon = new THREE.Mesh(new THREE.SphereGeometry(R_MOON, 256, 128), moonMaterial(tex('assets/moon/moon_color_4k.jpg'))); moonGroup.add(moon);
  const track = of.map((f) => llr(f.orbit.lat_deg, f.orbit.lon_deg, R_MOON + f.orbit.alt_km * 1000)); moonGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(track), new THREE.LineBasicMaterial({ color: 0x8db9ff, transparent: true, opacity: 0.4 })));
  const site = new THREE.Mesh(new THREE.RingGeometry(14e3, 20e3, 96), new THREE.MeshBasicMaterial({ color: 0xffa566, side: THREE.DoubleSide, transparent: true, opacity: 0.95, depthWrite: false })); const sp = llr(W.site.lat_deg, W.site.lon_deg, R_MOON + 500); site.position.copy(sp); site.lookAt(sp.clone().multiplyScalar(2)); moonGroup.add(site);
  label(site, 'South-pole landing site', 'warn', 0, { minD: 2e5 });
  const [lander, rover, pm] = await Promise.all([loadModel('lander'), loadModel('rover'), loadModel('propulsion_module')]);
  rover.rotation.y = Math.PI / 2; // the rover model's front (cameras, arm, front wheels) is +X; the film drives along -Z
  rover.traverse((m) => { if (m.isMesh && m.material) { m.material.envMapIntensity = 0.2; if (m.material.metalness > 0.5) m.material.roughness = Math.max(m.material.roughness, 0.45); } }); models.lander = lander; models.rover = rover; models.pm = pm;
  models.stackPM = pm.clone(true); models.stackLander = lander.clone(true); stack.add(models.stackPM, models.stackLander);
  pmHolder.add(pm.clone(true)); const lOrbit = lander.clone(true), lSurf = lander.clone(true); landerOrbit.add(lOrbit); landerSurf.add(lSurf); roverG.add(rover);
  models.ramp = rigRamp(lSurf) || new THREE.Group();
  for (const inst of [models.stackLander, lOrbit]) { const r = rover.clone(true); r.rotation.y = Math.PI; const P = deployPose(0); r.position.copy(P.p); inst.add(r); } // the rover rides in the bay, facing out
  // the lander is turned so its bay faces the way the rover first drives (the run gives no lander heading)
  { const L0 = toScene(DS.last.x, DS.last.y, 0); let s0 = 0; for (let m = 2; m < 40; m += 0.5) { const q = RV.curve.getPointAt(RV.sAt(m)); if (Math.hypot(q.x - L0.x, q.z - L0.z) >= 6) { s0 = RV.sAt(m); break; } }
    const q = RV.curve.getPointAt(s0), d = new THREE.Vector3(q.x - L0.x, 0, q.z - L0.z).normalize(); landerYaw.setFromAxisAngle(Y, Math.atan2(d.z, -d.x)); RV.s0 = s0; }
  label(stack, 'Lander on the propulsion module', '', -3.4, { minD: 400 }); label(models.stackLander, 'Lander', '', 2.4, { maxD: 400 }); label(models.stackPM, 'Propulsion module', '', -1.4, { maxD: 400 });
  label(landerOrbit, 'Lander', '', 2.4); label(pmHolder, 'Propulsion module', '', 2.2); label(landerSurf, 'Lander', '', 2.6, { maxD: 1500 }); models.roverLabel = label(roverG, 'Rover', '', 1.0, { maxD: 600 });
  const bells = nozzles(lander, /^engine_.*_bell$/), innerO = bellsOf(lOrbit), innerS = bellsOf(lSurf); models.landerRcsDown = nozzles(lander, /^rcs\d_nozzle$/).map((n) => n.p);
  bells.forEach((b, i) => { const e = makeEngine(innerO[i]); e.position.copy(b.p); landerOrbit.add(e); fx.orbitEngines.push(e); const d = makeEngine(innerS[i]); d.position.copy(b.p); landerSurf.add(d); fx.descent.push(d); });
  const pmB = nozzles(pm, /^pm_main_engine_bell$/)[0]; fx.pmEngine = makeEngine(); if (pmB) fx.pmEngine.position.copy(pmB.p); pmHolder.add(fx.pmEngine);
  fx.rcs = makePuffs(orbit, 160, PUFF, 0.35); fx.dust = makePuffs(surf, 1600, DUST, 2.0); fx.dust.mat.blending = THREE.NormalBlending; fx.dust.mat.opacity = 0.2;
  buildSurface(); buildStory(); RV.trailStart = Math.floor(RV.segs * RV.s0) * 8 * 6;
  try { const r = await fetch('/api/ghosts'); if (r.ok) { for (const it of (await r.json()).filter((x) => x.summary?.kind && /\.json$/.test(x.name)).slice(0, 4)) { const j = await (await fetch(`/api/ghosts/${encodeURIComponent(it.name)}`)).json(); if (Array.isArray(j.runs)) ghostFiles.push(j); } } } catch (e) { /* no ghost API when hosted statically */ }
  buildGhosts(); if (!ghostRuns.length) { CH.pop(); S.total = CH[CH.length - 1].T1; } // no ghost files yet: the film ends with the rover
  const ch = Q.get('chapter'); if (ch) { const c = CH.find((x) => x.id === ch); if (c) S.T = c.T0 + Number(Q.get('u') || 0.3) * c.dur; }
  if (Q.get('pause') === '1') setPlay(false); if (Q.get('clean') === '1') document.body.classList.add('clean');
  S.ready = true; window.__showcase = { S, CH };
}
boot().catch((e) => { $('title-h').textContent = 'Could not load the mission data'; $('title-p').textContent = String(e.message || e); $('title').style.opacity = 1; console.error(e); });
