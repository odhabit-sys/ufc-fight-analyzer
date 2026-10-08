// Analysis viewer. Everything on screen is a pure function of the frame the <video> is
// showing: frame = round(mediaTime * fps), read from requestVideoFrameCallback.
import { COLORS, fmtClock, fmtTime, loadAnalysis } from './data.js';
import { Overlay } from './overlay.js';
import { Timeline } from './timeline.js';

const $ = id => document.getElementById(id);
const STATE_COLOR = { ADVANCING: 'var(--green)', RETREATING: 'var(--amber)', DOWN: 'var(--red)',
  CONTROL: 'var(--cyan)', HOLDING: 'var(--text)', SEARCHING: 'var(--dimmer)' };
const STATE_TEXT = { SEARCHING: 'NOT VISIBLE' };
const ICONS = {
  punch: '<path d="M8 1.5v3.5M8 11v3.5M1.5 8H5M11 8h3.5M3.4 3.4l2.3 2.3M10.3 10.3l2.3 2.3M12.6 3.4l-2.3 2.3M5.7 10.3l-2.3 2.3"/>',
  kick: '<path d="M3 2.5l3 5.5 7.5 1.5"/><circle cx="13" cy="9" r="1.2"/>',
  knockdown: '<path d="M8 2v9M4 7.5L8 11.5 12 7.5M3 14h10"/>',
  takedown: '<path d="M3 4c4 0 7 2 7 6.5M7.5 8.5L10 11l2.5-2.5M3 14h10"/>',
  exchange: '<path d="M3 3l10 10M13 3L3 13M3 9.5L6.5 13M13 9.5L9.5 13"/>',
  drop: '<path d="M4 6l4 4 4-4"/>',
};
const FILTERS = { all: () => true, strike: e => e.kind === 'punch', kick: e => e.kind === 'kick',
  big: e => ['knockdown', 'takedown', 'drop'].includes(e.kind), exchange: e => e.kind === 'exchange' };

let current = null;   // active viewer (so the router can tear it down)
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const cap = s => s.charAt(0) + s.slice(1).toLowerCase();

export function closeViewer() {
  if (current) current.destroy();
  current = null;
}

export async function openViewer(id, setFile) {
  closeViewer();
  const v = new Viewer(id);
  current = v;
  await v.init(setFile);
}

class Viewer {
  constructor(id) {
    this.id = id;
    this.video = $('video');
    this.stage = $('stage');
    this.lastF = -1;
    this.filter = 'all';
    this.cleanups = [];
    const saved = JSON.parse(localStorage.getItem(`fa:${id}`) || '{}');
    this.swapped = !!saved.swapped;
    this.names = saved.names || null;
  }

  on(el, ev, fn, opts) { el.addEventListener(ev, fn, opts); this.cleanups.push(() => el.removeEventListener(ev, fn, opts)); }
  save() { localStorage.setItem(`fa:${this.id}`, JSON.stringify({ swapped: this.swapped, names: this.names })); }
  get order() { return this.swapped ? [1, 0] : [0, 1]; }
  // "Fighter 1", or "Fighter 1 · NAME" once the user has named them
  who(raw) {
    const slot = this.order.indexOf(raw), name = this.names[raw];
    return /^FIGHTER [12]$/.test(name) ? `Fighter ${slot + 1}` : `Fighter ${slot + 1} · ${name}`;
  }

  async init(setFile) {
    const [model, job] = await Promise.all([
      loadAnalysis(this.id),
      fetch(`/api/jobs/${this.id}`).then(r => r.json()),
    ]);
    if (current !== this) return;
    this.m = model;
    setFile(job.name);
    this.names = this.names || model.a.fighters.map(f => f.name);

    this.video.src = `/api/jobs/${this.id}/video.mp4`;
    this.overlay = new Overlay($('overlay'), model);
    this.timeline = new Timeline($('timeline'), model, { onSeek: (t, o) => this.seek(t, o) });
    this.buildStats();
    this.buildEvents();
    this.bindControls();
    this.applyOrder();
    $('t-dur').textContent = fmtTime(model.duration);
    this.stage.classList.add('paused');
    $('view-viewer').classList.add('paused');
    this.startSync();
    this.render(0, true);
  }

  destroy() {
    this.dead = true;
    this.video.pause();
    this.video.removeAttribute('src');
    this.video.load();
    this.cleanups.forEach(fn => fn());
    this.timeline?.destroy();
    $('banner').hidden = true;
    this.stage.classList.remove('moment');
  }

