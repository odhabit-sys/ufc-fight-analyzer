// Full-fight momentum graph that doubles as the scrubber.
//   top lane:    red-corner strike/kick ticks      graph: momentum (red above 50%, blue below)
//   bottom lane: blue-corner strike/kick ticks     bands: high-activity exchanges
//   full-height: knockdowns (amber) / takedowns
// Drag anywhere to scrub; click a marker to jump to that event.
import { fmtTime } from './data.js';

const LANE = 18, PAD = 4;

export class Timeline {
  constructor(root, model, { onSeek }) {
    this.root = root;
    this.canvas = root.querySelector('canvas');
    this.tip = root.querySelector('.tl-tip');
    this.ctx = this.canvas.getContext('2d');
    this.m = model;
    this.onSeek = onSeek;
    this.order = [0, 1];
    this.colors = ['#ff3b4e', '#2fa8ff'];
    this.t = 0;
    this.static = document.createElement('canvas');
    this.bind();
    this.ro = new ResizeObserver(() => this.layout());
    this.ro.observe(root);
  }

  destroy() {
    this.ro.disconnect();
    this.canvas.replaceWith(this.canvas.cloneNode());   // drops this instance's listeners
    this.tip.hidden = true;
  }

  setOrder(order, colors) { this.order = order; this.colors = colors; this.layout(); }

  layout() {
    const dpr = window.devicePixelRatio || 1;
    const w = this.root.clientWidth, h = this.root.clientHeight;
    if (!w || !h) return;
    this.w = w; this.h = h; this.dpr = dpr;
    for (const c of [this.canvas, this.static]) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    this.gTop = LANE + PAD; this.gBot = h - LANE - PAD;
    this.drawStatic();
    this.draw(this.t);
  }

  x(t) { return (t / this.m.duration) * this.w; }
  tAt(x) { return Math.max(0, Math.min(this.m.duration, (x / this.w) * this.m.duration)); }

  // share for the display slot 0 (red corner) at frame f
  share(f) { const m = this.m.momentum(f); return this.order[0] === 0 ? m : 1 - m; }

  drawStatic() {
    const c = this.static.getContext('2d'), { w, h, gTop, gBot } = this, m = this.m;
    c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    const gH = gBot - gTop, yc = gTop + gH / 2;

    // exchange bands
    for (const e of m.events) {
      if (e.kind !== 'exchange') continue;
      const x1 = this.x(e.t), x2 = Math.max(x1 + 2, this.x(e.end));
      c.fillStyle = 'rgba(124,245,255,0.07)';
      c.fillRect(x1, gTop, x2 - x1, gH);
      c.fillStyle = 'rgba(124,245,255,0.45)';
      c.fillRect(x1, gTop, x2 - x1, 1.5);
    }
    // minute grid
    c.fillStyle = 'rgba(255,255,255,0.05)';
    c.font = '10px "JetBrains Mono", monospace';
    for (let t = 30; t < m.duration; t += 30) {
      const x = Math.round(this.x(t)) + 0.5;
      c.fillRect(x, gTop, 1, gH);
      c.fillStyle = 'rgba(255,255,255,0.25)';
      // keep clear of the "FIGHTER 2 AHEAD" label (left) and the axis labels (right)
      if (x > 140 && x < w - 70) c.fillText(fmtTime(t).slice(0, 5), x + 4, gBot - 4);
      c.fillStyle = 'rgba(255,255,255,0.05)';
    }
    // centre line
    c.strokeStyle = 'rgba(255,255,255,0.18)';
    c.setLineDash([3, 4]);
    c.beginPath(); c.moveTo(0, yc); c.lineTo(w, yc); c.stroke();
    c.setLineDash([]);

    // momentum curve, one sample per pixel column. The vertical axis is zoomed to this
    // fight's range (at least 35-65%) and labelled, so small swings are visible but honest.
    const shares = [];
    for (let x = 0; x <= w; x++) shares.push(this.share(m.frameAt(this.tAt(x))));
    const dev = Math.min(0.5, Math.max(0.15, ...shares.map(s => Math.abs(s - 0.5))) * 1.15);
    const yOf = s => yc - ((s - 0.5) / dev) * (gH / 2);
    const ys = shares.map(yOf);
    // axis labels (right edge) + who-is-ahead labels (left edge, in corner colours)
    c.font = '500 10px "JetBrains Mono", monospace';
    c.textAlign = 'right';
    c.fillStyle = 'rgba(255,255,255,0.32)';
    c.fillText(`${Math.round((0.5 + dev) * 100)}%`, w - 6, gTop + 10);
    c.fillText('50%', w - 6, yc - 4);
    c.fillText(`${Math.round((0.5 - dev) * 100)}%`, w - 6, gBot - 4);
    c.textAlign = 'left';
    for (const [side, col] of [[1, this.colors[0]], [-1, this.colors[1]]]) {
      c.save();
      c.beginPath();
      side > 0 ? c.rect(0, gTop, w, yc - gTop) : c.rect(0, yc, w, gBot - yc);
      c.clip();
      c.beginPath(); c.moveTo(0, yc);
      ys.forEach((y, x) => c.lineTo(x, y));
      c.lineTo(w, yc); c.closePath();
      c.fillStyle = col + '66';
      c.fill();
      c.restore();
    }
    c.font = '600 10px Inter, sans-serif';
    c.fillStyle = this.colors[0];
    c.fillText('FIGHTER 1 AHEAD ▲', 8, gTop + 12);
    c.fillStyle = this.colors[1];
    c.fillText('FIGHTER 2 AHEAD ▼', 8, gBot - 5);
    c.strokeStyle = 'rgba(255,255,255,0.9)';
    c.lineWidth = 1.5;
    c.beginPath();
    ys.forEach((y, x) => (x ? c.lineTo(x, y) : c.moveTo(x, y)));
    c.stroke();

    // lead changes: where the momentum line crosses 50% (with a little hysteresis so
    // jitter right at 50/50 doesn't produce a marker every few pixels)
    let lead = 0;
    shares.forEach((sh, x) => {
      const now = sh > 0.51 ? 1 : sh < 0.49 ? -1 : lead;
      if (lead !== 0 && now !== lead) {
        c.fillStyle = now > 0 ? this.colors[0] : this.colors[1];
        c.strokeStyle = '#06080b';
        c.lineWidth = 1.5;
        c.beginPath(); c.moveTo(x, yc - 5); c.lineTo(x + 5, yc); c.lineTo(x, yc + 5); c.lineTo(x - 5, yc); c.closePath();
        c.fill(); c.stroke();
      }
      lead = now;
    });

    // event markers
    this.markers = [];
    for (const e of m.events) {
      const x = this.x(e.t);
      if (e.kind === 'punch' || e.kind === 'kick') {
        const slot = this.order.indexOf(e.fighter - 1);
        const top = slot === 0;
        c.fillStyle = this.colors[slot];
        if (e.kind === 'punch') {
          c.fillRect(x - 0.75, top ? 4 : h - 4 - (e.target ? 14 : 10), 1.5, e.target ? 14 : 10);
        } else {
          const y = top ? 5 : h - 5;
          c.beginPath(); c.moveTo(x - 4, y); c.lineTo(x + 4, y); c.lineTo(x, top ? y + 8 : y - 8); c.fill();
        }
        this.markers.push({ x, y: top ? LANE / 2 : h - LANE / 2, e });
      } else if (e.kind === 'knockdown' || e.kind === 'takedown') {
        const col = e.kind === 'knockdown' ? '#ffc43d' : this.colors[this.order.indexOf(e.fighter - 1)];
        c.fillStyle = col;
        c.fillRect(x - 1, 0, 2, h);
        c.beginPath(); c.moveTo(x - 6, 0); c.lineTo(x + 6, 0); c.lineTo(x, 9); c.fill();
        this.markers.push({ x, y: h / 2, e, big: true });
      } else if (e.kind === 'exchange') {
        this.markers.push({ x: this.x(e.t), y: gTop + 2, e });
      }
    }
  }

