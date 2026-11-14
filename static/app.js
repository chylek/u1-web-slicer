import * as T from './vendor/three.module.min.js';
import {OrbitControls} from './vendor/OrbitControls.js';
import {TransformControls} from './vendor/TransformControls.js';

const $ = (id) => document.getElementById(id);
const WIDE = matchMedia('(min-width:900px) and (min-height:560px) and (pointer:fine)'); // same query as style.css
const el = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
};

// ---------- icons (stroke, 24 grid)
const ICONS = {
  folder: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  chev: 'M6 9l6 6 6-6',
  save: 'M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM8 3v5h7V3M7 21v-7h10v7',
  plus: 'M12 5v14M5 12h14',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  rl: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5',
  rr: 'M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5',
  move: 'M12 2v20M2 12h20M9 5l3-3 3 3M9 19l3 3 3-3M5 9l-3 3 3 3M19 9l3 3-3 3',
  rot3: 'M20 13a8 8 0 1 1-2.3-5.7M20 4v5h-5M12 12l-7 7M12 12l8-4',
  lay: 'M3 20h18M7 4l10 3-4 9-10-3zM12 16v4',
  scale: 'M4 14v6h6M4 20l6-6M20 10V4h-6M20 4l-6 6M14 20h6v-6',
  dropb: 'M3 21h18M12 3v11M8 10l4 4 4-4M6 17h12',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  x: 'M6 6l12 12M18 6L6 18',
  cam: 'M3 8h4l2-3h6l2 3h4v11H3zM12 10a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z',
  pin: 'M9 4h6l-1 6 3 3H7l3-3zM12 13v8',
  layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5',
  printer: 'M6 9V3h12v6M6 18H4v-7h16v7h-2M8 14h8v7H8z',
  send: 'M4 12l16-8-6 16-3-7z',
  undo: 'M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3',
  redo: 'M15 14l5-5-5-5M20 9H9a5 5 0 0 0 0 10h3',
  lock: 'M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3',
  brush: 'M14 4l6 6-8 8-6-6zM6 12l-2 6 6-2M17 7l-3-3',
  sliders: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  dl: 'M12 4v11M7 10l5 5 5-5M5 20h14',
  file: 'M6 3h8l4 4v14H6zM14 3v4h4',
  up: 'M12 20V8M7 13l5-5 5 5M5 4h14',
  new: 'M12 8v8M8 12h8M5 3h14v18H5z',
};
const icon = (n) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${ICONS[n]}"/></svg>`;
const paintIcons = (root) => root.querySelectorAll('.ic[data-i]').forEach((e) => (e.innerHTML = icon(e.dataset.i)));
paintIcons(document);