  // ---------------------------------------------------------------- sync
  startSync() {
    const v = this.video;
    if ('requestVideoFrameCallback' in HTMLVideoElement.prototype) {
      const cb = (_, meta) => { if (this.dead) return; this.render(meta.mediaTime); v.requestVideoFrameCallback(cb); };
      v.requestVideoFrameCallback(cb);
    } else {
      const loop = () => { if (this.dead) return; this.render(v.currentTime); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }
    // a seek while paused may not present a new frame in every browser; render anyway
    this.on(v, 'seeked', () => this.render(v.currentTime, true));
    this.on(v, 'loadeddata', () => this.render(v.currentTime, true));
    this.on(v, 'play', () => this.setPaused(false));
    // throttled/background tabs may skip the last frame callbacks: render the exact pause frame
    this.on(v, 'pause', () => { this.setPaused(true); this.render(v.currentTime, true); });
    this.on(v, 'ended', () => this.setPaused(true));
    this.on(window, 'resize', () => this.render(v.currentTime, true));
  }

  seek(t, opts = {}) {
    t = Math.max(0, Math.min(this.m.duration, t));
    this.video.currentTime = t;
    this.timeline.draw(t);            // instant playhead feedback while dragging
    this.render(t, true);
  }

  setPaused(p) {
    this.stage.classList.toggle('paused', p);
    $('view-viewer').classList.toggle('paused', p);
  }

  render(t, force = false) {
    const m = this.m;
    const f = m.frameAt(t);
    this.timeline.draw(t);
    $('hud-time').textContent = `${fmtTime(t)}  ·  F ${String(f).padStart(5, '0')}`;
    $('t-cur').textContent = fmtTime(t);
    const order = this.order;
    // don't draw skeletons over a black screen before the first video frame has decoded
    if (this.video.readyState >= 2) this.overlay.draw(f, order, COLORS, ['F1', 'F2']);
    if (f === this.lastF && !force) return;
    this.lastF = f;

    // momentum header (slot 0 = red corner)
    const s0 = order[0] === 0 ? m.momentum(f) : 1 - m.momentum(f);
    const p0 = Math.round(s0 * 100);
    $('mom-0').textContent = `${p0}%`;
    $('mom-1').textContent = `${100 - p0}%`;
    $('mom-fill').style.width = `${s0 * 100}%`;

    const r = m.range(f);
    $('hud-range').textContent = r == null ? '' : `RANGE ${r.toFixed(1)} BL`;
    order.forEach((raw, slot) => this.updateStats(slot, raw, f));
    this.updateBanner(f);
    this.updateEvents(f);
  }

  // ---------------------------------------------------------------- stats
  buildStats() {
    for (const slot of [0, 1]) {
      const el = $(`stats-${slot}`);
      el.innerHTML = `
        <div class="st-top"><div class="st-head" data-k="head"></div><div class="st-state" data-k="state"></div></div>
        <div class="st-pair">
          <div><div class="st-k">Strikes</div><div class="st-big" data-k="punches"></div></div>
          <div><div class="st-k">Kicks</div><div class="st-big" data-k="kicks"></div></div>
        </div>
        <div class="st-meter"><div class="st-row"><span class="st-k">Activity</span><span class="st-v" data-k="activity"></span></div>
             <div class="st-bar"><i data-k="activityBar"></i></div></div>
        <div class="st-meter"><div class="st-row"><span class="st-k">Pressure</span><span class="st-v" data-k="pressure"></span></div>
             <div class="st-bar"><i data-k="pressureBar"></i></div></div>
        <div class="st-meter"><div class="st-row"><span class="st-k">Advancing vs retreating</span></div>
             <div class="st-split"><i class="adv" data-k="advBar"></i><i class="ret" data-k="retBar"></i></div>
             <div class="st-split-lbl"><span class="a" data-k="adv"></span><span class="r" data-k="ret"></span></div></div>
        <div class="st-list">
          <div class="st-row"><span class="st-k">Control time</span><span class="st-v" data-k="control"></span></div>
          <div class="st-row"><span class="st-k" title="Fist or foot overlapped the opponent in 2D; contact not confirmed">On target?</span><span class="st-v" data-k="onTarget"></span></div>
          <div class="st-row"><span class="st-k" title="Possible knockdowns / takedowns">KD / TD</span><span class="st-v" data-k="big"></span></div>
        </div>`;
      el.q = k => el.querySelector(`[data-k="${k}"]`);
      el.prev = {};
    }
  }

  updateStats(slot, raw, f) {
    const m = this.m, el = $(`stats-${slot}`), q = el.q;
    el.style.setProperty('--c', COLORS[slot]);
    q('head').textContent = `Fighter ${slot + 1}`;
    const st = m.state(raw, f);
    const se = q('state');
    se.textContent = STATE_TEXT[st] || st;
    se.style.setProperty('--sc', STATE_COLOR[st] || 'var(--text)');
    for (const k of ['punches', 'kicks']) {
      const v = m.stat(raw, k, f), node = q(k);
      // brief colour flash when a counter goes up during playback
      if (el.prev[k] != null && v > el.prev[k] && f - (el.prevF ?? f) <= 2) {
        node.classList.add('bump');
        clearTimeout(node.t);
        node.t = setTimeout(() => node.classList.remove('bump'), 450);
      }
      el.prev[k] = v;
      node.textContent = v;
    }
    el.prevF = f;
    const act = m.stat(raw, 'activity', f), pr = m.stat(raw, 'pressure', f);
    q('activity').textContent = act.toFixed(2);
    q('activityBar').style.width = `${Math.min(100, act / 4 * 100)}%`;
    q('pressure').textContent = pr.toFixed(2);
    q('pressureBar').style.width = `${Math.min(100, pr / 1.2 * 100)}%`;
    const eng = m.stat(raw, 'engaged', f);
    const adv = eng > 0 ? m.stat(raw, 'advance', f) / eng : 0, ret = eng > 0 ? m.stat(raw, 'retreat', f) / eng : 0;
    q('advBar').style.width = `${adv * 100}%`;
    q('retBar').style.width = `${ret * 100}%`;
    q('adv').textContent = `ADV ${Math.round(adv * 100)}%`;
    q('ret').textContent = `RET ${Math.round(ret * 100)}%`;
    q('control').textContent = fmtClock(m.stat(raw, 'control', f));
    q('onTarget').textContent = m.stat(raw, 'onTarget', f);
    q('big').textContent = `${m.stat(raw, 'knockdowns', f)} / ${m.stat(raw, 'takedowns', f)}`;
  }

  updateBanner(f) {
    const m = this.m, win = 2.5 * m.fps;
    let hit = null;
    for (const e of m.events) {
      if (e.frame > f) break;
      if ((e.kind === 'knockdown' || e.kind === 'takedown') && f - e.frame < win) hit = e;
    }
    const b = $('banner');
    this.stage.classList.toggle('moment', !!hit);
    if (!hit) { b.hidden = true; return; }
    const slotOf = raw => this.order.indexOf(raw - 1);
    const color = hit.kind === 'knockdown' ? 'var(--amber)' : COLORS[slotOf(hit.fighter)];
    b.hidden = false;
    b.style.setProperty('--bc', color);
    this.stage.style.setProperty('--bc', color);
    b.querySelector('.banner-title').textContent = hit.label;
    const who = raw => this.who(raw - 1);
    b.querySelector('.banner-sub').textContent = hit.kind === 'knockdown' ? `${who(hit.victim)} down` : `${who(hit.fighter)} on top`;
  }

  // ---------------------------------------------------------------- events
  buildEvents() {
    const list = $('events');
    list.innerHTML = '';
    this.evRows = this.m.events.map((e, idx) => {
      const li = document.createElement('li');
      li.className = 'ev' + (e.kind === 'knockdown' ? ' kd' : e.kind === 'exchange' ? ' ex' : '');
      li.dataset.i = idx;
      list.appendChild(li);
      return { e, li };
    });
    this.on(list, 'click', ev => {
      const li = ev.target.closest('.ev');
      if (!li) return;
      const e = this.m.events[+li.dataset.i];
      this.seek(Math.max(0, e.t - 0.5));
    });
    for (const b of $('filters').children) {
      b.querySelector('span').textContent = this.m.events.filter(FILTERS[b.dataset.f]).length;
    }
    this.renderEventRows();
  }

  renderEventRows() {
    const slotOf = raw => this.order.indexOf(raw - 1);
    for (const { e, li } of this.evRows) {
      const slot = e.fighter ? slotOf(e.fighter) : -1;
      const fc = slot >= 0 ? COLORS[slot] : 'var(--cyan)';
      const icon = e.kind === 'knockdown' ? 'var(--amber)' : fc;
      const label = e.kind === 'exchange' ? `High activity · ${e.count} strikes in ${(e.end - e.t).toFixed(1)} s`
        : e.kind === 'punch' ? `Strike · ${cap(e.label)}` : e.kind === 'kick' ? `Kick · ${cap(e.label.replace(' KICK', ''))}` : e.label;
      const who = slot >= 0 ? esc(this.who(e.fighter - 1)) : 'Both fighters';
      li.innerHTML = `
        <span class="ev-t">${fmtTime(e.t)}</span>
        <svg viewBox="0 0 16 16" style="color:${icon}">${ICONS[e.kind] || ICONS.drop}</svg>
        <span class="ev-f" style="--fc:${fc}"><i></i><b>${who}</b></span>
        <span class="ev-l">${label}</span>
        <span class="ev-tgt">${e.target ? e.target + '?' : ''}</span>`;
      li.hidden = !FILTERS[this.filter](e);
    }
    const empty = !this.evRows.some(r => !r.li.hidden);
    let note = $('events').querySelector('.events-empty');
    if (empty && !note) {
      note = document.createElement('li');
      note.className = 'events-empty';
      note.textContent = 'No events of this type were detected in this fight.';
      $('events').appendChild(note);
    }
    if (note) note.hidden = !empty;
    this.curEv = null;
  }

  updateEvents(f) {
    let cur = null;
    for (const row of this.evRows) {
      const past = row.e.frame <= f;
      row.li.classList.toggle('future', !past);
      if (past && !row.li.hidden) cur = row;
    }
    if (cur !== this.curEv) {
      this.curEv?.li.classList.remove('current');
      cur?.li.classList.add('current');
      this.curEv = cur;
      if (cur && !this.video.paused) {
        const list = $('events'), li = cur.li;
        if (li.offsetTop < list.scrollTop || li.offsetTop > list.scrollTop + list.clientHeight - li.offsetHeight) {
          list.scrollTop = li.offsetTop - list.clientHeight / 2;
        }
      }
    }
  }

  // ---------------------------------------------------------------- controls
  applyOrder() {
    for (const slot of [0, 1]) $(`name-${slot}`).textContent = this.names[this.order[slot]];
    this.timeline.setOrder(this.order, COLORS);
    this.renderEventRows();
    this.render(this.video.currentTime || 0, true);
  }

  bindControls() {
    const v = this.video;
    const toggle = () => (v.paused ? v.play() : v.pause());
    this.on($('btn-play'), 'click', toggle);
    this.on(this.stage, 'click', toggle);
    this.on($('speed'), 'change', e => { v.playbackRate = +e.target.value; });
    for (const [id, key] of [['tg-skel', 'skeleton'], ['tg-fx', 'fx'], ['tg-range', 'range']]) {
      const b = $(id);
      b.setAttribute('aria-pressed', String(this.overlay.opts[key]));
      this.on(b, 'click', () => {
        this.overlay.opts[key] = !this.overlay.opts[key];
        b.setAttribute('aria-pressed', String(this.overlay.opts[key]));
        this.render(v.currentTime, true);
      });
    }
    $('btn-change').href = `#/select/${this.id}`;
    this.on($('btn-swap'), 'click', () => { this.swapped = !this.swapped; this.save(); this.applyOrder(); });
    for (const slot of [0, 1]) {
      const el = $(`name-${slot}`);
      this.on(el, 'keydown', e => { if (e.key === 'Enter') { e.preventDefault(); el.blur(); } });
      this.on(el, 'blur', () => {
        const name = el.textContent.trim().toUpperCase() || `FIGHTER ${this.order[slot] + 1}`;
        this.names[this.order[slot]] = name;
        el.textContent = name;
        this.save();
        this.renderEventRows();
        this.updateEvents(this.lastF);
      });
    }
    this.on($('filters'), 'click', e => {
      const b = e.target.closest('[data-f]');
      if (!b) return;
      this.filter = b.dataset.f;
      for (const c of $('filters').children) c.setAttribute('aria-pressed', String(c === b));
      this.renderEventRows();
      this.updateEvents(this.lastF);
    });
    this.on(document, 'keydown', e => {
      if (e.target.isContentEditable || ['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;
      const step = 1 / this.m.fps;
      if (e.code === 'Space') { e.preventDefault(); toggle(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); this.seek(v.currentTime - (e.shiftKey ? 5 : 1)); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); this.seek(v.currentTime + (e.shiftKey ? 5 : 1)); }
      else if (e.key === ',') { v.pause(); this.seek(v.currentTime - step); }
      else if (e.key === '.') { v.pause(); this.seek(v.currentTime + step); }
      else if (e.key === 's') $('tg-skel').click();
    });
  }
}