  draw(t) {
    this.t = t;
    if (!this.w) return;
    const c = this.ctx;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
    c.drawImage(this.static, 0, 0);
    c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    // played region tint + playhead
    const x = this.x(t);
    c.fillStyle = 'rgba(0,0,0,0.25)';
    c.fillRect(x, 0, this.w - x, this.h);
    c.fillStyle = '#fff';
    c.fillRect(Math.round(x) - 1, 0, 2, this.h);
    c.beginPath(); c.moveTo(x - 5, 0); c.lineTo(x + 5, 0); c.lineTo(x, 6); c.fill();
  }

  markerAt(px, py) {
    let best = null, bd = 7;
    for (const mk of this.markers || []) {
      const d = mk.big ? Math.abs(mk.x - px) : Math.hypot(mk.x - px, (mk.y - py) * 0.4);
      if (d < bd) { bd = d; best = mk; }
    }
    return best;
  }

  bind() {
    const pos = ev => { const r = this.canvas.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
    let dragging = false, moved = false, downX = 0;
    this.canvas.addEventListener('pointerdown', ev => {
      dragging = true; moved = false; downX = ev.clientX;
      this.canvas.setPointerCapture(ev.pointerId);
      const [x] = pos(ev);
      this.onSeek(this.tAt(x), { scrub: true });
    });
    this.canvas.addEventListener('pointermove', ev => {
      const [x, y] = pos(ev);
      if (dragging) {
        if (Math.abs(ev.clientX - downX) > 3) moved = true;
        this.onSeek(this.tAt(x), { scrub: true });
        this.showTip(x, fmtTime(this.tAt(x)));
        return;
      }
      const mk = this.markerAt(x, y);
      this.showTip(mk ? mk.x : x, mk ? this.describe(mk.e) : fmtTime(this.tAt(x)));
      this.canvas.style.cursor = mk ? 'pointer' : 'crosshair';
    });
    const end = ev => {
      if (!dragging) return;
      dragging = false;
      const [x, y] = pos(ev);
      const mk = !moved && this.markerAt(x, y);
      if (mk) this.onSeek(Math.max(0, mk.e.t - 0.5), { event: mk.e });
    };
    this.canvas.addEventListener('pointerup', end);
    this.canvas.addEventListener('pointercancel', end);
    this.canvas.addEventListener('pointerleave', () => { if (!dragging) this.tip.hidden = true; });
  }

  describe(e) {
    const who = e.fighter ? ` · F${this.order.indexOf(e.fighter - 1) + 1}` : '';
    const end = e.kind === 'exchange' ? `–${fmtTime(e.end)} · ${e.count} strikes` : '';
    return `${fmtTime(e.t)}${end}${who} · ${e.label}${e.target ? ` · ${e.target}?` : ''}`;
  }

  showTip(x, text) {
    this.tip.hidden = false;
    this.tip.textContent = text;
    const half = this.tip.offsetWidth / 2;
    this.tip.style.left = `${Math.max(half, Math.min(this.w - half, x))}px`;
  }
}
