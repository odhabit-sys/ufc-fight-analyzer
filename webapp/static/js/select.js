// Fighter selection: click Fighter 1 (red), then Fighter 2 (blue), then start.
// Boxes come from the detection stage's cache; nobody is pre-selected, so the referee or
// a spectator can only be chosen by explicitly clicking them.
const $ = id => document.getElementById(id);
const COLORS = ['#ff3b4e', '#2fa8ff'];

let state = null;

export function closeSelect() { state = null; }

export async function openSelect(id, setFile) {
  state = { id, picks: [], frameIdx: 0, sel: null, hover: null };
  const s = state;
  $('sel-error').hidden = true;
  $('sel-loading').hidden = false;
  $('sel-boxes').innerHTML = '';
  $('sel-frames').innerHTML = '';
  $('sel-img').removeAttribute('src');

  const job = await (await fetch(`/api/jobs/${id}`)).json();
  setFile(job.name);
  const cancel = $('sel-cancel');
  cancel.hidden = job.status !== 'done';          // "Change fighters": allow going back
  cancel.href = `#/analysis/${id}`;

  const r = await fetch(`/api/jobs/${id}/selection`);
  if (state !== s) return;
  if (!r.ok) { location.replace(`#/processing/${id}`); return; }
  s.sel = await r.json();
  $('sel-stage').style.setProperty('--ar', s.sel.width / s.sel.height);
  buildFrameStrip();
  showFrame(s.sel.default ?? 0);
}

function buildFrameStrip() {
  const strip = $('sel-frames');
  state.sel.frames.forEach((f, k) => {
    const b = document.createElement('button');
    b.className = 'sel-thumb';
    b.innerHTML = `<img alt=""><span>${fmt(f.t)}</span>`;
    b.querySelector('img').src = `/api/jobs/${state.id}/select_${f.frame}.jpg`;
    b.addEventListener('click', () => showFrame(k));
    strip.appendChild(b);
  });
}

function showFrame(k) {
  const s = state;
  s.frameIdx = k;
  s.picks = [];                       // detections are per frame: picks reset
  s.hover = null;
  const f = s.sel.frames[k];
  const img = $('sel-img');
  img.onload = () => { $('sel-loading').hidden = true; };
  img.src = `/api/jobs/${s.id}/select_${f.frame}.jpg`;
  [...$('sel-frames').children].forEach((b, i) => b.classList.toggle('active', i === k));
  draw();
}

// Smallest box containing the point; fighters win over spectators standing behind them.
function personAt(x, y) {
  const f = state.sel.frames[state.frameIdx];
  const hits = f.people.filter(p => x >= p.box[0] && x <= p.box[2] && y >= p.box[1] && y <= p.box[3]);
  if (!hits.length) return null;
  const pool = hits.some(p => p.likely_fighter) ? hits.filter(p => p.likely_fighter) : hits;
  const area = p => (p.box[2] - p.box[0]) * (p.box[3] - p.box[1]);
  return pool.reduce((a, b) => (area(b) < area(a) ? b : a));
}

function toVideo(ev) {
  const r = $('sel-stage').getBoundingClientRect();
  return [((ev.clientX - r.left) / r.width) * state.sel.width, ((ev.clientY - r.top) / r.height) * state.sel.height];
}

function draw() {
  const s = state, f = s.sel.frames[s.frameIdx], W = s.sel.width, H = s.sel.height;
  const boxes = $('sel-boxes');
  boxes.innerHTML = '';
  const nextSlot = s.picks.length < 2 ? s.picks.length : null;
  for (const p of f.people) {
    const slot = s.picks.indexOf(p.i);
    const hover = s.hover === p.i;
    // unselected people stay neutral: faint corner marks for full-body detections,
    // a plain white outline on hover. Only a click gives a box a fighter colour.
    const cls = slot >= 0 ? 'picked' : hover ? 'hover' : p.likely_fighter ? 'idle' : null;
    if (!cls) continue;
    const d = document.createElement('div');
    d.className = `pbox ${cls}`;
    const [x1, y1, x2, y2] = p.box;
    Object.assign(d.style, { left: `${x1 / W * 100}%`, top: `${y1 / H * 100}%`,
      width: `${(x2 - x1) / W * 100}%`, height: `${(y2 - y1) / H * 100}%` });
    if (slot >= 0) {
      d.style.setProperty('--c', COLORS[slot]);
      d.innerHTML = `<span class="pbox-tag">FIGHTER ${slot + 1}</span>`;
    } else if (hover && nextSlot != null) {
      d.style.setProperty('--c', COLORS[nextSlot]);
      d.innerHTML = `<span class="pbox-tag"><i></i>SET AS FIGHTER ${nextSlot + 1}</span>`;
    }
    boxes.appendChild(d);
  }
  const n = s.picks.length;
  const steps = [['Fighter 1', COLORS[0]], ['Fighter 2', COLORS[1]], ['Start analysis', '#e9eef4']];
  $('sel-prompt').innerHTML = steps.map(([label, c], k) =>
    `<li class="${k < n ? 'ok' : k === n ? 'now' : ''}" style="--c:${c}"><i></i>${k < n ? label + ' ✓' : k === n && k < 2 ? 'Click ' + label : label}</li>`).join('');
  $('sel-start').disabled = n !== 2;
}

function bindOnce() {
  const stage = $('sel-stage');
  stage.addEventListener('pointermove', ev => {
    if (!state?.sel) return;
    const p = personAt(...toVideo(ev));
    const h = p ? p.i : null;
    stage.style.cursor = p && (state.picks.length < 2 || state.picks.includes(p.i)) ? 'pointer' : 'default';
    if (h !== state.hover) { state.hover = h; draw(); }
  });
  stage.addEventListener('pointerleave', () => { if (state?.sel) { state.hover = null; draw(); } });
  stage.addEventListener('click', ev => {
    if (!state?.sel) return;
    const p = personAt(...toVideo(ev));
    if (!p) return;
    const at = state.picks.indexOf(p.i);
    if (at >= 0) state.picks.splice(at, 1);          // click again to unselect
    else if (state.picks.length < 2) state.picks.push(p.i);
    draw();
  });
  $('sel-reset').addEventListener('click', () => { if (state?.sel) { state.picks = []; draw(); } });
  $('sel-start').addEventListener('click', submit);
}
bindOnce();

async function submit() {
  const s = state;
  if (!s || s.picks.length !== 2) return;
  $('sel-start').disabled = true;
  const f = s.sel.frames[s.frameIdx];
  const r = await fetch(`/api/jobs/${s.id}/selection`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ frame: f.frame, dets: s.picks }),
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    $('sel-error').textContent = e.detail || `Could not start the analysis (${r.status}).`;
    $('sel-error').hidden = false;
    $('sel-start').disabled = false;
    return;
  }
  localStorage.removeItem(`fa:${s.id}`);   // names / corner swap belonged to the old selection
  location.hash = `#/processing/${s.id}`;
}

function fmt(t) { const m = Math.floor(t / 60); return `${m}:${String(Math.floor(t % 60)).padStart(2, '0')}`; }