// ---------- three.js scene
const cv = $('cv'),
  renderer = new T.WebGLRenderer({canvas: cv, antialias: true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new T.Scene();
scene.background = new T.Color(0x141619);
scene.fog = new T.Fog(0x141619, 700, 1400); // pushed out in view() when several plates are visible
let bedPlates = [],
  overhangs = false; // used by the render loop, which starts right away
const persp = new T.PerspectiveCamera(38, 1, 1, 3000);
persp.up.set(0, 0, 1);
const ortho = new T.OrthographicCamera(-1, 1, 1, -1, -3000, 6000);
ortho.up.set(0, 0, 1);
let cam = persp,
  orthoH = 300; // orthoH = visible height in mm at zoom 1
const ctl = new OrbitControls(cam, cv);
ctl.enableDamping = true;
ctl.maxPolarAngle = Math.PI; // you can always look from below
// gizmo (three.js TransformControls): X/Y arrows to move, X/Y/Z rings to rotate in 15° steps; free-rotate ball and screen ring removed (confusing on a phone)
const tc = new TransformControls(cam, cv);
const SCALE_DAMP = matchMedia('(pointer:coarse)').matches ? 0.25 : 0.5;
let GZ = 'move',
  LAY = false,
  gizmoDown = false,
  pv0 = null,
  zone = null; // GZ: 'move' | 'rotate' | 'scale'; LAY: next tap on the object picks the face to lay on the bed
const pivot = new T.Object3D(); // the gizmo drives this proxy at the object's bbox centre; the delta is applied to the object (rotation about the centre, not the mesh origin)
// snap zone by the finger's distance from the centre, live while dragging: [upper limit, snap, label, ring radius] in gizmo units (rings: ROT_RINGS in TransformControls.js)
const SNAP = [
  [0.52, null, 'free', 0.46],
  [0.64, Math.PI / 36, '5°', 0.58],
  [Infinity, Math.PI / 12, '15°', 0.7],
];
const dot = new T.Mesh(
  new T.SphereGeometry(1, 16, 12),
  new T.MeshBasicMaterial({color: 0xffffff, depthTest: false, depthWrite: false, transparent: true})
);
dot.renderOrder = Infinity;
dot.visible = false;
tc.addEventListener('ring', (e) => {
  // finger position on the ring plane → zone + white dot on that zone's ring
  const k = tc._gizmo.picker.rotate.children[0].scale.x;
  zone = SNAP.find(([lim]) => e.point.length() / k < lim);
  tc.rotationSnap = zone[1];
  tc._gizmo.ringZone = SNAP.indexOf(zone); // the gizmo (not the controls) draws the rings
  dot.position
    .copy(e.point)
    .setLength(zone[3] * k)
    .add(tc.worldPositionStart);
  dot.scale.setScalar(k * 0.05);
  dot.visible = true;
});
for (const g of ['gizmo', 'picker', 'helper'])
  for (const h of [...tc._gizmo[g].rotate.children])
    if (h.name === 'E' || h.name === 'XYZE') tc._gizmo[g].rotate.remove(h);
tc.addEventListener('dragging-changed', (e) => (ctl.enabled = !e.value));
let gzM0 = '';
tc.addEventListener('mouseDown', () => {
  const g = selected.group,
    b = bbox(selected);
  gzM0 = JSON.stringify(getM(g));
  pv0 = {
    p: g.position.clone(),
    q: g.quaternion.clone(),
    s: g.scale.clone(),
    cw: pivot.position.clone(),
    c: pivot.position.clone().sub(plateOffset(selected.plate)),
    a: new T.Vector3((b.min.x + b.max.x) / 2, (b.min.y + b.max.y) / 2, b.min.z).sub(plateOffset(selected.plate)),
  }; // scale anchor = bottom centre: stays on the bed
});
tc.addEventListener('objectChange', () => {
  if (!pv0 || !selected) return;
  const g = selected.group;
  if (tc.mode === 'translate') g.position.copy(pv0.p).add(pivot.position).sub(pv0.cw);
  else if (tc.mode === 'scale') {
    // pivot carries the object's rotation, so its scale delta is along the object's own axes (no shear)
    // three.js scales by the ratio of finger distances from the (small) gizmo centre: +39 % for a 30 px drag. Damp it, finger more than mouse,
    // and round the result to whole percent. ponytail: fixed factors, tune SCALE_DAMP if it still feels off on a given screen
    const sd = pivot.scale
        .clone()
        .subScalar(1)
        .multiplyScalar(SCALE_DAMP)
        .addScalar(1)
        .max(new T.Vector3(0.02, 0.02, 0.02)),
      qi = pv0.q.clone().invert();
    g.scale.copy(pv0.s).multiply(sd).multiplyScalar(100).round().divideScalar(100);
    sd.copy(g.scale).divide(pv0.s);
    g.position.copy(pv0.p).sub(pv0.a).applyQuaternion(qi).multiply(sd).applyQuaternion(pv0.q).add(pv0.a);
    toast(
      g.scale
        .toArray()
        .map((v) => Math.round(v * 100))
        .join(' × ') + ' %'
    );
  } else {
    const qd = pivot.quaternion;
    g.quaternion.copy(qd).multiply(pv0.q);
    g.position.copy(pv0.p).sub(pv0.c).applyQuaternion(qd).add(pv0.c);
    if (zone)
      toast(
        `${Math.round(T.MathUtils.radToDeg(tc.rotationAngle))}° · ${zone[2] === 'free' ? 'free' : zone[2] + ' steps'}`
      );
  }
});
tc.addEventListener('mouseUp', async () => {
  dot.visible = false;
  zone = null;
  const o = selected;
  if (!o || JSON.stringify(getM(o.group)) === gzM0) return;
  const r = await op({op: 'move', id: o.id, m: getM(o.group), plate: o.plate});
  pv0 = null;
  if (r?.msg) toast(r.msg);
  if (S) apply(S);
});
function gizmo() {
  // show on the selected object unless painting / previewing
  const o = selected && GZ && !PM && !PV && !LAY ? selected : null; // hidden while picking a face so the tap reaches the mesh
  if (!o) {
    tc.detach();
  } else {
    if (!tc.dragging) {
      pivot.position.copy(bbox(o).getCenter(new T.Vector3()));
      pivot.scale.set(1, 1, 1);
      if (GZ === 'scale') pivot.quaternion.copy(o.group.quaternion);
      else pivot.quaternion.identity();
    }
    tc.attach(pivot);
    tc.setMode({move: 'translate', rotate: 'rotate', scale: 'scale'}[GZ]);
    tc.setSize(GZ === 'rotate' ? 0.85 : 0.7); // rotate bigger: three ring zones need finger room
  }
  const gb = document.querySelector('[data-a=gz]'),
    ICN = {move: 'move', rotate: 'rot3', scale: 'scale'};
  gb.title = `${GZ[0].toUpperCase() + GZ.slice(1)} — tap to pick move / rotate / scale`;
  gb.firstElementChild.innerHTML = icon(ICN[GZ]);
  for (const b of document.querySelectorAll('#gzMenu [data-a]')) b.classList.toggle('on', b.dataset.a === 'gz-' + GZ);
  document.querySelector('[data-a=lay]').classList.toggle('on', LAY);
}
scene.add(new T.HemisphereLight(0xffffff, 0x30343a, 1.5));
const dl = new T.DirectionalLight(0xffffff, 1.6);
dl.position.set(120, -220, 320);
scene.add(dl);
const dl2 = new T.DirectionalLight(0xffffff, 0.5);
dl2.position.set(-200, 200, 120);
scene.add(dl2);

let S = null,
  mix = [],
  objs = [],
  selected = null,
  wipeMeshes = [],
  projName = '',
  curPlate = 1,
  plateGroups = [],
  plateKey = '',
  lastView = 'iso';
const root = new T.Group();
scene.add(root);
scene.add(tc.getHelper());
scene.add(pivot);
scene.add(dot);

function resize() {
  const w = innerWidth,
    h = innerHeight,
    sheet = $('sheet').getBoundingClientRect();
  renderer.setSize(w, h, false);
  persp.aspect = w / h;
  persp.updateProjectionMatrix();
  if (cam === ortho)
    Object.assign(ortho, {
      left: (-orthoH * w) / h / 2,
      right: (orthoH * w) / h / 2,
      top: orthoH / 2,
      bottom: -orthoH / 2,
    });
  // keep the model centred in the free area above the bottom sheet (phones) / left of the side panel (desktop)
  const wide = WIDE.matches,
    dy = wide ? 0 : (h - sheet.top) / 2 - 30,
    dx = wide ? sheet.width / 2 - 30 : -30; // also clear the left tool rail
  cam.setViewOffset(w, h, dx, dy, w, h);
  cam.updateProjectionMatrix();
}
addEventListener('resize', resize);
new ResizeObserver(resize).observe($('sheet'));
$('sheet').addEventListener('transitionend', resize);
resize();
(function loop() {
  ctl.update();
  for (const bp of bedPlates) {
    // looking from below (or overhang view): the bed plates become see-through
    const see = overhangs || cam.position.z < 0;
    if (bp.material.transparent !== see)
      Object.assign(bp.material, {transparent: see, opacity: see ? 0.25 : 1, needsUpdate: true});
  }
  renderer.render(scene, cam);
  requestAnimationFrame(loop);
})();

// ---------- colours, mixes
const nPhys = () => S.filaments.length;
const hex2 = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
let MIXER = null;
fetch('mixer.json')
  .then((r) => r.json())
  .then((m) => {
    MIXER = m;
    if (S) refresh();
  });
function blend(a, b, pct) {
  // FilamentMixer pigment blend (Snapmaker Orca's model); RGB average until the coefficients load
  const x = [...hex2(a), ...hex2(b), pct / 100];
  if (pct <= 0) return a;
  if (pct >= 100) return b;
  if (!MIXER)
    return (
      '#' +
      hex2(a)
        .map((v, i) =>
          Math.round((v * (100 - pct)) / 100 + (hex2(b)[i] * pct) / 100)
            .toString(16)
            .padStart(2, '0')
        )
        .join('')
    );
  const out = [0, 0, 0].map((_, c) => MIXER.intercept[c]);
  for (let i = 0; i < MIXER.powers.length; i++) {
    let f = 1;
    const pw = MIXER.powers[i];
    for (let j = 0; j < 7; j++) if (pw[j]) f *= x[j] ** pw[j];
    for (let c = 0; c < 3; c++) out[c] += f * MIXER.coef[i][c];
  }
  return (
    '#' +
    out
      .map((v) =>
        Math.max(0, Math.min(255, Math.trunc(v)))
          .toString(16)
          .padStart(2, '0')
      )
      .join('')
  );
}
const fcol = (n) => S.filaments[n - 1]?.colour || '#888';
const colour = (n) => {
  if (n <= nPhys()) return fcol(n);
  const k = n - nPhys() - 1;
  if (S.mix_colours?.[k]) return S.mix_colours[k];
  const m = mix[k];
  return m ? blend(fcol(m.a), fcol(m.b), m.pct) : '#888';
};
const ink = (c) => {
  const [r, g, b] = hex2(c);
  return r * 0.3 + g * 0.59 + b * 0.11 > 150 ? '#141619' : '#fff';
};
const chipBg = (n) => {
  // mix colour + a corner striped with its components
  if (n <= nPhys()) return fcol(n);
  const m = mix[n - nPhys() - 1],
    st = 28 / m.ids.length;
  return `linear-gradient(135deg, ${colour(n)} 0 72%, ${m.ids.map((id, i) => `${fcol(id)} ${72 + i * st}% ${72 + (i + 1) * st}%`).join(', ')})`;
};
// mix rows (Orca mixed_filament_definitions): pairs 'a,b,en,custom,pctB'; 3-4 components add 'g<ids>' + 'w<w1/w2/..>'
function parseMix(s) {
  return s
    .split(';')
    .filter(Boolean)
    .map((r) => {
      const t = r.split(','),
        a = +t[0],
        b = +t[1],
        pct = +(t.length === 4 ? t[3] : t[4]);
      const g = (t.slice(5).find((x) => /^g./i.test(x)) || '').slice(1),
        w = (t.slice(5).find((x) => /^w./i.test(x)) || '').slice(1);
      const gi = g ? (g.includes('/') ? g.split('/').filter(Boolean).map(Number) : [...g].map(Number)) : [];
      let ids = [a, b],
        ws = [100 - pct, pct];
      if (gi.length >= 3) {
        ids = gi;
        ws = w ? w.split('/').map(Number) : gi.map(() => 1);
      }
      const tot = ws.reduce((p, q) => p + q, 0) || 1;
      return {
        raw: r,
        en: t[2] !== '0',
        ids,
        weights: ws.map((x) => Math.round((100 * x) / tot)),
        a: ids[0],
        b: ids[1],
        pct,
      };
    })
    .filter((m) => m.en && m.ids.every(Boolean));
}
const mixLabel = (m) => `${m.ids.join('+')} · ${m.weights.join('/')} %`;
const fname = (n) => (n <= nPhys() ? `${S.filaments[n - 1].type}` : mixLabel(mix[n - nPhys() - 1]));
const sameRecipe = (m, ids, ws) => {
  const k = (i, w) =>
    i
      .map((x, j) => `${x}:${w[j]}`)
      .sort()
      .join(',');
  return k(m.ids, m.weights) === k(ids, ws);
};
function blendMulti(ids, ws) {
  // Orca blend_color_multi: weighted pairwise pigment blend, heaviest first
  const p = ids
    .map((id, i) => [id, ws[i]])
    .filter((x) => x[1] > 0)
    .sort((x, y) => y[1] - x[1] || x[0] - y[0]);
  if (!p.length) return '#000000';
  let acc = fcol(p[0][0]),
    tot = p[0][1];
  for (const [id, w] of p.slice(1)) {
    acc = blend(acc, fcol(id), (100 * w) / (tot + w));
    tot += w;
  }
  return acc;
}

// ---------- UI helpers
let toastT;
function toast(t, err) {
  const e = $('toast');
  e.textContent = t;
  e.className = err ? 'err' : '';
  e.hidden = false;
  clearTimeout(toastT);
  toastT = setTimeout(() => (e.hidden = true), err ? 6000 : 2500);
}
function summary() {
  if (!S) return;
  $('sumTitle').textContent = projName || 'New project';
  const p = objs.reduce((a, o) => a + o.parts.length, 0);
  $('sumSub').textContent =
    `${objs.length} objects · ${p} parts · ${nPhys()} filaments${mix.length ? ` + ${mix.length} mix` : ''}`;
}
function modal(title, body) {
  $('mtitle').textContent = title;
  $('mbody').innerHTML = '';
  $('mbody').append(body);
  $('modal').hidden = false;
}
const closeModal = () => ($('modal').hidden = true);
$('mclose').onclick = closeModal;
$('modal').onclick = (e) => {
  if (e.target === $('modal')) closeModal();
};

// sheet: tap / drag the handle between peek, half, full
const states = ['peek', 'half', 'full'];
let gy = null;
$('grab').onpointerdown = (e) => {
  gy = e.clientY;
  $('grab').setPointerCapture(e.pointerId);
};
$('grab').onpointerup = (e) => {
  const d = gy == null ? 0 : e.clientY - gy,
    i = states.indexOf($('sheet').dataset.state);
  gy = null;
  $('sheet').dataset.state =
    Math.abs(d) < 8 ? states[(i + 1) % 3] : states[Math.max(0, Math.min(2, i + (d < 0 ? 1 : -1)))];
};
$('tabs').onclick = (e) => {
  const t = e.target.dataset.t;
  if (!t) return;
  if (t === 'fil') loadPrinter();
  for (const b of $('tabs').children) b.classList.toggle('on', b.dataset.t === t);
  for (const k of ['obj', 'fil', 'prn']) $('tab-' + k).hidden = k !== t;
};

// ---------- 3MF matrix (12 numbers, row vectors) <-> three.js
function setM(g, m) {
  g.matrix.set(m[0], m[3], m[6], m[9], m[1], m[4], m[7], m[10], m[2], m[5], m[8], m[11], 0, 0, 0, 1);
  g.matrix.decompose(g.position, g.quaternion, g.scale);
}
function getM(g) {
  g.updateMatrix();
  const e = g.matrix.elements;
  return [e[0], e[1], e[2], e[4], e[5], e[6], e[8], e[9], e[10], e[12], e[13], e[14]];
}
const bbox = (o) => {
  o.group.updateMatrixWorld(true);
  return new T.Box3().setFromObject(o.group);
};

// ---------- server state -> scene (the server is the single source of truth; this page only renders it and sends ops)
const geoCache = {};
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
function geoFor(gid) {
  return (geoCache[gid] ??= fetch('/api/geo/' + gid)
    .then((r) => r.json())
    .then((g) =>
      g.parts.map((p) => {
        const geo = new T.BufferGeometry();
        geo.setAttribute('position', new T.BufferAttribute(new Float32Array(b64(p.pos).buffer), 3));
        geo.computeVertexNormals();
        return {geo, paint: p.paint, type: p.type || 'normal_part'};
      })
    )
    .catch((e) => {
      delete geoCache[gid];
      throw e;
    })); // never cache a failure
}
function material() {
  return new T.MeshStandardMaterial({roughness: 0.55, metalness: 0.02, side: T.DoubleSide});
}
function makeObj(o, parts) {
  const g = new T.Group();
  root.add(g);
  const ob = {id: o.id, gid: o.gid, group: g, parts: []};
  parts.forEach(({geo, paint: pp, type}) => {
    const own = new T.BufferGeometry();
    own.setAttribute('position', geo.getAttribute('position'));
    own.setAttribute('normal', geo.getAttribute('normal'));
    const paint = pp ? b64(pp.s) : null;
    if (paint) own.setAttribute('color', new T.BufferAttribute(new Float32Array(paint.length * 9), 3)); // own colours per instance
    const mat = material();
    mat.vertexColors = !!paint;
    if (type !== 'normal_part') Object.assign(mat, {transparent: true, opacity: 0.38, depthWrite: false}); // modifiers & co. are see-through volumes
    const mesh = new T.Mesh(own, mat);
    mesh.userData.obj = ob;
    if (type !== 'normal_part') mesh.renderOrder = 2;
    g.add(mesh);
    const part = {mesh, paint, type};
    ob.parts.push(part);
    setLeaves(part, pp);
  });
  return ob;
}
const byId = (id) => objs.find((o) => o.id === id);

let loading = 0;
async function apply(st) {
  const seq = ++loading;
  // only objects that are new or whose mesh (shape) changed need geometry; paint-only changes fetch colours
  try {
    await busy(
      Promise.all(
        st.objects
          .filter((so) => {
            const o = byId(so.id);
            return !o || o.shape !== so.shape;
          })
          .map((so) => geoFor(so.gid))
      )
    );
  } catch (e) {
    if (seq === loading) toast('Could not load geometry, retrying…', true);
    setTimeout(() => seq === loading && apply(st), 1500);
    return;
  }
  if (seq !== loading) return; // a newer state arrived meanwhile
  S = st;
  mix = parseMix(st.mix || '');
  projName = st.name || '';
  $('projName').textContent = projName || 'New project';
  const firstPlates = !plateGroups.length;
  if (buildPlates(st) && firstPlates) view('iso');
  // reconcile objects
  const want = new Map(st.objects.map((o) => [o.id, o]));
  for (const o of objs.filter((o) => !want.has(o.id) || want.get(o.id).shape !== o.shape)) {
    o.group.removeFromParent();
    objs.splice(objs.indexOf(o), 1);
  }
  for (const so of st.objects) {
    let o = byId(so.id);
    if (!o) {
      o = makeObj(so, await geoFor(so.gid));
      o.shape = so.shape;
      o.gid = so.gid;
      objs.push(o);
    } else if (o.gid !== so.gid) {
      const g = so.gid;
      o.gid = g;
      if (!(PM && PM.o === o && PM.busy)) refreshPaint(o, g);
    } // same mesh, new paint/names (incl. undo/redo)
    o.lock = so.lock || null;
    o.role = so.role || null;
    Object.assign(o, {name: so.name, m: so.m, cfg: so.cfg, pcfg: so.pcfg || []});
    o.parts.forEach((p, i) => {
      p.extruder = so.ext[i];
      p.name = so.parts[i].name;
      p.type = so.parts[i].type;
      p.cfg = (so.pcfg || [])[i] || {};
    });
    o.plate = so.plate || 1;
    const pg = plateGroups[o.plate - 1] || plateGroups[0];
    if (drag?.o !== o && !(tc.dragging && selected === o)) {
      if (o.group.parent !== pg) pg.add(o.group);
      setM(o.group, so.m);
    } // a state push mid-drag must not snap the object back
  }
  objs.sort((a, c) => st.objects.findIndex((o) => o.id === a.id) - st.objects.findIndex((o) => o.id === c.id));
  if (selected && !byId(selected.id)) selected = null;
  else if (selected) selected = byId(selected.id);
  if (PM && PM.o !== byId(PM.o.id)) {
    const n = byId(PM.o.id);
    if (n) {
      PM.o = n;
      pbTri();
    } else closePaint();
  }
  // wipe tower: same spot on every plate (one shared position)
  wipeMeshes.forEach((w, i) => (w.visible = st.wipe.enabled && !PV && objs.some((o) => o.plate === i + 1)));
  if (wipeMeshes.length && !drag?.wipe) showWipe(st.wipe.x, st.wipe.y);
  $('slice').disabled = $('save').disabled = false;
  $('undo').disabled = !st.can_undo;
  $('redo').disabled = !st.can_redo;
  globalSettings();
  refresh();
  if (PROFS) profilesCard();
  else loadProfiles();
  // last slice result
  $('modeSeg').lastElementChild.disabled = !st.result?.ok;
  $('modeSeg').lastElementChild.textContent = st.result?.stale ? 'Layers (old)' : 'Layers';
  if (st.result) showResult(st.result);
  else {
    $('result').hidden = true;
    $('slice').classList.remove('quiet', 'attn');
    if (PV) closePreview();
  }
}

// ---------- plates: Orca's grid (~sqrt(n) columns, 1/5 gap); objects live in plate-local coordinates
const plateCols = (n) => {
  const v = Math.sqrt(n),
    r = Math.round(v);
  return v > r ? r + 1 : Math.max(1, r);
};
function plateOffset(p) {
  const n = S?.plates || 1,
    c = plateCols(n),
    i = p - 1,
    b = S.bed;
  return new T.Vector3((i % c) * (b.x1 - b.x0) * 1.2, -Math.floor(i / c) * (b.y1 - b.y0) * 1.2, 0);
}
function plateLabel(n) {
  const cv2 = document.createElement('canvas');
  cv2.width = cv2.height = 128;
  const g = cv2.getContext('2d');
  g.fillStyle = 'rgba(255,255,255,.12)';
  g.beginPath();
  g.arc(64, 64, 60, 0, 7);
  g.fill();
  g.fillStyle = '#c9d0d6';
  g.font = 'bold 72px system-ui';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText(n, 64, 68);
  const s = new T.Sprite(new T.SpriteMaterial({map: new T.CanvasTexture(cv2), depthWrite: false}));
  s.scale.set(22, 22, 1);
  return s;
}
function buildPlates(st) {
  const key = (st.plates || 1) + JSON.stringify(st.bed) + (st.wipe.enabled ? 'w' : '');
  if (key === plateKey) return false;
  plateKey = key;
  for (const g of plateGroups) {
    for (const o of objs) if (o.group.parent === g) root.add(o.group);
    root.remove(g);
  }
  plateGroups = [];
  bedPlates = [];
  wipeMeshes = [];
  for (let p = 1; p <= (st.plates || 1); p++) {
    const g = new T.Group();
    g.position.copy(plateOffset(p));
    g.userData.plate = p;
    const bm = bedMesh(st.bed);
    g.add(bm);
    bedPlates.push(bm.userData.plate);
    if ((st.plates || 1) > 1) {
      const l = plateLabel(p);
      l.position.set(st.bed.x0 + 14, st.bed.y0 - 16, 0);
      g.add(l);
    }
    if (st.wipe.enabled) {
      const w = new T.Mesh(
        new T.BoxGeometry(1, 1, 40),
        new T.MeshStandardMaterial({color: 0xffffff, transparent: true, opacity: 0.18, roughness: 1})
      );
      w.add(new T.LineSegments(new T.EdgesGeometry(w.geometry), new T.LineBasicMaterial({color: 0x9aa3ab})));
      g.add(w);
      wipeMeshes.push(w);
    }
    root.add(g);
    plateGroups.push(g);
  }
  if (curPlate > plateGroups.length) curPlate = plateGroups.length;
  return true;
}
function plateAt(world) {
  // plate whose bed contains this world point
  const b = S.bed;
  for (let p = 1; p <= (S.plates || 1); p++) {
    const o = plateOffset(p);
    if (world.x >= b.x0 + o.x && world.x <= b.x1 + o.x && world.y >= b.y0 + o.y && world.y <= b.y1 + o.y) return p;
  }
  return null;
}
function setPlate(p) {
  curPlate = p;
  view(lastView);
  objList();
}

function bedMesh(b) {
  const cx = (b.x0 + b.x1) / 2,
    cy = (b.y0 + b.y1) / 2,
    g = new T.Group();
  const shape = new T.Shape(),
    r = 8;
  shape.moveTo(b.x0 + r, b.y0);
  shape.lineTo(b.x1 - r, b.y0);
  shape.quadraticCurveTo(b.x1, b.y0, b.x1, b.y0 + r);
  shape.lineTo(b.x1, b.y1 - r);
  shape.quadraticCurveTo(b.x1, b.y1, b.x1 - r, b.y1);
  shape.lineTo(b.x0 + r, b.y1);
  shape.quadraticCurveTo(b.x0, b.y1, b.x0, b.y1 - r);
  shape.lineTo(b.x0, b.y0 + r);
  shape.quadraticCurveTo(b.x0, b.y0, b.x0 + r, b.y0);
  const plate = new T.Mesh(
    new T.ExtrudeGeometry(shape, {depth: 3, bevelEnabled: false}),
    new T.MeshStandardMaterial({color: 0x24282d, roughness: 0.9})
  );
  plate.position.z = -3.05;
  g.add(plate);
  g.userData.plate = plate;
  const pts = [];
  for (let x = Math.ceil(b.x0 / 10) * 10; x <= b.x1; x += 10) pts.push(x, b.y0, 0, x, b.y1, 0);
  for (let y = Math.ceil(b.y0 / 10) * 10; y <= b.y1; y += 10) pts.push(b.x0, y, 0, b.x1, y, 0);
  const lg = new T.BufferGeometry();
  lg.setAttribute('position', new T.Float32BufferAttribute(pts, 3));
  g.add(new T.LineSegments(lg, new T.LineBasicMaterial({color: 0x3a3f46})));
  const ax = new T.BufferGeometry();
  ax.setAttribute(
    'position',
    new T.Float32BufferAttribute([cx, b.y0, 0.05, cx, b.y1, 0.05, b.x0, cy, 0.05, b.x1, cy, 0.05], 3)
  );
  g.add(new T.LineSegments(ax, new T.LineBasicMaterial({color: 0x4c525a})));
  // orientation hints lying on the bed; FRONT = low y (door side), each word reads facing outward from the bed
  for (const [txt, x, y, rot] of [
    ['FRONT', cx, b.y0 + 12, 0],
    ['BACK', cx, b.y1 - 12, Math.PI],
    ['LEFT', b.x0 + 12, cy, -Math.PI / 2],
    ['RIGHT', b.x1 - 12, cy, Math.PI / 2],
  ]) {
    const c = document.createElement('canvas');
    c.width = 256;
    c.height = 64;
    const q = c.getContext('2d');
    q.fillStyle = 'rgba(201,208,214,.55)';
    q.font = 'bold 44px system-ui';
    q.textAlign = 'center';
    q.textBaseline = 'middle';
    q.fillText(txt, 128, 34);
    const m = new T.Mesh(
      new T.PlaneGeometry(40, 10),
      new T.MeshBasicMaterial({map: new T.CanvasTexture(c), transparent: true, depthWrite: false})
    );
    m.position.set(x, y, 0.1);
    m.rotation.z = rot;
    g.add(m);
  }
  return g;
}

function view(v) {
  if (!S) return;
  lastView = v;
  {
    const k = plateCols(S.plates || 1) * 400;
    scene.fog.near = 700 * Math.max(1, k / 400);
    scene.fog.far = 1400 + k * 2;
  }
  const b = S.bed,
    po = plateOffset(curPlate),
    cx = (b.x0 + b.x1) / 2 + po.x,
    cy = (b.y0 + b.y1) / 2 + po.y,
    size = Math.max(b.x1 - b.x0, b.y1 - b.y0);
  const hf = 2 * Math.atan(Math.tan((persp.fov * Math.PI) / 360) * persp.aspect),
    dist = (size * 0.52) / Math.tan(Math.min(hf, (persp.fov * Math.PI) / 180) / 2);
  const p = {
    iso: [cx + dist * 0.3, cy - dist * 0.66, dist * 0.7],
    top: [cx, cy - 0.01, dist * 1.05],
    front: [cx, cy - dist, size * 0.12],
  }[v];
  cam.position.set(...p);
  ctl.target.set(cx, cy, 8);
  if (cam === ortho) {
    orthoH = 2 * dist * Math.tan((persp.fov * Math.PI) / 360);
    ortho.zoom = 1;
    resize();
  }
  ctl.update();
  for (const b of $('views').children)
    if (!['ovh', 'ortho'].includes(b.dataset.v)) b.classList.toggle('on', b.dataset.v === v);
}
$('views').onclick = (e) => {
  const v = e.target.dataset.v;
  if (!v) return;
  if (v === 'ortho') {
    setOrtho(cam !== ortho);
    e.target.classList.toggle('on', cam === ortho);
    return;
  }
  if (v === 'ovh') {
    overhangs = !overhangs;
    e.target.classList.toggle('on', overhangs);
    recolour();

    if (overhangs)
      toast(
        `White body, red = overhang below ${ovhAngle()}° from horizontal (support_threshold_angle) — orbit under the bed to see it`
      );
    return;
  }
  view(v);
};
function setOrtho(on) {
  // same framing when switching: ortho height = perspective view height at the target distance
  const from = cam,
    dir = from.position.clone().sub(ctl.target),
    tanh = Math.tan((persp.fov * Math.PI) / 360);
  if (on && from === persp) {
    orthoH = 2 * dir.length() * tanh;
    ortho.position.copy(persp.position);
    ortho.quaternion.copy(persp.quaternion);
    ortho.zoom = 1;
    cam = ortho;
  } else if (!on && from === ortho) {
    const d = orthoH / ortho.zoom / (2 * tanh);
    persp.position.copy(ctl.target).addScaledVector(dir.normalize(), d);
    persp.quaternion.copy(ortho.quaternion);
    cam = persp;
  }
  ctl.object = cam;
  tc.camera = cam;
  resize();
  ctl.update();
  toast(on ? 'Orthographic view' : 'Perspective view');
}
const ovhAngle = () => +(S?.overrides?.support_threshold_angle ?? S?.settings?.support_threshold_angle ?? 30) || 30;

function showWipe(x, y) {
  const f = S.wipe.fp;
  for (const w of wipeMeshes) {
    w.scale.set(f[1] - f[0], f[3] - f[2], 1);
    w.position.set(x + (f[0] + f[1]) / 2, y + (f[2] + f[3]) / 2, 20);
  }
  $('wx').value = Math.round(x);
  $('wy').value = Math.round(y);
}
$('wx').onchange = $('wy').onchange = () => op({op: 'set_wipe', x: +$('wx').value, y: +$('wy').value});

// ---------- panels
function refresh() {
  recolour();
  objList();
  filTab();
  summary();
  gizmo();
  for (const b of document.querySelectorAll('#rail .sel')) {
    b.disabled = false;
    b.classList.toggle('off', !selected);
  }
  document.querySelector('[data-a=arr]').disabled = !objs.length;
}
function recolour() {
  const lim = -Math.cos((ovhAngle() * Math.PI) / 180),
    red = new T.Color('#ff3b30'),
    nm = new T.Matrix3(),
    nv = new T.Vector3(),
    pv = new T.Vector3();
  for (const o of objs)
    for (const p of o.parts) {
      if (o.role) {
        const tc = {
          modifier_part: '#ffd166',
          negative_part: '#9aa3ab',
          support_blocker: '#ff4d4d',
          support_enforcer: '#4cd964',
        }[o.role];
        Object.assign(p.mesh.material, {transparent: true, opacity: 0.4, depthWrite: false});
        p.mesh.material.color.set(tc);
        p.mesh.renderOrder = 2;
        continue;
      }
      const seeThrough = selected === o && o.parts.some((x) => x.type !== 'normal_part'); // show the volumes inside the selected object
      const dim = selected && selected !== o; // unselected objects fade out
      const op_ = dim ? 0.22 : seeThrough ? 0.3 : 1;
      if (p.type === 'normal_part' && p.mesh.material.opacity !== op_)
        Object.assign(p.mesh.material, {transparent: op_ < 1, opacity: op_, depthWrite: op_ === 1, needsUpdate: true});
      if (p.overlay && p.overlay.material.opacity !== op_)
        Object.assign(p.overlay.material, {
          transparent: op_ < 1,
          opacity: op_,
          depthWrite: op_ === 1,
          needsUpdate: true,
        });
      if (p.type !== 'normal_part') {
        const tc =
          {
            modifier_part: p.type === 'modifier_part' ? colour(p.extruder) : '#ffd166',
            negative_part: '#9aa3ab',
            support_blocker: '#ff4d4d',
            support_enforcer: '#4cd964',
          }[p.type] || '#ffd166';
        p.mesh.material.color.set(tc);
        p.mesh.material.opacity = dim ? 0.12 : 0.38;
        continue;
      }
      if (overhangs) {
        // faces pointing down steeper than the support threshold (and not lying on the bed) turn red
        const g = p.mesh.geometry,
          pos = g.getAttribute('position'),
          nrm = g.getAttribute('normal'),
          n = pos.count / 3;
        if (!g.getAttribute('color'))
          g.setAttribute('color', new T.BufferAttribute(new Float32Array(pos.count * 3), 3));
        const c = g.getAttribute('color');
        o.group.updateMatrixWorld(true);
        nm.getNormalMatrix(o.group.matrixWorld);
        const base = new T.Color('#f2f2f2'); // overhang view: neutral white body so red stays readable on red filaments
        for (let t = 0; t < n; t++) {
          nv.fromBufferAttribute(nrm, t * 3)
            .applyMatrix3(nm)
            .normalize();
          pv.fromBufferAttribute(pos, t * 3).applyMatrix4(o.group.matrixWorld);
          const v = nv.z < lim && pv.z > 0.3 ? red : base;
          for (let j = 0; j < 3; j++) c.setXYZ(t * 3 + j, v.r, v.g, v.b);
        }
        c.needsUpdate = true;
        p.mesh.material.vertexColors = true;
        p.mesh.material.color.set(0xffffff);
        p.mesh.material.needsUpdate = true;
      } else if (p.paint) {
        // painted part: per-triangle colours, unpainted triangles take the part's filament
        p.mesh.material.color.set(0xffffff);
        const c = p.mesh.geometry.getAttribute('color'),
          cache = {},
          col = new T.Color();
        for (let t = 0; t < p.paint.length; t++) {
          const k = p.paint[t] && p.paint[t] !== 255 ? p.paint[t] : p.extruder,
            v = (cache[k] ??= col.set(colour(k)).clone());
          for (let j = 0; j < 3; j++) c.setXYZ(t * 3 + j, v.r, v.g, v.b);
        }
        c.needsUpdate = true;
      } else {
        if (p.mesh.material.vertexColors) {
          p.mesh.material.vertexColors = false;
          p.mesh.material.needsUpdate = true;
        }
        p.mesh.material.color.set(colour(p.extruder));
      }
      if (p.paint && !p.mesh.material.vertexColors) {
        p.mesh.material.vertexColors = true;
        p.mesh.material.needsUpdate = true;
      }
      colourLeaves(p);
      if (p.overlay) p.overlay.visible = !overhangs;
    }
}

function chip(n, onPick, multi) {
  const c = el('button', 'chip', n || '–');
  if (n) {
    c.style.background = chipBg(n);
    c.style.color = n > nPhys() ? '#fff' : ink(fcol(n));
    if (n > nPhys()) c.style.textShadow = '0 1px 2px #000';
  } else if (multi) {
    const cs = [...new Set(multi)].map(colour),
      st = 100 / cs.length;
    c.style.background = `linear-gradient(90deg, ${cs.map((x, i) => `${x} ${i * st}% ${(i + 1) * st}%`).join(',')})`;
    c.textContent = '';
  } else c.style.background = 'rgba(255,255,255,.08)';
  c.onclick = (e) => {
    e.stopPropagation();
    pickFilament(n, onPick);
  };
  return c;
}
function pickFilament(cur, onPick) {
  const g = el('div', 'grid');
  for (let i = 1; i <= nPhys() + mix.length; i++) {
    const b = el('button', cur === i ? 'on' : '');
    b.style.background = chipBg(i);
    b.style.color = i > nPhys() ? '#fff' : ink(fcol(i));
    if (i > nPhys()) b.style.textShadow = '0 1px 2px #000';
    b.innerHTML = `${i}<small>${fname(i)}</small>`;
    b.onclick = () => {
      onPick(i);
      closeModal();
    };
    g.append(b);
  }
  modal('Filament', g);
}

const open = new Set();
const PTYPE = {
  modifier_part: 'Modifier',
  negative_part: 'Negative',
  support_blocker: 'Blocker',
  support_enforcer: 'Enforcer',
  normal_part: 'Part',
};
function objList() {
  const L = $('tab-obj');
  L.innerHTML = '';
  if (!objs.length && (S?.plates || 1) === 1) {
    L.append(el('div', 'empty', 'Empty plate — add an object with + or open a project'));
    return;
  }
  const n = S?.plates || 1;
  for (let p = 1; p <= n; p++) {
    const on = objs.filter((o) => o.plate === p);
    if (n > 1) {
      const h = el('div', 'plh' + (p === curPlate ? ' on' : ''));
      h.append(
        el('b', '', `Plate ${p}`),
        el('small', 'mut', `${on.length} object${on.length === 1 ? '' : 's'}`),
        el('span', 'grow')
      );
      const ar = el('button', 'ibtn');
      ar.innerHTML = `<span class="ic">${icon('grid')}</span>`;
      ar.title = 'Arrange this plate';
      ar.onclick = async (e) => {
        e.stopPropagation();
        curPlate = p;
        const r = await op({op: 'arrange', plate: p});
        if (r) toast(r.msg);
      };
      const dl = el('button', 'ibtn');
      dl.innerHTML = `<span class="ic">${icon('trash')}</span>`;
      dl.title = 'Delete plate (and its objects)';
      dl.onclick = async (e) => {
        e.stopPropagation();
        if (on.length && !confirm(`Delete plate ${p} with ${on.length} object(s)?`)) return;
        const r = await op({op: 'del_plate', plate: p});
        if (r) toast(r.msg);
      };
      h.append(ar, dl);
      h.onclick = () => setPlate(p);
      L.append(h);
      if (!on.length) L.append(el('div', 'empty sm', 'Empty — drag objects here or add with +'));
    }
    objRows(L, on);
  }
  const bar = el('div', 'plbar'),
    np = el('button', 'btn2'),
    aa = el('button', 'btn2');
  np.innerHTML = `<span class="ic">${icon('plus')}</span>Plate`;
  np.onclick = async () => {
    const r = await op({op: 'add_plate'});
    if (r) {
      toast(r.msg);
      curPlate = S.plates + 1;
    }
  };
  aa.innerHTML = `<span class="ic">${icon('grid')}</span>Arrange all plates`;
  aa.title = 'Repack every object onto as few plates as possible';
  aa.onclick = async () => {
    const r = await op({op: 'arrange', all: true});
    if (r) toast(r.msg);
  };
  bar.append(np, aa);
  L.append(bar);
}
function objRows(L, list) {
  for (const o of list) {
    const multi = o.parts.length > 1,
      e0 = o.parts[0].extruder,
      same = o.parts.every((p) => p.extruder === e0);
    const r = el('div', 'orow' + (selected === o ? ' on' : ''));
    const ex = el('button', 'exp' + (open.has(o.id) ? ' open' : ''));
    ex.innerHTML = multi ? icon('chev').replace('M6 9l6 6 6-6', 'M9 6l6 6-6 6') : '';
    ex.onclick = (e) => {
      e.stopPropagation();
      if (multi) {
        open.has(o.id) ? open.delete(o.id) : open.add(o.id);
        objList();
      }
    };
    const sb = el('button', 'ibtn');
    sb.innerHTML = `<span class="ic">${icon('sliders')}</span>`;
    sb.title = 'Settings';
    sb.onclick = (e) => {
      e.stopPropagation();
      selected = o;
      refresh();
      objectModal(o);
    };
    const nm = el('span', 'n', o.name + (o.cfg && Object.keys(o.cfg).length ? ' •' : ''));
    if (o.lock) {
      const lk = el('span', 'ptype lock');
      lk.innerHTML = `${icon('lock').replace('<svg', '<svg width="11" height="11" style="vertical-align:-1px"')} ${o.lock.by}`;
      lk.title = 'Checked out — edits are blocked until it is checked in or released';
      nm.prepend(lk);
    }
    r.append(
      ex,
      nm,
      sb,
      chip(same ? e0 : 0, (k) => op({op: 'set_ext', id: o.id, ext: k}), same ? null : o.parts.map((p) => p.extruder))
    );
    r.onclick = () => {
      selected = selected === o ? null : o;
      refresh();
    };
    L.append(r);
    if (multi && open.has(o.id))
      o.parts.forEach((p, i) => {
        const pr = el('div', 'orow part'),
          nm = el('span', 'n', p.name + (Object.keys(p.cfg || {}).length ? ' •' : ''));
        if (p.type !== 'normal_part') nm.prepend(el('span', 'ptype ' + p.type, PTYPE[p.type]));
        const del = el('button', 'ibtn');
        del.innerHTML = `<span class="ic">${icon('trash')}</span>`;
        del.title = 'Remove part';
        del.onclick = async (e) => {
          e.stopPropagation();
          const r = await op({op: 'del_part', id: o.id, part: i});
          if (r) toast(r.msg);
        };
        const st = el('button', 'ibtn');
        st.innerHTML = `<span class="ic">${icon('sliders')}</span>`;
        st.title = 'Part settings';
        st.onclick = (e) => {
          e.stopPropagation();
          partModal(o, i);
        };
        pr.append(
          nm,
          ...(p.type !== 'normal_part' ? [st] : []),
          del,
          ...(['negative_part', 'support_blocker', 'support_enforcer'].includes(p.type)
            ? []
            : [chip(p.extruder, (k) => op({op: 'set_ext', id: o.id, part: i, ext: k}))])
        );
        L.append(pr);
      });
  }
}

let PR = null; // last printer status
async function loadPrinter() {
  const r = await fetch('/api/printer');
  PR = await r.json();
  filTab();
}
// ---- Monitor: camera (~1 fps) + printer status, as a modal or pinned as a small floating window
// camera polls only while its <img> is on the page and the page is visible; the server keeps the U1 camera awake
function camView() {
  const im = el('img', 'cam');
  let busy = false,
    n = 0;
  const tick = () => {
    if (!im.isConnected) return n++ > 3 ? clearInterval(iv) : 0; // not attached yet on the first ticks
    if (busy || document.hidden || !im.getClientRects().length) return; // closed modal = not rendered
    busy = true;
    im.onload = im.onerror = () => {
      busy = false;
    };
    im.src = '/api/printer/camera.jpg?' + Date.now();
  };
  const iv = setInterval(tick, 1000);
  return im;
}
const TNAME = {
  extruder: 'T1',
  extruder1: 'T2',
  extruder2: 'T3',
  extruder3: 'T4',
  heater_bed: 'Bed',
  chamber: 'Chamber',
};
// "2h 21m left · done 14:52" — day named when it's not today ("tomorrow 02:10", "Thu 09:30")
function eta(s, full) {
  const h = Math.floor(s / 3600),
    m = Math.round((s % 3600) / 60),
    left = h ? `${h}h ${m}m` : `${m}m`;
  const t = new Date(Date.now() + s * 1000),
    now = new Date(),
    hm = t.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
  const days = Math.round((new Date(t).setHours(0, 0, 0, 0) - new Date(now).setHours(0, 0, 0, 0)) / 864e5);
  const when =
    days === 0 ? hm : days === 1 ? `tomorrow ${hm}` : `${t.toLocaleDateString([], {weekday: 'short'})} ${hm}`;
  return full ? `${left} left · done ${when}` : `${left} · ${when}`;
}
function monStatus(full) {
  // refreshes itself every 5 s while on the page
  const box = el('div', 'mon');
  let n = 0;
  const draw = (p) => {
    box.innerHTML = '';
    if (p.error) return box.append(el('small', 'mut', p.error));
    const busy = p.state === 'printing' || p.state === 'paused';
    box.append(
      el(
        'div',
        'mst',
        !busy
          ? p.state
          : full
            ? `${p.state} · ${p.progress} % · layer ${p.layer[0]}/${p.layer[1]}`
            : `${p.progress} % · ${p.layer[0]}/${p.layer[1]}`
      )
    );
    if (busy && p.remaining_s != null) box.append(el('div', full ? 'meta' : 'meta sm', eta(p.remaining_s, full)));
    if (busy) {
      const b = el('div', 'mbar'),
        i = el('i');
      i.style.width = p.progress + '%';
      b.append(i);
      box.append(b);
      if (full) box.append(el('small', 'mut', p.file));
    }
    if (!full) return;
    const t = el('div', 'mtemps');
    for (const [k, v] of Object.entries(p.temps || {})) t.append(el('span', '', `${TNAME[k] || k} ${v}°`));
    box.append(t);
    const f = el('div', 'mfil');
    for (const x of p.filaments || []) {
      const s = el('span', 'tile', x.filament);
      s.style.background = x.colour;
      s.style.color = ink(x.colour);
      s.title = `${x.vendor} ${x.type} ${x.sub_type}`;
      if (!x.loaded) s.style.opacity = 0.35;
      f.append(s);
    }
    box.append(f);
  };
  const tick = async () => {
    if (!box.isConnected) {
      if (n++ > 3) clearInterval(iv);
      return;
    }
    if (document.hidden || !box.getClientRects().length) return;
    try {
      draw((PR = await (await fetch('/api/printer')).json()));
    } catch {}
  };
  const iv = setInterval(tick, 5000);
  setTimeout(tick, 50);
  box.append(el('small', 'mut', 'Checking…'));
  return box;
}
function openMonitor() {
  const b = el('div'),
    pin = el('button', 'btn2 full');
  pin.innerHTML = `<span class="ic">${icon('pin')}</span>Pin as a small window`;
  pin.onclick = () => {
    localStorage.monPin = '1';
    closeModal();
    drawPip();
  };
  b.append(camView(), monStatus(true), pin);
  modal('Monitor', b);
}
function drawPip() {
  $('pip')?.remove();
  if (localStorage.monPin !== '1') return;
  const p = el('div', 'glass');
  p.id = 'pip';
  const x = el('button', 'ibtn');
  x.innerHTML = icon('x');
  x.title = 'Unpin';
  x.onclick = (e) => {
    e.stopPropagation();
    localStorage.monPin = '';
    p.remove();
  };
  p.append(camView(), monStatus(false), x);
  p.onclick = openMonitor;
  document.body.append(p);
}
$('monBtn').onclick = openMonitor;
drawPip();
function printerCard() {
  const c = el('div', 'card'),
    h = el('div', 'ct');
  h.innerHTML = `<span class="ic" style="vertical-align:-4px">${icon('printer')}</span> Printer`;
  c.append(h);
  if (!PR) {
    c.append(el('small', 'mut', 'Checking…'));
    return c;
  }
  if (PR.error) {
    c.append(el('small', 'mut', PR.error));
    return c;
  }
  const st = el('div', 'mut');
  st.style.marginBottom = '6px';
  st.textContent =
    PR.state === 'printing' || PR.state === 'paused'
      ? `${PR.state} · ${PR.file} · ${PR.progress} % · layer ${PR.layer[0]}/${PR.layer[1]}`
      : `${PR.state} · ${PR.host}`;
  c.append(st);
  PR.filaments.forEach((f) => {
    const r = el('div', 'frow'),
      t = el('span', 'tile', f.filament);
    t.style.background = f.colour;
    t.style.color = ink(f.colour);
    const same = S.filaments[f.filament - 1]?.colour.toUpperCase() === f.colour.toUpperCase();
    r.append(
      t,
      el('span', 'n', `${f.vendor} ${f.type} ${f.sub_type}`.trim() + (f.loaded ? '' : ' (empty)')),
      el('small', '', same ? '✓ in project' : f.colour)
    );
    c.append(r);
  });
  const differ = PR.filaments.some((f) => S.filaments[f.filament - 1]?.colour.toUpperCase() !== f.colour.toUpperCase());
  if (differ) c.append(el('small', 'mut', 'The project uses other colours than the printer has loaded.'));
  const b = el('button', 'btn2 full');
  b.innerHTML = `<span class="ic">${icon('printer')}</span>Map colours to the printer…`;
  b.onclick = () => colourMapDialog('printer');
  c.append(b);
  return c;
}
const deClass = (d) => (d < 5 ? 'good' : d < 12 ? 'ok' : 'bad');
const optLabel = (o) => (o.kind === 'phys' ? `Filament ${o.ext}` : `Mix ${o.ids.join('+')} · ${o.weights.join('/')} %`);
async function colourMapDialog(source) {
  toast('Matching colours…');
  let r = await busy(fetch('/api/colours/plan?source=' + source).then((r) => r.json()));
  if (r.error && source === 'printer') {
    toast('Printer unreachable — matching to the project filaments', true);
    r = await busy(fetch('/api/colours/plan?source=project').then((r) => r.json()));
    source = 'project';
  }
  $('toast').hidden = true;
  const box = el('div'),
    choice = {};
  box.append(
    el(
      'small',
      'mut',
      `Each colour of the model gets the closest ${source === 'printer' ? 'loaded filament' : 'filament'} — or a Full Spectrum mix when no filament is close. ΔE: under 5 looks the same, over 12 is clearly different. Tap a row to pick something else.`
    )
  );
  const pal = el('div', 'maprow');
  pal.append(el('span', 'mut', 'Target:'));
  r.physical.forEach((c, i) => {
    const t = el('span', 'tile sm', i + 1);
    t.style.background = c;
    t.style.color = ink(c);
    pal.append(t);
  });
  box.append(pal);
  for (const t of r.targets) {
    choice[t.id] = t.best;
    const row = el('div', 'maprow click'),
      from = el('span', 'tile', t.id);
    from.style.background = t.colour;
    from.style.color = ink(t.colour);
    const info = el('span', 'n');
    info.innerHTML = `${t.colour}<small>${t.parts ? t.parts + ' parts' : ''}${t.parts && t.painted ? ' · ' : ''}${t.painted ? 'painted' : ''}</small>`;
    const to = el('span', 'tile'),
      lab = el('span', 'n'),
      de = el('span', 'de');
    const show = (o) => {
      to.style.background = o.colour;
      to.textContent = o.kind === 'phys' ? o.ext : 'M';
      to.style.color = ink(o.colour);
      lab.innerHTML = `${optLabel(o)}<small>${o.colour}</small>`;
      de.textContent = `ΔE ${o.de}`;
      de.className = 'de ' + deClass(o.de);
    };
    show(t.best);
    const opts = el('div', 'mapopts');
    opts.hidden = true;
    for (const o of t.options) {
      const b = el('button', 'opt'),
        sw = el('span', 'tile sm');
      sw.style.background = o.colour;
      b.append(
        sw,
        el('span', 'n', optLabel(o)),
        Object.assign(el('span', 'de ' + deClass(o.de)), {textContent: `ΔE ${o.de}`})
      );
      b.onclick = (e) => {
        e.stopPropagation();
        choice[t.id] = o;
        show(o);
        opts.hidden = true;
      };
      opts.append(b);
    }
    row.append(from, info, el('span', 'arrow', '→'), to, lab, de);
    row.onclick = () => (opts.hidden = !opts.hidden);
    box.append(row, opts);
  }
  if (!r.targets.length) box.append(el('div', 'empty', 'No coloured objects in the project.'));
  const foot = el('div', 'mfoot'),
    cancel = el('button', 'btn2', 'Cancel'),
    ok = el('button', 'primary', 'Apply');
  cancel.onclick = closeModal;
  ok.onclick = async () => {
    const fil =
      source === 'printer'
        ? PR.filaments.map((f) => ({colour: f.colour, type: f.type}))
        : S.filaments.map((f) => ({colour: f.colour}));
    const res = await op({op: 'apply_colour_map', filaments: fil, map: choice});
    if (res) {
      closeModal();
      toast(res.msg);
    }
  };
  document.querySelectorAll('.mfoot').forEach((f) => f.remove());
  foot.append(cancel, ok);
  modal('Map colours', box);
  $('mbody').after(foot);
  const kill = new MutationObserver(() => {
    if ($('modal').hidden) {
      foot.remove();
      kill.disconnect();
    }
  });
  kill.observe($('modal'), {attributes: true});
}
let FILPRESETS = null;
const FILFIELDS = [
  // [key, label, unit] — editable per filament slot (all flow variants get the value)
  ['nozzle_temperature', 'Nozzle', '°C'],
  ['hot_plate_temp', 'Bed', '°C'],
  ['filament_max_volumetric_speed', 'Max flow', 'mm³/s'],
  ['filament_flow_ratio', 'Flow ratio', ''],
  ['filament_retraction_length', 'Retraction', 'mm'],
  ['filament_retraction_speed', 'Retraction speed', 'mm/s'],
  ['fan_min_speed', 'Fan min', '%'],
  ['fan_max_speed', 'Fan max', '%'],
];
async function filamentModal(i) {
  FILPRESETS = await (await fetch('/api/filaments')).json();
  const f = S.filaments[i],
    box = el('div', 'form'),
    cur = f.vals || {};
  const ps = el('select'),
    byType = {};
  for (const [n, v] of Object.entries(FILPRESETS))
    (byType[v.user ? '★ My presets' : v.filament_type[0]] ??= []).push(n);
  for (const t of Object.keys(byType).sort()) {
    const g = document.createElement('optgroup');
    g.label = t;
    for (const n of byType[t]) g.append(new Option(n.replace(/ @U1( 0\.4 nozzle)?$/, ''), n));
    ps.append(g);
  }
  if (!FILPRESETS[f.preset]) ps.prepend(new Option(`${f.preset || f.type} (from the project)`, ''));
  ps.value = FILPRESETS[f.preset] ? f.preset : '';
  const row = (label, input) => {
    const r = el('label', 'frm');
    r.append(el('span', '', label), input);
    box.append(r);
    return input;
  };
  row('Preset', ps);
  const inp = {};
  for (const [k, l, u] of FILFIELDS)
    inp[k] = row(
      l + (u ? ` (${u})` : ''),
      Object.assign(el('input'), {
        type: 'text',
        inputMode: 'decimal',
        value: cur[k] ?? '',
        placeholder: 'printer default',
      })
    );
  ps.onchange = () => {
    const p = FILPRESETS[ps.value];
    if (p) for (const [k] of FILFIELDS) inp[k].value = p[k]?.[0] ?? '';
  };
  const val = (v) => (v === 'nil' ? '' : v);
  for (const [k] of FILFIELDS) inp[k].value = val(inp[k].value);
  const foot = el('div', 'mfoot'),
    save = el('button', 'btn2', 'Save as my preset…'),
    ok = el('button', 'primary', 'Apply');
  async function apply() {
    if (
      ps.value &&
      ps.value !== f.preset &&
      !(await op({op: 'set_filament_preset', filament: i + 1, preset: ps.value}))
    )
      return false;
    const base =
      FILPRESETS[ps.value] && ps.value !== f.preset
        ? Object.fromEntries(FILFIELDS.map(([k]) => [k, val(FILPRESETS[ps.value][k]?.[0] ?? '')]))
        : Object.fromEntries(FILFIELDS.map(([k]) => [k, val(cur[k] ?? '')]));
    const values = {};
    for (const [k] of FILFIELDS)
      if (inp[k].value.trim() !== String(base[k]) && inp[k].value.trim() !== '') values[k] = inp[k].value.trim();
    if (values.nozzle_temperature) values.nozzle_temperature_initial_layer = values.nozzle_temperature;
    if (values.hot_plate_temp) {
      const b = values.hot_plate_temp;
      delete values.hot_plate_temp;
      return !!(await op({op: 'set_filament_values', filament: i + 1, bed: b, values}));
    }
    return !Object.keys(values).length || !!(await op({op: 'set_filament_values', filament: i + 1, values}));
  }
  ok.onclick = async () => {
    if (await apply()) {
      closeModal();
      toast(`Filament ${i + 1} updated`);
    }
  };
  save.onclick = async () => {
    const n = prompt(
      'Name for your filament preset',
      (ps.value || f.preset || f.type).replace(/ @U1.*$/, '') + ' (mine)'
    );
    if (!n || !(await apply())) return;
    const r = await postJ('/api/filaments/save', {filament: i + 1, name: n});
    if (r) {
      closeModal();
      toast(`Saved "${n}" — pick it for any slot`);
    }
  };
  if (FILPRESETS[ps.value]?.user) {
    const del = el('button', 'btn2', 'Delete preset');
    del.onclick = async () => {
      if (confirm(`Delete your preset "${ps.value}"? (the project keeps its values)`)) {
        await postJ('/api/filaments/delete', {name: ps.value});
        closeModal();
      }
    };
    foot.append(del);
  }
  document.querySelectorAll('.mfoot').forEach((x) => x.remove());
  foot.append(save, ok);
  modal(`Filament ${i + 1}`, box);
  $('mbody').after(foot);
  const kill = new MutationObserver(() => {
    if ($('modal').hidden) {
      foot.remove();
      kill.disconnect();
    }
  });
  kill.observe($('modal'), {attributes: true});
}
function filTab() {
  const F = $('tab-fil');
  if (!S || (F.contains(document.activeElement) && document.activeElement.matches('input,select,textarea'))) return;
  F.innerHTML = ''; // only while typing
  F.append(printerCard());
  const c1 = el('div', 'card');
  c1.append(el('div', 'ct', 'Filaments'));
  S.filaments.forEach((f, i) => {
    const r = el('button', 'frow tap'),
      t = el('span', 'tile', i + 1);
    t.style.background = f.colour;
    t.style.color = ink(f.colour);
    const nm = el('span', 'n');
    nm.append(f.type, el('small', 'mut', ' ' + (f.preset || '').replace(/ @U1.*$/, '')));
    r.append(t, nm, el('small', '', `${f.nozzle || '?'}° / ${f.bed || '?'}°`));
    r.title = 'Filament preset and temperatures';
    r.onclick = () => filamentModal(i);
    c1.append(r);
  });
  c1.append(
    el(
      'small',
      'mut',
      'Tap a filament to pick its Orca preset (PLA, PETG, TPU…) or change temperatures. Sync from the printer picks presets automatically.'
    )
  );
  F.append(c1);
  const c2 = el('div', 'card');
  c2.append(el('div', 'ct', 'Mixed colours'));
  if (!mix.length)
    c2.append(el('small', 'mut', 'None yet. Snapmaker Full Spectrum alternates 2–4 filaments layer by layer.'));
  const pal = el('div', 'pal');
  c2.append(el('div', 'sub', 'Mixable from your filaments — tap to add'), pal);
  fetch('/api/colours/palette')
    .then((r) => r.json())
    .then((list) =>
      list.forEach((m) => {
        const b = el('button');
        b.style.background = m.colour;
        b.title = `${m.ids.join('+')} · ${m.weights.join('/')} %`;
        if (m.ids.length > 2) b.classList.add('tri');
        if (mix.some((x) => sameRecipe(x, m.ids, m.weights))) {
          b.textContent = '✓';
          b.style.color = ink(m.colour);
          b.title += ' (added)';
        }
        b.onclick = async () => {
          const r = await op({op: 'mix_add', ids: m.ids, weights: m.weights});
          if (r) toast(r.msg);
        };
        pal.append(b);
      })
    );
  mix.forEach((m, k) => {
    const id = nPhys() + k + 1,
      r = el('div', 'frow'),
      t = el('span', 'tile', id);
    t.style.background = chipBg(id);
    t.style.color = '#fff';
    t.style.textShadow = '0 1px 2px #000';
    const del = el('button', 'ibtn');
    del.innerHTML = `<span class="ic">${icon('trash')}</span>`;
    del.onclick = () => op({op: 'mix_del', index: k});
    r.append(t, el('span', 'n', m.ids.join(' + ')), el('small', '', `${m.weights.join(' / ')} %`), del);
    c2.append(r);
  });
  // new mix: 2-4 components with weights
  const ed = el('div', 'mixed');
  c2.append(el('div', 'sub', 'New mix'), ed);
  const comps = [
    [1, 50],
    [Math.min(3, nPhys()), 50],
  ];
  const prev = el('div', 'frow'),
    pt = el('span', 'tile'),
    pl = el('small', 'n');
  const add = el('button', 'btn2 full');
  add.innerHTML = `<span class="ic">${icon('plus')}</span>Add mix`;
  function draw() {
    ed.innerHTML = '';
    comps.forEach((cw, i) => {
      const row = el('div', 'fields'),
        s = el('select');
      for (let k = 1; k <= nPhys(); k++) s.add(new Option(`${k} · ${S.filaments[k - 1].type}`, k));
      s.value = cw[0];
      const sw = el('span', 'tile sm');
      sw.style.background = fcol(cw[0]);
      const w = Object.assign(el('input'), {
        type: 'number',
        min: 1,
        max: 100,
        step: 5,
        value: cw[1],
        inputMode: 'numeric',
      });
      s.onchange = () => {
        cw[0] = +s.value;
        sw.style.background = fcol(cw[0]);
        upd();
      };
      w.oninput = () => {
        cw[1] = Math.max(0, +w.value || 0);
        upd();
      };
      row.append(sw, s, w, el('span', 'mut', '%'));
      if (comps.length > 2) {
        const x = el('button', 'ibtn');
        x.innerHTML = `<span class="ic">${icon('x')}</span>`;
        x.onclick = () => {
          comps.splice(i, 1);
          draw();
        };
        row.append(x);
      }
      ed.append(row);
    });
    if (comps.length < Math.min(4, nPhys())) {
      const more = el('button', 'btn2');
      more.innerHTML = `<span class="ic">${icon('plus')}</span>Component`;
      more.onclick = () => {
        const free = [...Array(nPhys()).keys()].map((k) => k + 1).find((k) => !comps.some((c) => c[0] === k));
        comps.push([free, 20]);
        draw();
      };
      ed.append(more);
    }
    upd();
  }
  function upd() {
    const ids = comps.map((c) => c[0]),
      ws = comps.map((c) => c[1]),
      tot = ws.reduce((p, q) => p + q, 0) || 1,
      dup = new Set(ids).size !== ids.length;
    pt.style.background = dup ? 'transparent' : blendMulti(ids, ws);
    pl.textContent = dup
      ? 'Pick different filaments'
      : comps.map((c) => `${Math.round((100 * c[1]) / tot)} % ${c[0]}`).join(' · ');
    add.disabled = dup || ws.some((x) => x <= 0);
  }
  add.onclick = async () => {
    const r = await op({op: 'mix_add', ids: comps.map((c) => c[0]), weights: comps.map((c) => c[1])});
    if (r) toast(r.msg);
  };
  prev.append(pt, pl);
  draw();
  c2.append(prev, add);
  F.append(c2);
}

// ---------- print settings (schema.json generated from the Orca source: pages > groups > options)
let SCHEMA = null;
const schemaReady = fetch('schema.json')
  .then((r) => r.json())
  .then((s) => (SCHEMA = s));
const strip = (v) => (v == null ? '' : String(v).replace(/%$/, ''));

// values: current; base: inherited values (per-object form, empty = inherit) or null (global form)
function settingsForm(values, base, objOnly) {
  const box = el('div', 'form'),
    get = {},
    rows = [];
  const search = el('input', 'search');
  search.placeholder = 'Search settings…';
  search.type = 'search';
  let showAdv = true;
  const advT = el('button', 'sw2 on');
  advT.type = 'button';
  advT.onclick = () => {
    showAdv = !showAdv;
    advT.classList.toggle('on', showAdv);
    filter();
  };
  const tools = el('div', 'ftools');
  const al = el('span', 'mut', 'Show advanced');
  tools.append(search, al, advT);
  box.append(tools);
  for (const pg of SCHEMA.pages) {
    const det = el('details', 'pg'),
      sum = el('summary'),
      cnt = el('span', 'cnt');
    sum.append(el('span', '', pg.name), cnt);
    det.append(sum);
    let any = 0;
    for (const gr of pg.groups) {
      const keys = gr.opts.filter((k) => !objOnly || SCHEMA.opts[k].obj);
      if (!keys.length) continue;
      const grp = el('div', 'grp');
      grp.append(el('div', 'sub', gr.name));
      det.append(grp);
      for (const k of keys) {
        const o = SCHEMA.opts[k],
          cur = values[k],
          inh = base ? base[k] : values[k];
        const row = el('div', 'frm'),
          lab = el('span', 'lab');
        row.dataset.q = [o.label, k, pg.name, gr.name].join(' ').toLowerCase();
        row.dataset.k = k;
        row.dataset.adv = o.adv ? 1 : '';
        const meta = el('span', 'meta');
        meta.append(el('span', 'badge ' + (o.adv ? 'adv' : 'basic'), o.adv ? 'Advanced' : 'Basic'), el('code', '', k));
        const info = el('button', 'info', 'i');
        info.type = 'button';
        info.title = 'Help';
        info.onclick = (e) => {
          e.preventDefault();
          row.classList.toggle('tipo');
        };
        lab.append(el('span', 'lt', o.label), meta);
        row.append(info, lab);
        let read;
        if (o.type === 'Bool') {
          let on = (cur ?? inh) === '1',
            set = cur != null;
          const t = el('button', 'sw2' + (on ? ' on' : ''));
          t.type = 'button';
          t.onclick = (e) => {
            e.preventDefault();
            on = !on;
            set = true;
            t.classList.toggle('on', on);
            count();
          };
          row.append(t);
          read = () => (base && !set ? null : on ? '1' : '0');
        } else if (o.enum) {
          const s = el('select');
          if (base) s.add(new Option(`↳ ${(o.enum.find((e) => e[0] === inh) || [null, inh])[1]}`, ''));
          for (const [v, l] of o.enum) s.add(new Option(l, v));
          s.value = cur ?? (base ? '' : inh);
          row.append(s);
          read = () => s.value || null;
        } else {
          const i = el('input');
          const num = ['Int', 'Float', 'Percent'].includes(o.type);
          i.type = num ? 'number' : 'text';
          if (num) i.inputMode = 'decimal';
          i.step = o.type === 'Int' ? 1 : 'any';
          const side = o.type === 'Percent' ? '%' : o.side;
          const sv = (v) => (o.type === 'Percent' ? strip(v) : (v ?? '')); // FloatOrPercent keeps its '%'
          i.value = sv(cur ?? (base ? null : inh));
          if (base) i.placeholder = sv(inh) + (side ? ' ' + side : '');
          const w = el('span', 'inp');
          w.append(i);
          if (side && !base) w.append(el('em', '', side));
          row.append(w);
          read = () => (i.value === '' ? null : o.type === 'Percent' ? i.value + '%' : i.value);
        }
        row.append(el('div', 'tip', o.tip || 'No description in Orca.'));
        // global form: report only values the user changed; object form: everything that is set
        get[k] = base
          ? read
          : () => {
              const v = read();
              return v != null && v !== String(values[k]) ? v : null;
            };
        grp.append(row);
        rows.push(row);
        any++;
      }
    }
    if (any) box.append(det);
  }
  // per-section counters of set values
  function count() {
    box.querySelectorAll('details.pg').forEach((d) => {
      const n = [...d.querySelectorAll('.frm')].filter((r) => get[r.dataset.k]() != null).length;
      d.querySelector('.cnt').textContent = n || '';
    });
  }
  box.addEventListener('change', count);
  box.addEventListener('input', count);
  count();
  search.oninput = filter;
  function filter() {
    const q = search.value.trim().toLowerCase();
    for (const r of rows) r.hidden = (q && !r.dataset.q.includes(q)) || (!showAdv && r.dataset.adv);
    box.querySelectorAll('.grp').forEach((g) => (g.hidden = ![...g.querySelectorAll('.frm')].some((r) => !r.hidden)));
    box.querySelectorAll('details.pg').forEach((d) => {
      const vis = [...d.querySelectorAll('.frm')].some((r) => !r.hidden);
      d.hidden = !vis;
      d.open = !!q && vis;
    });
  }
  return {
    el: box,
    read: () =>
      Object.fromEntries(
        Object.entries(get)
          .map(([k, f]) => [k, f()])
          .filter(([, v]) => v != null)
      ),
  };
}
let gform = null;
// ---------- profiles (global = Orca presets + saved ones; object = saved favourites, merged into the object)
let PROFS = null;
async function loadProfiles() {
  PROFS = await (await fetch('/api/profiles')).json();
  profilesCard();
  return PROFS;
}
function profilesCard() {
  const box = $('profs');
  if (!box || !PROFS) return;
  box.innerHTML = '';
  // dropdown (Orca presets / saved), applied on change; saved ones can be deleted with the × next to it
  const row = el('div', 'profs'),
    sel = el('select'),
    grp = {Orca: [], '★ Saved': []};
  for (const p of PROFS.global) grp[p.builtin ? 'Orca' : '★ Saved'].push(p);
  sel.append(new Option('Choose a profile…', ''));
  for (const [label, list] of Object.entries(grp)) {
    if (!list.length) continue;
    const g = document.createElement('optgroup');
    g.label = label;
    for (const p of list) g.append(new Option(p.name, p.name));
    sel.append(g);
  }
  sel.value = PROFS.global.some((p) => p.name === S?.profile) ? S.profile : '';
  sel.onchange = async () => {
    const p = PROFS.global.find((q) => q.name === sel.value);
    if (!p) return;
    const r = await op({op: 'apply_profile', kind: 'global', name: p.name, user: !p.builtin});
    if (r) toast(r.msg);
  };
  row.append(sel);
  const cur = PROFS.global.find((p) => p.name === sel.value);
  if (cur && !cur.builtin) {
    const x = el('button', 'ibtn');
    x.innerHTML = `<span class="ic">${icon('trash')}</span>`;
    x.title = 'Delete this saved profile';
    x.onclick = async () => {
      if (!confirm(`Delete profile "${cur.name}"?`)) return;
      await postJ('/api/profiles/delete', {kind: 'global', name: cur.name});
      loadProfiles();
    };
    row.append(x);
  }
  const save = el('button', 'btn2 full');
  save.innerHTML = `<span class="ic">${icon('save')}</span>Save current settings as profile…`;
  save.onclick = async () => {
    const n = prompt('Profile name (colours / filament assignments are not saved)');
    if (!n) return;
    const r = await postJ('/api/profiles/save', {kind: 'global', name: n});
    if (r) {
      toast(r.msg);
      loadProfiles();
    }
  };
  box.append(
    row,
    el('small', 'mut', 'A profile replaces the project-level print settings. Filament colours and assignments stay.'),
    save
  );
}
let gformKey = '';
async function globalSettings() {
  await schemaReady;
  const key = JSON.stringify([S.settings, S.overrides]);
  if (key === gformKey || $('gset').contains(document.activeElement)) return;
  gformKey = key;
  const vals = Object.assign({}, S.settings, S.overrides);
  gform = settingsForm(vals, null, false);
  $('gset').innerHTML = '';
  $('gset').append(gform.el);
  gform.el.addEventListener('change', () => {
    const ch = gform.read();
    if (Object.keys(ch).length) op({op: 'set_global', settings: ch});
  });
}

function objectModal(o) {
  document.querySelectorAll('.mfoot').forEach((f) => f.remove()); // reopen ("All global") must not stack footers
  const box = el('div'),
    bb = bbox(o),
    c = bb.getCenter(new T.Vector3()).sub(plateOffset(o.plate)); // plate-local
  const eu = new T.Euler().setFromQuaternion(o.group.quaternion, 'ZYX'),
    r1 = (v) => String(Math.round(v * 10) / 10); // same convention as session.decompose (R = Rz·Ry·Rx)
  const tf = el('div', 'form');
  const xyz = (name, vals, unit) => {
    // a row per axis (three in one row did not fit a phone); returns {read(): [x,y,z] or null if untouched, inputs}
    const ins = vals.map((v, i) => {
      const n = num(`${name} ${'XYZ'[i]}`, r1(v), unit);
      n.step = 'any';
      n.closest('.frm').classList.add('xyzr');
      return n;
    });
    return {
      ins,
      read: () =>
        ins.some((n, i) => n.value !== r1(vals[i])) ? ins.map((n) => (n.value === '' ? null : +n.value)) : null,
    };
  };
  const num = (name, v, unit) => {
    const r = el('label', 'frm'),
      i = el('input');
    i.type = 'number';
    i.inputMode = 'decimal';
    i.value = v;
    r.append(el('span', '', name + (unit ? ` (${unit})` : '')), i);
    tf.append(r);
    return i;
  };
  const nm = el('input');
  nm.value = o.name;
  nm.style.textAlign = 'left';
  const nr = el('label', 'frm');
  nr.append(el('span', '', 'Name'), nm);
  tf.append(nr);
  const P = xyz('Position', [c.x, c.y, bb.min.z], 'mm'),
    R = xyz('Rotation', [eu.x, eu.y, eu.z].map(T.MathUtils.radToDeg), '°'),
    K = xyz(
      'Scale',
      o.group.scale.toArray().map((v) => v * 100),
      '%'
    );
  P.ins[2].title = 'Z = height of the bottom above the bed';
  const KU = el('input');
  KU.type = 'checkbox';
  KU.checked = new Set(K.ins.map((n) => n.value)).size === 1; // uniform scaling: one field drives all three
  {
    const r = el('label', 'frm');
    r.append(el('span', '', 'Uniform scale'), KU);
    tf.append(r);
    KU.style.width = '22px';
  }
  K.ins.forEach(
    (n, i) =>
      (n.oninput = () => {
        if (KU.checked) {
          const f = +n.value / +K.ins[i].defaultValue;
          K.ins.forEach((m, j) => {
            if (j !== i) m.value = r1(+m.defaultValue * f);
          });
        }
      })
  );
  K.ins.forEach((n) => (n.defaultValue = n.value));
  const PL = el('select');
  for (let p = 1; p <= (S.plates || 1); p++) PL.add(new Option(`Plate ${p}`, p));
  PL.add(new Option('New plate', S.plates + 1));
  PL.value = o.plate;
  {
    const r = el('label', 'frm');
    r.append(el('span', '', 'Plate'), PL);
    tf.append(r);
  }
  const RL = el('select');
  for (const [v, l] of [
    ['', 'Normal object (printed)'],
    ['modifier_part', 'Modifier (own settings, region)'],
    ['negative_part', 'Negative volume (hole)'],
    ['support_blocker', 'Support blocker'],
    ['support_enforcer', 'Support enforcer'],
  ])
    RL.add(new Option(l, v));
  RL.value = o.role || '';
  RL.onchange = async () => {
    const r = await op({op: 'set_role', id: o.id, role: RL.value || null});
    if (r) toast(r.msg);
  };
  {
    const r = el('label', 'frm');
    r.append(el('span', '', 'Acts as'), RL);
    tf.append(r);
  }
  const addc = el('div', 'form'),
    ad = el('div', 'fields');
  const kind = el('select');
  for (const [v, l] of [
    ['modifier', 'Modifier (own settings)'],
    ['negative', 'Negative volume (hole)'],
    ['part', 'Solid part'],
    ['support_enforcer', 'Support enforcer'],
    ['support_blocker', 'Support blocker'],
  ])
    kind.add(new Option(l, v));
  const shape = el('select');
  for (const v of ['box', 'cylinder', 'sphere']) shape.add(new Option(v[0].toUpperCase() + v.slice(1), v));
  ad.append(kind, shape);
  const sz = el('div', 'fields'),
    dims = ['X', 'Y', 'Z'].map((a) => {
      const i = el('input');
      i.type = 'number';
      i.placeholder = `${a} size mm`;
      i.inputMode = 'decimal';
      sz.append(i);
      return i;
    });
  const addB = el('button', 'btn2 full');
  addB.innerHTML = `<span class="ic">${icon('plus')}</span>Add to object`;
  addB.onclick = async () => {
    const size = dims.every((i) => i.value) ? dims.map((i) => +i.value) : undefined;
    const r = await op({op: 'add_part', id: o.id, kind: kind.value, shape: shape.value, size});
    if (r) {
      closeModal();
      open.add(o.id);
      toast(r.msg + (kind.value === 'modifier' ? ' — set its settings in the parts list' : ''));
    }
  };
  addc.append(ad, sz, el('small', 'mut', 'Empty size = 60 % of the object, centred in it.'), addB);
  const pr = el('div', 'profs');
  (PROFS?.object || []).forEach((p) => {
    const b = el('button', 'prof');
    b.append(el('span', '', p.name), el('em', '', `${p.count}`));
    b.title = Object.entries(p.settings)
      .map(([k, v]) => `${k} = ${v}`)
      .join('\n');
    const x = el('span', 'x', '×');
    x.onclick = async (e) => {
      e.stopPropagation();
      if (confirm(`Delete object profile "${p.name}"?`)) {
        await postJ('/api/profiles/delete', {kind: 'object', name: p.name});
        await loadProfiles();
        objectModal(byId(o.id));
      }
    };
    b.append(x);
    b.onclick = async () => {
      const r = await op({op: 'apply_profile', kind: 'object', name: p.name, id: o.id});
      if (r) {
        toast(r.msg);
        objectModal(byId(o.id));
      }
    };
    pr.append(b);
  });
  const ps = el('button', 'btn2');
  ps.innerHTML = `<span class="ic">${icon('save')}</span>Save as profile…`;
  ps.onclick = async () => {
    const n = prompt('Object profile name (e.g. "Tree supports")');
    if (!n) return;
    const r = await postJ('/api/profiles/save', {kind: 'object', name: n, id: o.id});
    if (r) {
      toast(r.msg);
      await loadProfiles();
      objectModal(byId(o.id));
    }
  };
  pr.append(ps);
  box.append(
    el('div', 'sub', 'Object'),
    tf,
    el('div', 'sub', "Profiles — tap to apply (adds to this object's settings)"),
    pr,
    el('div', 'sub', 'Add volume'),
    addc,
    el('div', 'sub', 'Print — empty = global value')
  );
  const f = settingsForm(o.cfg || {}, Object.assign({}, S.settings, S.overrides), true);
  box.append(f.el);
  const foot = el('div', 'mfoot'),
    reset = el('button', 'btn2', 'All global'),
    ok = el('button', 'primary', 'Apply');
  reset.onclick = async () => {
    await op({op: 'set_object', id: o.id, cfg: {}});
    objectModal(byId(o.id));
  };
  ok.onclick = async () => {
    if (+PL.value !== o.plate) {
      if (!(await op({op: 'set_plate', id: o.id, plate: +PL.value}))) return;
      curPlate = +PL.value;
    }
    const p = P.read(),
      samePlate = +PL.value === o.plate;
    const r = await op({
      op: 'set_object',
      id: o.id,
      name: nm.value,
      cfg: f.read(),
      ...(p && samePlate ? {x: p[0], y: p[1]} : {}),
      ...(p ? {z: p[2]} : {}),
      rot: R.read(),
      scale: K.read(),
    });
    if (r) {
      closeModal();
      toast(r.msg || 'Saved');
      if (+PL.value !== o.plate) view(lastView);
    }
  };
  foot.append(reset, ok);
  modal(o.name, box);
  $('mbody').after(foot);
  const kill = new MutationObserver(() => {
    if ($('modal').hidden) {
      foot.remove();
      kill.disconnect();
    }
  });
  kill.observe($('modal'), {attributes: true});
}

function partModal(o, i) {
  document.querySelectorAll('.mfoot').forEach((f) => f.remove());
  const p = o.parts[i],
    box = el('div');
  const nm = el('input');
  nm.value = p.name;
  nm.style.textAlign = 'left';
  const nr = el('label', 'frm');
  nr.append(el('span', '', 'Name'), nm);
  box.append(
    el('div', 'form'),
    el('div', 'sub', `${PTYPE[p.type]} — settings for this volume (empty = object/global value)`)
  );
  box.firstChild.append(nr);
  const pos = {}; // world centre of this volume (move it inside the object)
  {
    const pb = new T.Box3().setFromObject(o.parts[i].mesh).getCenter(new T.Vector3()).sub(plateOffset(o.plate));
    for (const [a, v] of [
      ['x', pb.x],
      ['y', pb.y],
      ['z', pb.z],
    ]) {
      const r = el('label', 'frm'),
        inp = el('input');
      inp.type = 'number';
      inp.inputMode = 'decimal';
      inp.value = v.toFixed(1);
      pos[a] = inp;
      r.append(el('span', '', `Position ${a.toUpperCase()} (mm)`), inp);
      box.firstChild.append(r);
    }
  }
  if (PROFS?.object?.length) {
    const pr = el('div', 'profs');
    for (const q of PROFS.object) {
      const b = el('button', 'prof');
      b.append(el('span', '', q.name), el('em', '', `${q.count}`));
      b.title = Object.entries(q.settings)
        .map(([k, v]) => `${k} = ${v}`)
        .join('\n');
      b.onclick = async () => {
        const r = await op({op: 'apply_profile', kind: 'object', name: q.name, id: o.id, part: i});
        if (r) {
          toast(r.msg);
          partModal(byId(o.id), i);
        }
      };
      pr.append(b);
    }
    box.append(el('div', 'sub', 'Profiles — tap to apply to this volume'), pr);
  }
  if (Object.keys(p.cfg || {}).length) {
    const ps = el('button', 'btn2');
    ps.innerHTML = `<span class="ic">${icon('save')}</span>Save these settings as a profile…`;
    ps.onclick = async () => {
      const n = prompt('Profile name (e.g. "TPU slow")');
      if (!n) return;
      const r = await postJ('/api/profiles/save', {kind: 'object', name: n, id: o.id, part: i});
      if (r) {
        toast(r.msg);
        await loadProfiles();
        partModal(byId(o.id), i);
      }
    };
    box.append(ps);
  }
  const f = settingsForm(p.cfg || {}, Object.assign({}, S.settings, S.overrides, o.cfg), true);
  box.append(f.el);
  const foot = el('div', 'mfoot'),
    reset = el('button', 'btn2', 'Clear'),
    ok = el('button', 'primary', 'Apply');
  reset.onclick = async () => {
    await op({op: 'set_part', id: o.id, part: i, cfg: {}});
    partModal(byId(o.id), i);
  };
  ok.onclick = async () => {
    const mv = ['x', 'y', 'z'].some((a) => Math.abs(+pos[a].value - +pos[a].defaultValue) > 0.05)
      ? await op({op: 'move_part', id: o.id, part: i, x: +pos.x.value, y: +pos.y.value, z: +pos.z.value})
      : true;
    if (mv && (await op({op: 'set_part', id: o.id, part: i, cfg: f.read(), name: nm.value}))) {
      closeModal();
      toast('Saved');
    }
  };
  foot.append(reset, ok);
  modal(`${o.name} · ${p.name}`, box);
  $('mbody').after(foot);
  const kill = new MutationObserver(() => {
    if ($('modal').hidden) {
      foot.remove();
      kill.disconnect();
    }
  });
  kill.observe($('modal'), {attributes: true});
}

$('addBtn').onclick = () => {
  const box = el('div', 'flist');
  const act = (ic, t, sub, fn) => {
    const b = el('button');
    b.innerHTML = `<span class="ic">${icon(ic)}</span><span>${t}<small>${sub}</small></span>`;
    b.onclick = fn;
    box.append(b);
  };
  act('up', 'Import STL / 3MF / ZIP', 'from this device — a zip can hold many models', () => {
    closeModal();
    $('add').click();
  });
  for (const [sh, sub] of [
    ['box', '20 × 20 × 20 mm'],
    ['cylinder', 'Ø 20 × 20 mm'],
    ['sphere', 'Ø 20 mm'],
  ])
    act('plus', sh[0].toUpperCase() + sh.slice(1), sub, async () => {
      closeModal();
      const r = await op({op: 'add_primitive', shape: sh, size: [20, 20, 20], plate: curPlate});
      if (r) {
        toast(r.msg);
      }
    });
  modal('Add object', box);
};

// ---------- colour painting (Orca paint_color per triangle)
let PM = null; // {o, tool, size, angle, state, pending: Map(part -> Map(state -> Set(tri)))}
async function refreshPaint(o, gid) {
  const g = await (await fetch('/api/paint/' + gid)).json();
  if (o.gid !== gid) return;
  (g.parts || []).forEach((pb, i) => {
    const p = o.parts[i];
    if (!p) return;
    p.paint = pb ? b64(pb.s) : null;
    setLeaves(p, pb);
  });
  recolour();
}
// Orca-style split triangles: the server sends their leaf sub-triangles; drawn as an overlay on top of the base mesh
function setLeaves(p, pp) {
  if (p.overlay) {
    p.mesh.remove(p.overlay);
    p.overlay.geometry.dispose();
    p.overlay = null;
  }
  p.leafSt = null;
  if (!pp || !pp.ls) return;
  const st = b64(pp.ls);
  if (!st.length) return;
  const pos = new Float32Array(b64(pp.lp).buffer),
    g = new T.BufferGeometry();
  g.setAttribute('position', new T.BufferAttribute(pos, 3));
  g.computeVertexNormals();
  g.setAttribute('color', new T.BufferAttribute(new Float32Array(pos.length), 3));
  const m = new T.MeshStandardMaterial({
    roughness: 0.55,
    metalness: 0.02,
    side: T.DoubleSide,
    vertexColors: true,
    polygonOffset: true,
    polygonOffsetFactor: -2,
    polygonOffsetUnits: -2,
  });
  p.overlay = new T.Mesh(g, m);
  p.overlay.raycast = () => {}; // picking stays on the base mesh
  p.leafSt = st;
  p.mesh.add(p.overlay);
}
function colourLeaves(p) {
  if (!p.overlay) return;
  const c = p.overlay.geometry.getAttribute('color'),
    cache = {};
  for (let t = 0; t < p.leafSt.length; t++) {
    const k = p.leafSt[t] || p.extruder,
      v = (cache[k] ??= new T.Color(colour(k)));
    for (let j = 0; j < 3; j++) c.setXYZ(t * 3 + j, v.r, v.g, v.b);
  }
  c.needsUpdate = true;
}
function ensurePaint(p) {
  const n = p.mesh.geometry.getAttribute('position').count / 3;
  if (!p.paint) p.paint = new Uint8Array(n);
  if (!p.mesh.geometry.getAttribute('color')) {
    // start from the part colour, not black
    const arr = new Float32Array(n * 9),
      c = new T.Color(colour(p.extruder));
    for (let i = 0; i < n * 3; i++) arr.set([c.r, c.g, c.b], i * 3);
    p.mesh.geometry.setAttribute('color', new T.BufferAttribute(arr, 3));
  }
  if (!p.local) {
    // centroids + normals in object-local space, built once per part
    const pos = p.mesh.geometry.getAttribute('position'),
      c = new Float32Array(n * 3),
      nr = new Float32Array(n * 3),
      a = new T.Vector3(),
      b = new T.Vector3(),
      d = new T.Vector3();
    for (let t = 0; t < n; t++) {
      a.fromBufferAttribute(pos, t * 3);
      b.fromBufferAttribute(pos, t * 3 + 1);
      d.fromBufferAttribute(pos, t * 3 + 2);
      c.set([(a.x + b.x + d.x) / 3, (a.y + b.y + d.y) / 3, (a.z + b.z + d.z) / 3], t * 3);
      const nn = b.clone().sub(a).cross(d.clone().sub(a)).normalize();
      nr.set([nn.x, nn.y, nn.z], t * 3);
    }
    p.local = {c, nr};
  }
}
function adjacency(p) {
  // triangle neighbours through shared edges (vertices matched by position)
  if (p.adj) return p.adj;
  const pos = p.mesh.geometry.getAttribute('position'),
    n = pos.count / 3,
    key = (i) => `${pos.getX(i).toFixed(4)},${pos.getY(i).toFixed(4)},${pos.getZ(i).toFixed(4)}`;
  const vid = new Map(),
    id = (i) => {
      const k = key(i);
      if (!vid.has(k)) vid.set(k, vid.size);
      return vid.get(k);
    };
  const edges = new Map(),
    adj = Array.from({length: n}, () => []);
  for (let t = 0; t < n; t++) {
    const v = [id(t * 3), id(t * 3 + 1), id(t * 3 + 2)];
    for (const [x, y] of [
      [v[0], v[1]],
      [v[1], v[2]],
      [v[2], v[0]],
    ]) {
      const k = x < y ? `${x}_${y}` : `${y}_${x}`;
      const o = edges.get(k);
      if (o != null) {
        adj[t].push(o);
        adj[o].push(t);
      } else edges.set(k, t);
    }
  }
  return (p.adj = adj);
}
function paintTris(p, pi, tris) {
  const st = PM.state,
    c = p.mesh.geometry.getAttribute('color'),
    col = new T.Color(colour(st || p.extruder));
  let pend = PM.pending.get(pi);
  if (!pend) PM.pending.set(pi, (pend = new Map()));
  let set = pend.get(st);
  if (!set) pend.set(st, (set = new Set()));
  for (const t of tris) {
    if (p.paint[t] === st) continue;
    p.paint[t] = st;
    set.add(t);
    for (let j = 0; j < 3; j++) c.setXYZ(t * 3 + j, col.r, col.g, col.b);
  }
  if (!p.mesh.material.vertexColors) {
    p.mesh.material.vertexColors = true;
    p.mesh.material.color.set(0xffffff);
    p.mesh.material.needsUpdate = true;
  }
  c.needsUpdate = true;
}
function paintAt(e) {
  cast(e);
  const o = PM.o,
    solid = o.parts.filter((p) => p.type === 'normal_part');
  const h = ray.intersectObjects(solid.map((p) => p.mesh))[0];
  if (!h) return;
  const p = o.parts.find((x) => x.mesh === h.object),
    pi = o.parts.indexOf(p);
  ensurePaint(p);
  o.group.updateMatrixWorld(true);
  const inv = o.group.matrixWorld.clone().invert(),
    hl = h.point.clone().applyMatrix4(inv),
    k = o.group.scale.x;
  if (PM.tool === 'fill') {
    const adj = adjacency(p),
      {nr} = p.local,
      f = h.faceIndex,
      lim = Math.cos((PM.angle * Math.PI) / 180),
      seen = new Set([f]),
      q = [f],
      out = [];
    while (q.length) {
      const t = q.pop();
      out.push(t);
      for (const u of adj[t])
        if (!seen.has(u)) {
          seen.add(u);
          const nprev = nr[t * 3] * nr[u * 3] + nr[t * 3 + 1] * nr[u * 3 + 1] + nr[t * 3 + 2] * nr[u * 3 + 2];
          if (nprev >= lim) q.push(u);
        }
    }
    return paintTris(p, pi, out);
  }
  addDot(h, o);
  // stroke sample (world); spaced at ~1/3 radius
  const last = PM.stroke.at(-1),
    wp = h.point;
  if (
    !last ||
    last.pi !== pi ||
    Math.hypot(wp.x - last.center[0], wp.y - last.center[1], wp.z - last.center[2]) > PM.size / 3
  )
    PM.stroke.push({pi, center: [wp.x, wp.y, wp.z], radius: PM.size});
  // instant preview: only triangles the brush covers completely (the server adds the exact edge)
  const pos = p.mesh.geometry.getAttribute('position'),
    r2 = (PM.size / k) ** 2,
    n = pos.count / 3,
    out = [],
    v = new T.Vector3();
  for (let t = 0; t < n; t++) {
    let inside = true;
    for (let j = 0; j < 3 && inside; j++) {
      v.fromBufferAttribute(pos, t * 3 + j);
      inside = v.distanceToSquared(hl) <= r2;
    }
    if (inside) out.push(t);
  }
  previewTris(p, out);
}
const dotGeo = new T.CircleGeometry(1, 28);
function addDot(h, o) {
  // instant feedback: a disc of the brush size lying on the surface
  if (!PM.dots) {
    PM.dots = new T.Group();
    scene.add(PM.dots);
  }
  const n = h.face.normal.clone().transformDirection(o.group.matrixWorld);
  const d = new T.Mesh(
    dotGeo,
    new T.MeshBasicMaterial({
      color: colour(PM.state || o.parts.find((p) => p.mesh === h.object).extruder),
      side: T.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: -4,
      polygonOffsetUnits: -4,
    })
  );
  d.scale.setScalar(PM.size);
  d.position.copy(h.point).addScaledVector(n, 0.05);
  d.lookAt(h.point.clone().addScaledVector(n, 1));
  PM.dots.add(d);
}
function clearDots() {
  if (PM?.dots) {
    scene.remove(PM.dots);
    PM.dots.children.forEach((d) => d.material.dispose());
    PM.dots = null;
  }
}
function cancelStroke() {
  // second finger = navigation: drop the stroke and its preview
  if (!PM) return;
  PM.stroke = [];
  painting = false;
  clearDots();
  recolour();
}
function previewTris(p, tris) {
  const c = p.mesh.geometry.getAttribute('color'),
    col = new T.Color(colour(PM.state || p.extruder));
  for (const t of tris) for (let j = 0; j < 3; j++) c.setXYZ(t * 3 + j, col.r, col.g, col.b);
  if (!p.mesh.material.vertexColors) {
    p.mesh.material.vertexColors = true;
    p.mesh.material.color.set(0xffffff);
    p.mesh.material.needsUpdate = true;
  }
  c.needsUpdate = true;
}
async function flushPaint() {
  if (!PM) return;
  PM.busy = true;
  try {
    await sendPaint();
  } finally {
    if (PM) {
      PM.busy = false;
      clearDots();
    }
  }
}
async function sendPaint() {
  if (PM.stroke.length) {
    // adaptive brush stroke -> server (Orca paint trees), then fetch the exact result
    const o = PM.o,
      byPart = {};
    for (const s of PM.stroke) (byPart[s.pi] ??= []).push({center: s.center, radius: s.radius});
    PM.stroke = [];
    const st = PM.state;
    for (const [pi, strokes] of Object.entries(byPart)) {
      const r = await op({op: 'paint_brush', id: o.id, part: +pi, filament: st, strokes});
      if (r) {
        o.gid = r.gid;
        await refreshPaint(o, r.gid);
      }
    }
  }
  if (!PM || !PM.pending.size) return;
  const jobs = [...PM.pending];
  PM.pending = new Map();
  for (const [pi, m] of jobs) {
    const set = Object.fromEntries([...m].filter(([, s]) => s.size).map(([st, s]) => [st, [...s]]));
    if (!Object.keys(set).length) continue;
    const r = await op({op: 'paint', id: PM.o.id, part: pi, set});
    if (r && PM) {
      PM.o.gid = r.gid;
      await refreshPaint(PM.o, r.gid);
    }
  }
}
function pbChips() {
  const C = $('pbChips');
  C.innerHTML = '';
  const er = el('button', 'er' + (PM.state === 0 ? ' on' : ''), '⌫');
  er.title = 'Erase (back to the part filament)';
  er.onclick = () => {
    PM.state = 0;
    pbChips();
  };
  C.append(er);
  for (let i = 1; i <= nPhys() + mix.length; i++) {
    const b = el('button', PM.state === i ? 'on' : '', i);
    b.style.background = chipBg(i);
    b.style.color = i > nPhys() ? '#fff' : ink(fcol(i));
    b.onclick = () => {
      PM.state = i;
      pbChips();
    };
    C.append(b);
  }
}
function pbTri() {
  const n = PM.o.parts
    .filter((p) => p.type === 'normal_part')
    .reduce((s, p) => s + p.mesh.geometry.getAttribute('position').count / 3, 0);
  $('pbTitle').textContent = `Paint · ${PM.o.name} · ${n} △`;
}
function openPaint(o) {
  closePreview();
  selected = o;
  PM = {o, tool: 'brush', size: 4, angle: 30, state: Math.min(2, nPhys()), pending: new Map(), stroke: []};
  document.body.classList.add('paint');
  $('paintbar').hidden = false;
  $('sheet').dataset.state = 'peek';
  ctl.mouseButtons = {LEFT: null, MIDDLE: T.MOUSE.DOLLY, RIGHT: T.MOUSE.ROTATE};
  ctl.touches = {ONE: null, TWO: T.TOUCH.DOLLY_ROTATE};
  $('pbHint').textContent = matchMedia('(pointer:fine)').matches
    ? 'Left button paints · right button rotates · wheel zooms'
    : 'One finger paints · two fingers rotate/zoom';
  setTool('brush');
  pbChips();
  pbTri();
  placeBars();
  refresh();
}
function closePaint() {
  if (!PM) return;
  flushPaint();
  PM = null;
  document.body.classList.remove('paint');
  $('paintbar').hidden = true;
  ctl.mouseButtons = {LEFT: T.MOUSE.ROTATE, MIDDLE: T.MOUSE.DOLLY, RIGHT: T.MOUSE.PAN};
  ctl.touches = {ONE: T.TOUCH.ROTATE, TWO: T.TOUCH.DOLLY_PAN};
  if ($('sheet').dataset.state === 'peek') $('sheet').dataset.state = 'half';
}
function setTool(t) {
  PM.tool = t;
  for (const b of $('pbTool').children) b.classList.toggle('on', b.dataset.t === t);
  const s = $('pbSize');
  if (t === 'fill') {
    $('pbLab').textContent = 'Angle';
    Object.assign(s, {min: 5, max: 90, step: 5});
    s.value = PM.angle;
  } else {
    $('pbLab').textContent = 'Size';
    Object.assign(s, {min: 0.5, max: 20, step: 0.5});
    s.value = PM.size;
  }
  $('pbVal').textContent = t === 'fill' ? `${PM.angle}°` : `${PM.size} mm`;
}
$('pbTool').onclick = (e) => e.target.dataset.t && setTool(e.target.dataset.t);
$('pbSize').oninput = () => {
  if (PM.tool === 'fill') PM.angle = +$('pbSize').value;
  else PM.size = +$('pbSize').value;
  setTool(PM.tool);
};
$('pbClose').onclick = closePaint;
$('pbRepl').onclick = async () => {
  // pick a colour used by the object, then the filament that replaces it
  const o = PM.o;
  await flushPaint();
  const used = await (await fetch('/api/colours/used?id=' + o.id)).json(),
    g = el('div', 'grid');
  for (const i of used) {
    const b = el('button');
    b.style.background = chipBg(i);
    b.style.color = i > nPhys() ? '#fff' : ink(fcol(i));
    if (i > nPhys()) b.style.textShadow = '0 1px 2px #000';
    b.innerHTML = `${i}<small>${fname(i)}</small>`;
    b.onclick = () => {
      closeModal();
      pickFilament(0, async (to) => {
        const r = await op({op: 'replace_colour', id: o.id, from: i, to});
        if (r) toast(`Colour ${i} → ${to}`);
      });
    };
    g.append(b);
  }
  modal('Replace which colour?', g);
};
function placeBars() {
  if (!$('paintbar').hidden && !WIDE.matches)
    $('paintbar').style.bottom = innerHeight - $('sheet').getBoundingClientRect().top + 10 + 'px';
}
new ResizeObserver(placeBars).observe($('sheet'));
$('sheet').addEventListener('transitionend', placeBars);

// ---------- G-code preview
const TYPECOL = [
  '#ff8a3d',
  '#ffd166',
  '#4dabf7',
  '#b5543c',
  '#a37bd6',
  '#ef476f',
  '#8ecae6',
  '#4cc9f0',
  '#3a86ff',
  '#ffffff',
  '#52b788',
  '#95d5b2',
  '#8d949b',
  '#adb5bd',
  '#adb5bd',
  '#ff99c8',
  '#666666',
];
let PV = null;
async function pvLoad(job) {
  const [meta, buf] = await Promise.all([
    fetch(`/job/${job}/preview.json`).then((r) => r.json()),
    fetch(`/job/${job}/preview.bin`).then((r) => r.arrayBuffer()),
  ]);
  if (meta.error) throw new Error(meta.error);
  const dv = new DataView(buf),
    n = meta.count;
  const pos = new Float32Array(n * 6),
    tool = new Uint8Array(n),
    typ = new Uint8Array(n),
    ends = new Uint32Array(meta.layers.length);
  for (let i = 0; i < n; i++) {
    const o = i * 12,
      L = dv.getUint16(o + 8, true),
      z = meta.layers[L];
    pos.set(
      [
        dv.getInt16(o, true) / 100,
        dv.getInt16(o + 2, true) / 100,
        z,
        dv.getInt16(o + 4, true) / 100,
        dv.getInt16(o + 6, true) / 100,
        z,
      ],
      i * 6
    );
    tool[i] = dv.getUint8(o + 10);
    typ[i] = dv.getUint8(o + 11);
    ends[L] = i + 1;
  }
  for (let L = 1; L < ends.length; L++) ends[L] = Math.max(ends[L], ends[L - 1]);
  const posA = new T.BufferAttribute(pos, 3),
    colA = new T.BufferAttribute(new Float32Array(n * 6), 3);
  const gAll = new T.BufferGeometry(),
    gTop = new T.BufferGeometry();
  for (const g of [gAll, gTop]) {
    g.setAttribute('position', posA);
    g.setAttribute('color', colA);
  }
  const grp = new T.Group();
  grp.add(
    new T.LineSegments(gAll, new T.LineBasicMaterial({vertexColors: true, color: 0x8a8a8a})),
    new T.LineSegments(gTop, new T.LineBasicMaterial({vertexColors: true}))
  );
  return {meta, tool, typ, ends, colA, gAll, gTop, grp};
}
// r = slice result: every sliced plate is shown at its own place on the bed
async function openPreview(r) {
  toast('Loading preview…');
  const jobs = (r.plates || []).filter((x) => x.ok).map((x) => ({job: x.job, plate: x.plate}));
  if (!jobs.length) jobs.push({job: r.job, plate: 1});
  let parts;
  try {
    parts = await busy(Promise.all(jobs.map((j) => pvLoad(j.job))));
  } catch (e) {
    return toast(e.message, true);
  }
  closePreview();
  parts.forEach((p, i) => {
    p.plate = jobs[i].plate;
    p.grp.position.copy(plateOffset(p.plate));
    scene.add(p.grp);
  });
  PV = {parts};
  const pl = parts.some((p) => p.plate === curPlate) ? curPlate : parts[0].plate;
  if (pl !== curPlate) {
    curPlate = pl;
    view(lastView);
    objList();
  }
  for (const o of objs) o.group.visible = false;
  wipeMeshes.forEach((w) => (w.visible = false));
  const nl = Math.max(...parts.map((p) => p.ends.length));
  $('pvSlider').max = nl - 1;
  $('pvSlider').value = nl - 1;
  $('prevbar').hidden = false;
  $('sheet').dataset.state = 'peek';
  placePrevbar();
  setMode('prev');
  selected = null;
  refresh();
  pvColour('tool');
  pvLayer();
  $('toast').hidden = true;
}
function pvColour(mode) {
  const col = new T.Color(),
    cache = {};
  for (const P of PV.parts) {
    const c = P.colA.array,
      n = P.tool.length;
    for (let i = 0; i < n; i++) {
      const k = mode === 'tool' ? P.tool[i] : 100 + P.typ[i];
      const v = (cache[k] ??= col.set(mode === 'tool' ? fcol(P.tool[i] + 1) : TYPECOL[P.typ[i]] || '#888').clone());
      c[i * 6] = c[i * 6 + 3] = v.r;
      c[i * 6 + 1] = c[i * 6 + 4] = v.g;
      c[i * 6 + 2] = c[i * 6 + 5] = v.b;
    }
    P.colA.needsUpdate = true;
  }
  for (const b of $('pvMode').children) b.classList.toggle('on', b.dataset.m === mode);
  const leg = $('pvLegend');
  leg.innerHTML = '';
  if (mode === 'tool')
    S.filaments.forEach((f, i) => {
      const s = el('span');
      s.innerHTML = `<i style="background:${f.colour}"></i>${i + 1}`;
      leg.append(s);
    });
  else
    [...new Set(PV.parts.flatMap((P) => [...new Set(P.typ)].map((t) => [t, P.meta.types[t]])).map((x) => x.join('|')))]
      .map((x) => x.split('|'))
      .sort((p, q) => p[0] - q[0])
      .forEach(([t, name]) => {
        const s = el('span');
        s.innerHTML = `<i style="background:${TYPECOL[t]}"></i>${name}`;
        leg.append(s);
      });
}
function pvLayer() {
  const L0 = +$('pvSlider').value;
  for (const P of PV.parts) {
    const L = Math.min(L0, P.ends.length - 1), // plates can differ in height
      start = L ? P.ends[L - 1] : 0,
      end = P.ends[L];
    P.gAll.setDrawRange(0, start * 2);
    P.gTop.setDrawRange(start * 2, (end - start) * 2);
  }
  const P = PV.parts.find((p) => p.plate === curPlate) || PV.parts[0],
    L = Math.min(L0, P.ends.length - 1);
  $('pvLayer').textContent = `Layer ${L + 1} / ${P.ends.length} · Z ${P.meta.layers[L].toFixed(2)} mm`;
}
function setMode(m) {
  document.body.classList.toggle('prev', m === 'prev');
  for (const b of $('modeSeg').children) b.classList.toggle('on', b.dataset.mode === m);
}
function closePreview() {
  setMode('prep');
  if (!PV) return;
  for (const P of PV.parts) {
    scene.remove(P.grp);
    P.gAll.dispose();
    P.gTop.dispose();
  }
  PV = null;
  for (const o of objs) o.group.visible = true;
  wipeMeshes.forEach((w, i) => (w.visible = S.wipe.enabled && objs.some((o) => o.plate === i + 1)));
  $('prevbar').hidden = true;
  if ($('sheet').dataset.state === 'peek') $('sheet').dataset.state = 'half';
}
function placePrevbar() {
  if (!$('prevbar').hidden && !WIDE.matches)
    $('prevbar').style.bottom = innerHeight - $('sheet').getBoundingClientRect().top + 10 + 'px';
}
new ResizeObserver(placePrevbar).observe($('sheet'));
$('sheet').addEventListener('transitionend', placePrevbar);
$('pvSlider').oninput = pvLayer;
$('pvMode').onclick = (e) => e.target.dataset.m && pvColour(e.target.dataset.m);
$('pvClose').onclick = closePreview;

// ---------- object tools (all via server ops)
$('rail').onclick = async (e) => {
  const a = e.target.closest('[data-a]')?.dataset.a;
  if (!a) return;
  if (a === 'arr') {
    const r = await op({op: 'arrange', plate: curPlate});
    if (r) toast(r.off_bed?.length ? `Did not fit: ${r.off_bed.join(', ')}` : 'Arranged', !!r.off_bed?.length);
    return;
  }
  const o = selected;
  if (!o) return toast('Select an object first — tap it in the 3D view or in the list', true);
  if (a === 'set') return objectModal(o);
  if (a === 'paint') return PM ? closePaint() : openPaint(o);
  if (a === 'gz') {
    $('gzMenu').hidden = !$('gzMenu').hidden;
    return;
  } // tool picker opens to the right
  if (a.startsWith('gz-')) {
    GZ = a.slice(3);
    LAY = false;
    $('gzMenu').hidden = true;
    return gizmo();
  }
  if (a === 'lay') {
    LAY = !LAY;
    gizmo();
    return LAY && toast('Tap the face that should lie on the bed');
  }
  if (a === 'drop') {
    const r = await op({op: 'drop', id: o.id});
    return r?.msg && toast(r.msg);
  }
  const r = await op(a === 'del' ? {op: 'del', id: o.id} : {op: 'dup', id: o.id, arrange: false});
  if (r?.msg) toast(r.msg);
};

// ---------- picking / dragging (local while dragging, one op on release)
const ray = new T.Raycaster(),
  ptr = new T.Vector2(),
  plane = new T.Plane(new T.Vector3(0, 0, 1), 0);
let drag = null,
  down = null;
function cast(e) {
  ptr.set((e.clientX / innerWidth) * 2 - 1, (-e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ptr, cam);
}
function ground(e) {
  cast(e);
  const p = new T.Vector3();
  return ray.ray.intersectPlane(plane, p) ? p : null;
}
const meshes = () => objs.flatMap((o) => o.group.children);
let painting = false,
  armAt = 0;
const fingers = new Set();
cv.addEventListener('pointerdown', (e) => {
  down = [e.clientX, e.clientY];
  if (!S || PV) return;
  fingers.add(e.pointerId);
  if (PM) {
    if (fingers.size > 1) return cancelStroke(); // two fingers rotate/zoom, never paint
    if (e.button === 0 && e.isPrimary) {
      painting = true;
      if (e.pointerType === 'touch')
        armAt = performance.now() + 90; // wait whether a second finger follows
      else {
        armAt = 0;
        paintAt(e);
      }
    }
    return;
  }
  if (tc.dragging) {
    gizmoDown = true;
    return;
  } // TransformControls (registered first) grabbed a handle
  if (LAY) return; // the tap picks a face, it must not start a drag
  cast(e);
  if (
    ray.intersectObjects(
      wipeMeshes.filter((w) => w.visible),
      false
    ).length
  ) {
    const g = ground(e);
    drag = {wipe: true, g0: g, x0: S.wipe.x, y0: S.wipe.y};
    ctl.enabled = false;
    return;
  }
  const h = ray.intersectObjects(meshes())[0];
  if (h && h.object.userData.obj === selected) {
    const g = ground(e);
    if (g) {
      drag = {o: selected, g0: g, p0: selected.group.position.clone()};
      ctl.enabled = false;
    }
  }
});
cv.addEventListener('pointermove', (e) => {
  if (painting && PM && PM.tool === 'brush') {
    if (fingers.size === 1 && performance.now() >= armAt) paintAt(e);
    return;
  }
  if (!drag) return;
  const g = ground(e);
  if (!g) return;
  if (drag.wipe) {
    drag.x = drag.x0 + g.x - drag.g0.x;
    drag.y = drag.y0 + g.y - drag.g0.y;
    showWipe(drag.x, drag.y);
  } else drag.o.group.position.set(drag.p0.x + g.x - drag.g0.x, drag.p0.y + g.y - drag.g0.y, drag.p0.z);
});
addEventListener('pointercancel', (e) => {
  fingers.delete(e.pointerId);
  if (PM) cancelStroke();
  painting = false;
});
addEventListener('pointerup', async (e) => {
  fingers.delete(e.pointerId);
  if (painting) {
    painting = false;
    if (PM && PM.tool === 'fill' && e.pointerType === 'touch' && !PM.stroke.length) paintAt(e); // fill = a tap
    flushPaint();
    return;
  }
  if (PM) return;
  if (gizmoDown) {
    gizmoDown = false;
    return;
  }
  const moved = down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > (e.pointerType === 'touch' ? 12 : 6);
  if (drag) {
    const d = drag;
    ctl.enabled = true;
    if (moved && !d.wipe) {
      // dropped onto another plate? re-base the object into that plate's coordinates
      const c = bbox(d.o).getCenter(new T.Vector3()),
        p = plateAt(c);
      if (p && p !== d.o.plate) {
        d.o.group.position.add(plateOffset(d.o.plate)).sub(plateOffset(p));
        plateGroups[p - 1].add(d.o.group);
        d.o.plate = p;
        curPlate = p;
      }
      const r = await op({op: 'move', id: d.o.id, m: getM(d.o.group), plate: d.o.plate});
      if (r?.msg) toast(r.msg);
    } else if (moved) {
      const r = await op({op: 'set_wipe', x: d.x, y: d.y});
      if (r?.msg) toast(r.msg);
    }
    drag = null;
    if (S) apply(S);
    return;
  }
  if (e.target !== cv || !down || !S || moved || PV) return;
  cast(e);
  const h = ray.intersectObjects(meshes())[0];
  if (LAY && selected && h?.object.userData.obj === selected) return layOnFace(selected, h);
  selected = h ? h.object.userData.obj : null;
  if (selected) curPlate = selected.plate;
  refresh();
});
async function layOnFace(o, h) {
  // rotate about the bbox centre so the tapped face's normal points down, then drop onto the bed
  const n = h.face.normal.clone().applyMatrix3(new T.Matrix3().getNormalMatrix(h.object.matrixWorld)).normalize(),
    q = new T.Quaternion().setFromUnitVectors(n, new T.Vector3(0, 0, -1));
  const c = bbox(o).getCenter(new T.Vector3()).sub(plateOffset(o.plate)),
    g = o.group;
  g.position.sub(c).applyQuaternion(q).add(c);
  g.quaternion.premultiply(q);
  LAY = false;
  const r = await op({op: 'move', id: o.id, m: getM(g), plate: o.plate, drop: true});
  if (r?.msg) toast(r.msg);
  if (S) apply(S);
}

// ---------- server
// top progress bar while any slow request is in flight (uploads, ops, geometry fetch)
let nBusy = 0;
const busy = (p) => {
  $('busy').hidden = false;
  nBusy++;
  return Promise.resolve(p).finally(() => {
    if (!--nBusy) $('busy').hidden = true;
  });
};
async function op(body) {
  const r = await busy(fetch('/api/op', {method: 'POST', body: JSON.stringify(body)}).then((r) => r.json()));
  if (r.error) {
    toast(r.error, true);
    return null;
  }
  return r;
}
async function call(url, opt) {
  const r = await busy(fetch(url, opt).then((r) => r.json()));
  if (r.error) toast(r.error, true);
  return r.error ? null : r;
}
const postJ = (url, o) => call(url, {method: 'POST', body: JSON.stringify(o || {})});

$('fileBtn').onclick = async () => {
  const fs = await (await fetch('/api/files')).json(),
    box = el('div', 'flist');
  const act = (ic, t, sub, fn) => {
    const b = el('button');
    b.innerHTML = `<span class="ic">${icon(ic)}</span><span>${t}<small>${sub}</small></span>`;
    b.onclick = fn;
    box.append(b);
  };
  const go = (p) => {
    closeModal();
    toast('Loading…');
    p.then((r) => {
      if (r) {
        $('toast').hidden = true;
        selected = null;
      }
    });
  };
  act('new', 'New project', 'Empty U1 plate, 4 filaments', () => go(postJ('/api/new')));
  const up = Object.assign(el('input'), {type: 'file', accept: '.3mf', hidden: true});
  up.onchange = () => {
    const f = up.files[0];
    if (f) go(call('/api/upload?name=' + encodeURIComponent(f.name), {method: 'POST', body: f}));
  };
  act('up', 'Upload from device', '3MF project', () => up.click());
  box.append(up);
  const groups = {};
  for (const f of fs.filter((f) => f.endsWith('.3mf'))) (groups[f.split('/')[0]] ??= []).push(f);
  for (const [g, list] of Object.entries(groups)) {
    box.append(el('h4', '', g));
    for (const f of list)
      act(
        'file',
        f
          .split('/')
          .pop()
          .replace(/\.3mf$/, ''),
        g,
        () => go(postJ('/api/open', {path: f}))
      );
  }
  modal('Projects', box);
};

$('add').onchange = async (e) => {
  const f = e.target.files[0];
  e.target.value = '';
  if (!f) return;
  toast(/\.zip$/i.test(f.name) ? 'Unpacking…' : 'Adding…');
  const r = await busy(
    fetch(`/api/add?name=${encodeURIComponent(f.name)}&plate=${curPlate}`, {method: 'POST', body: f}).then((r) =>
      r.json()
    )
  );
  if (r.ok)
    toast(
      r.added > 1
        ? `Added ${r.added} objects from ${f.name}`
        : r.msg
          ? `Added ${f.name} — ${r.msg}`
          : `Added: ${f.name}`
    );
  else if (!r.ignored?.length) return toast(r.error, true);
  if (r.ignored?.length) {
    // a zip with other stuff in it: say what was skipped
    const box = el('div', 'ignored');
    box.append(
      el(
        'p',
        '',
        r.ok
          ? `Added ${r.added} object${r.added === 1 ? '' : 's'}${r.folder ? ` (files saved in ${r.folder})` : ''}. These were skipped:`
          : r.error + '. Skipped:'
      )
    );
    const ul = el('ul');
    for (const x of r.ignored) {
      const li = el('li');
      li.append(el('b', '', x.file), el('small', 'mut', ' — ' + x.why));
      ul.append(li);
    }
    box.append(ul);
    modal(`Skipped ${r.ignored.length} file${r.ignored.length === 1 ? '' : 's'}`, box);
  }
};

// file name on the printer: defaults like Orca's "<project>_<types>_<time>", editable; asks before overwriting
function defaultName(d) {
  const types = [...new Set(S.filaments.map((f) => f.type))].join('-'),
    t = (d.time || '').replace(/\s*\d+s$/, '').replace(/\s+/g, '');
  return [projName || 'u1web', (S.result?.plates?.length || 0) > 1 ? 'plate' + d.plate : '', types, t]
    .filter(Boolean)
    .join('_');
}
async function askName(d) {
  const n = prompt('File name on the printer', defaultName(d));
  return n && n.trim().replace(/\.gcode$/i, '');
}
async function sendGcode(body) {
  let r = await busy(fetch('/api/printer/send', {method: 'POST', body: JSON.stringify(body)}).then((r) => r.json()));
  if (r.stale) {
    if (
      !confirm(
        'This G-code is from before your latest changes. Send the OLD version anyway?\n(Cancel and press Slice to include the changes.)'
      )
    )
      return null;
    body = {...body, stale_ok: true};
    r = await busy(fetch('/api/printer/send', {method: 'POST', body: JSON.stringify(body)}).then((r) => r.json()));
  }
  if (r.exists) {
    if (!confirm(`"${r.file}" already exists on the printer. Overwrite it?`)) return null;
    r = await busy(
      fetch('/api/printer/send', {method: 'POST', body: JSON.stringify({...body, overwrite: true})}).then((r) =>
        r.json()
      )
    );
  }
  if (r.error) {
    toast(r.error, true);
    return null;
  }
  return r;
}
function plateResult(R, d, multi) {
  // one plate: thumb, time and grams; then Send / Print / G-code in one row
  if (!d.ok) {
    R.append(el('div', 'warn', `⚠ Plate ${d.plate}: ${d.error}`));
    return;
  }
  const top = el('div', 'rt' + (multi ? ' pl' : '')),
    tg = el('div', 'tg');
  if (multi) top.append(el('b', 'pn', d.plate));
  if (d.thumb) {
    const im = el('img', 'thumb');
    im.src = d.thumb;
    im.title = 'Thumbnail embedded in the G-code (shown on the printer)';
    top.append(im);
  }
  tg.append(
    el('span', 'big', d.time || '?'),
    el(
      'small',
      'mut',
      `${d.grams || '?'} g of filament` +
        (d.tower_g ? ` · ${d.tower_g} g prime tower, ${(d.grams - d.tower_g).toFixed(1)} g print` : '')
    )
  );
  top.append(tg);
  R.append(top);
  const a = el('a');
  a.href = d.gcode;
  a.innerHTML = `<span class="ic">${icon('dl')}</span>G-code`;
  const pr = el('div', 'rt'),
    send = el('button', 'btn2'),
    go = el('button', 'btn2 go');
  send.innerHTML = `<span class="ic">${icon('send')}</span>Send`;
  go.innerHTML = `<span class="ic">${icon('printer')}</span>Print`;
  send.title = 'Upload the G-code to the U1 (start it on the printer)';
  go.title = 'Upload and start printing now';
  a.title = 'Download the G-code';
  send.onclick = async () => {
    const name = await askName(d);
    if (!name) return;
    send.disabled = true;
    const r = await sendGcode({name, plate: d.plate});
    send.disabled = false;
    if (r) toast(`Uploaded ${r.file} — start it on the printer`);
  };
  go.onclick = async () => {
    await loadPrinter();
    if (PR?.state === 'printing' || PR?.state === 'paused')
      return toast(`Printer is ${PR.state} (${PR.file}) — use Send instead`, true);
    const name = await askName(d);
    if (!name) return;
    if (
      !confirm(
        `Start printing "${name}" on the U1 now?\n${multi ? `Plate ${d.plate}: ` : ''}${d.time}, ${d.grams} g. Check the bed is clear.`
      )
    )
      return;
    go.disabled = true;
    const r = await sendGcode({start: true, name, plate: d.plate});
    go.disabled = false;
    if (r) toast(r.started ? `Printing ${r.file}` : `Uploaded ${r.file} (queued: ${r.queued})`);
  };
  pr.append(send, go, a);
  R.append(pr);
}
function showResult(d) {
  const R = $('result');
  R.hidden = false;
  R.className = d.ok ? (d.stale ? 'stale' : '') : 'err';
  R.innerHTML = '';
  $('slice').classList.toggle('attn', !!d.stale || !d.ok);
  $('slice').classList.toggle('quiet', !!d.ok && !d.stale);
  const bar = el('div', 'rbar'),
    tg = el('button', 'ibtn'),
    x = el('button', 'ibtn');
  bar.append(
    el(
      'span',
      '',
      !d.ok ? 'Slicing failed' : `${d.stale ? 'Old slice' : 'Sliced'} · ${d.time || '?'} · ${d.grams || '?'} g`
    ),
    tg,
    x
  );
  tg.innerHTML = icon('chev');
  tg.title = 'Collapse / expand';
  tg.onclick = () => {
    localStorage.resMin = localStorage.resMin === '1' ? '' : '1';
    R.classList.toggle('min', localStorage.resMin === '1');
  };
  x.innerHTML = icon('x');
  x.title = 'Discard this slice';
  x.onclick = () => op({op: 'clear_result'});
  R.classList.toggle('min', localStorage.resMin === '1');
  R.append(bar);
  if (!d.ok) {
    R.append(el('div', '', d.error));
    return;
  }
  const pls = d.plates || [{...d, plate: 1}],
    multi = pls.length > 1;
  if (multi)
    R.append(
      el(
        'div',
        'rsum',
        `${pls.length} plates · ${d.time} · ${d.grams} g total — each plate is its own G-code, print them one after another`
      )
    );
  if (d.stale) {
    const w = el('div', 'stalebar');
    w.append(el('span', '', '⟳ The plate changed since this slice — slice again'));
    const b = el('button', 'btn2', 'Slice again');
    b.onclick = () => $('slice').click();
    w.append(b);
    R.append(w);
  }
  for (const p of pls) plateResult(R, p, multi);
  if (d.warning) {
    const w = el('div', 'warn');
    w.append(el('span', '', '⚠ ' + d.warning));
    if (/support/i.test(d.warning) && S.settings.enable_support !== '1' && S.overrides.enable_support !== '1') {
      const b = el('button', 'btn2', 'Enable supports');
      b.onclick = async () => {
        if (await op({op: 'set_global', settings: {enable_support: '1'}})) toast('Supports enabled — slice again');
      };
      w.append(b);
    }
    R.append(w);
  }
  const each = (d.grams_each || '')
    .split(',')
    .map(Number)
    .filter((x) => !isNaN(x));
  if (each.reduce((p, q) => p + q, 0) > 0) {
    const bars = el('div', 'bars'),
      leg = el('div', 'legend');
    each.forEach((g, i) => {
      if (!g) return;
      const b = el('i');
      b.style.flex = g;
      b.style.background = fcol(i + 1);
      bars.append(b);
      const s = el('span');
      s.innerHTML = `<i style="background:${fcol(i + 1)}"></i>${i + 1}: ${g.toFixed(1)} g`;
      leg.append(s);
    });
    R.append(bars, leg);
  }
}
$('modeSeg').onclick = (e) => {
  const m = e.target.dataset.mode;
  if (!m || e.target.disabled) return;
  m === 'prev' ? openPreview(S.result) : closePreview();
};
$('slice').onclick = async () => {
  const b = $('slice');
  if (b.classList.contains('busy')) return fetch('/api/slice_abort', {method: 'POST'}); // second tap = abort
  closePreview();
  b.classList.add('busy');
  b.lastChild.textContent = 'Slicing… tap to abort';
  const poll = setInterval(async () => {
    const p = await (await fetch('/api/slice_progress')).json().catch(() => null);
    if (!p?.stage) return;
    b.lastChild.textContent = `${p.of > 1 ? `Plate ${p.plate}/${p.of} · ` : ''}${p.stage} · ${Math.round(p.elapsed)}s · tap to abort`;
  }, 800);
  const d = await postJ('/api/slice');
  clearInterval(poll);
  b.classList.remove('busy');
  b.lastChild.textContent = 'Slice';
  if (d?.ok) openPreview(d);
  else if ($('sheet').dataset.state === 'peek') $('sheet').dataset.state = 'half';
};
$('save').onclick = async () => {
  const name = prompt('Project name (saved to the projects folder)', projName || 'project');
  if (!name) return;
  const d = await postJ('/api/save', {name});
  if (d) toast('Saved: ' + d.path);
};

// undo / redo (server-side snapshot history, shared by every window and MCP)
async function step(dir) {
  const r = await postJ('/api/' + dir);
  if (r) toast(r.msg);
}
$('undo').onclick = () => step('undo');
$('redo').onclick = () => step('redo');
addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
  const k = e.key.toLowerCase();
  if (k === 'z' && !e.shiftKey) {
    e.preventDefault();
    step('undo');
  } else if ((k === 'z' && e.shiftKey) || k === 'y') {
    e.preventDefault();
    step('redo');
  }
});

// live updates: browser, MCP and other tabs all edit the same session
function connect() {
  const es = new EventSource('/api/events');
  es.addEventListener('state', (e) => apply(JSON.parse(e.data)));
  es.onerror = () => {
    es.close();
    setTimeout(connect, 2000);
  };
}
connect();
