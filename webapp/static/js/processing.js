// Processing screen: polls the job and shows the backend's real stage progress, plus a
// live view of the frame the pose model is on and the people it found there.
const $ = id => document.getElementById(id);
// Rough share of total time per stage, measured on a 2-minute 480p fight on an M1.
// Only used to combine the stages into one overall bar; each stage's own % is exact.
const WEIGHT = { prepare: 0.04, detect: 0.82, select: 0, track: 0.12, build: 0.02 };
const EDGES = [[5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];

let timer = null;
let live = null;
window.addEventListener('resize', () => drawPeople());

export function closeProcessing() {
  clearTimeout(timer);
  timer = null;
  live = null;
  const bd = $('proc-backdrop');
  bd.removeAttribute('src');
  bd.load();
  clearCanvas();
}

export function openProcessing(id, setFile) {
  closeProcessing();
  $('proc-error').hidden = true;
  $('stages').innerHTML = '';
  $('proc-placeholder').hidden = false;
  $('proc-placeholder').textContent = 'Preparing the video…';
  $('proc-frame-info').textContent = '';
  $('proc-frame').classList.remove('proc-idle');
  live = { id, videoReady: false, shownFrame: -1, wantFrame: null, people: [] };
  const mine = live;

  const poll = async () => {
    let job;
    try {
      const r = await fetch(`/api/jobs/${id}`);
      if (r.status === 404) { location.hash = '#/'; return; }
      job = await r.json();
    } catch {
      timer = setTimeout(poll, 2000);
      return;
    }
    if (live !== mine) return;
    setFile(job.name);
    $('proc-name').textContent = job.name;
    renderStages(job);
    updateLive(job);
    if (job.status === 'done') { location.replace(`#/analysis/${id}`); return; }
    if (job.status === 'needs_selection') { location.replace(`#/select/${id}`); return; }
    if (job.status === 'error') { showError(job, id); return; }
    timer = setTimeout(poll, 700);
  };
  poll();
}

// ------------------------------------------------------------------ live detection view
function updateLive(job) {
  const bd = $('proc-backdrop');
  if (!live.videoReady && job.stages[0].state === 'done' && !bd.getAttribute('src')) {
    // the web-ready video exists once "prepare" finishes
    bd.src = `/api/jobs/${live.id}/video.mp4`;
    bd.addEventListener('loadeddata', () => {
      if (!live) return;
      live.videoReady = true;
      $('proc-placeholder').hidden = true;
      seekTo(live.wantFrame);
    }, { once: true });
    bd.addEventListener('seeked', () => drawPeople());
  }
  const p = job.preview;
  const detecting = job.stage === 'detect' && job.status === 'running';
  $('proc-frame').classList.toggle('proc-idle', !detecting);
  if (p && detecting) {
    live.people = p.people;
    live.wantFrame = p;
    $('proc-frame-info').textContent =
      `FRAME ${p.frame.toLocaleString()} / ${p.total.toLocaleString()} · ${p.people.length} ${p.people.length === 1 ? 'PERSON' : 'PEOPLE'}`;
    if (live.videoReady) seekTo(p);
  } else if (!detecting && job.stages[1].state === 'done') {
    $('proc-frame-info').textContent = 'DETECTION COMPLETE';
    live.people = [];
    drawPeople();
  } else if (job.status === 'queued') {
    $('proc-placeholder').textContent = 'Waiting for the previous fight to finish…';
  }
}

function seekTo(p) {
  if (!p || !live || p.frame === live.shownFrame) return;
  live.shownFrame = p.frame;
  live.drawn = p.people;
  $('proc-backdrop').currentTime = p.t + 0.001;   // drawPeople() runs on 'seeked'
}

function clearCanvas() {
  const c = $('proc-canvas');
  c.getContext('2d').clearRect(0, 0, c.width, c.height);
}

function drawPeople() {
  if (!live) return;
  const c = $('proc-canvas'), bd = $('proc-backdrop'), ctx = c.getContext('2d');
  const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
  c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const vw = bd.videoWidth, vh = bd.videoHeight;
  if (!vw) return;
  const s = Math.min(w / vw, h / vh), ox = (w - vw * s) / 2, oy = (h - vh * s) / 2;
  const P = (x, y) => [ox + x * s, oy + y * s];
  // identity is unknown at this stage, so everyone is drawn the same neutral colour
  for (const person of live.drawn || []) {
    const [x1, y1] = P(person.box[0], person.box[1]), [x2, y2] = P(person.box[2], person.box[3]);
    ctx.strokeStyle = 'rgba(255,255,255,0.35)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.setLineDash([]);
    const kp = person.kp, ok = k => kp[k][2] > 0.35;
    ctx.strokeStyle = 'rgba(124,245,255,0.9)';
    ctx.shadowColor = 'rgba(124,245,255,0.8)';
    ctx.shadowBlur = 8;
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.beginPath();
    for (const [a, b] of EDGES) {
      if (!ok(a) || !ok(b)) continue;
      ctx.moveTo(...P(kp[a][0], kp[a][1])); ctx.lineTo(...P(kp[b][0], kp[b][1]));
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#fff';
    for (let k = 5; k < 17; k++) if (ok(k)) { const [x, y] = P(kp[k][0], kp[k][1]); ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2); ctx.fill(); }
  }
}

// ------------------------------------------------------------------ stages
function renderStages(job) {
  const ol = $('stages');
  if (ol.children.length !== job.stages.length) {
    ol.innerHTML = '';
    for (const s of job.stages) {
      const li = document.createElement('li');
      li.className = 'stage-row';
      li.innerHTML = `<span class="st-icon"></span><span class="st-label"></span><span class="st-pct"></span>
                      <div class="bar"><div class="bar-fill"></div></div>`;
      li.querySelector('.st-label').textContent = s.label;
      ol.appendChild(li);
    }
  }
  let overall = 0;
  job.stages.forEach((s, i) => {
    const li = ol.children[i];
    // "select" is the user's turn, not a computation: never show a spinner for it here
    const state = s.key === 'select' && s.state === 'running' ? 'pending' : s.state;
    li.className = `stage-row ${state}`;
    li.querySelector('.st-pct').textContent = state === 'running' ? `${Math.floor(s.progress * 100)}%` : '';
    li.querySelector('.bar').hidden = state !== 'running';
    li.querySelector('.bar-fill').style.width = `${s.progress * 100}%`;
    overall += (WEIGHT[s.key] || 0) * (s.state === 'done' ? 1 : s.progress);
  });
  const pct = job.status === 'queued' ? 0 : Math.min(99, Math.floor(overall * 100));
  $('proc-bar').style.width = `${pct}%`;
  $('proc-pct').textContent = job.status === 'queued' ? 'Queued' : `${pct}%`;
  $('proc-eta').textContent = job.eta != null ? `About ${fmtEta(job.eta)} left in detection` : '';
}

function showError(job, id) {
  const box = $('proc-error');
  box.innerHTML = '';
  box.append(job.error || 'Processing failed.', document.createElement('br'));
  const a = document.createElement('a');
  a.href = '#/'; a.className = 'btn btn-secondary'; a.style.marginTop = '14px'; a.textContent = 'Try another video';
  box.append(a);
  if (job.has_poses) {          // detection is cached: the user can retry from selection
    const b = document.createElement('a');
    b.href = `#/select/${id}`; b.className = 'btn btn-primary'; b.style.margin = '14px 0 0 8px'; b.textContent = 'Choose fighters again';
    box.append(b);
  }
  box.hidden = false;
  $('proc-frame').classList.add('proc-idle');
}

function fmtEta(s) {
  if (s < 60) return `${Math.max(1, Math.round(s))} s`;
  return `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`;
}
