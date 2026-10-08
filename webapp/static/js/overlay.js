// Draws skeletons, labels, range line and strike effects on a canvas over the <video>.
// Everything is drawn from data for the frame the video is showing, so it is exact
// while playing, paused, or scrubbing.

const EDGES = [[5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16]];
const KP_CONF = 0.35;
const FX_SECONDS = 0.7;

export class Overlay {
  constructor(canvas, model) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.m = model;
    this.opts = { skeleton: true, fx: true, range: true };
    // index events by frame for the strike effects
    this.fxEvents = model.events.filter(e => e.kind === 'punch' || e.kind === 'kick');
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (this.canvas.width !== Math.round(w * dpr) || this.canvas.height !== Math.round(h * dpr)) {
      this.canvas.width = Math.round(w * dpr);
      this.canvas.height = Math.round(h * dpr);
    }
    this.dpr = dpr;
    // object-fit: contain mapping from video pixels to canvas CSS pixels
    const vw = this.m.a.video.width, vh = this.m.a.video.height;
    const s = Math.min(w / vw, h / vh);
    this.map = { s, ox: (w - vw * s) / 2, oy: (h - vh * s) / 2 };
  }

  P(x, y) { const { s, ox, oy } = this.map; return [ox + x * s, oy + y * s]; }

  draw(f, order, colors, labels) {
    const ctx = this.ctx;
    this.resize();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    const sk = [this.m.skeleton(f, 0), this.m.skeleton(f, 1)];
    if (this.opts.range) this.drawRange(f, sk);
    if (this.opts.skeleton) {
      order.forEach((raw, slot) => { if (sk[raw]) this.drawSkeleton(sk[raw], colors[slot], labels[slot]); });
    }
    if (this.opts.fx) this.drawFx(f, order, colors);
  }

  torso(kp) {
    const ok = k => kp[k * 3 + 2] > KP_CONF;
    if (ok(5) && ok(6) && ok(11) && ok(12)) {
      const sx = (kp[15] + kp[18]) / 2, sy = (kp[16] + kp[19]) / 2;
      const hx = (kp[33] + kp[36]) / 2, hy = (kp[34] + kp[37]) / 2;
      return Math.hypot(sx - hx, sy - hy);
    }
    return null;
  }

  drawSkeleton(sk, color, label) {
    const ctx = this.ctx, kp = sk.kp, s = this.map.s;
    const ok = k => kp[k * 3 + 2] > KP_CONF;
    const pt = k => this.P(kp[k * 3], kp[k * 3 + 1]);
    const S = (this.torso(kp) || (sk.box[3] - sk.box[1]) * 0.3) * s;  // body size on screen
    const th = Math.max(2, Math.min(6, S / 24));
    const segs = EDGES.filter(([a, b]) => ok(a) && ok(b)).map(([a, b]) => [pt(a), pt(b)]);
    if (ok(0) && ok(5) && ok(6)) {
      const [x5, y5] = pt(5), [x6, y6] = pt(6);
      segs.push([pt(0), [(x5 + x6) / 2, (y5 + y6) / 2]]);
    }
    ctx.save();
    ctx.globalAlpha = sk.held ? 0.45 : 1;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    // glow + colour pass
    ctx.shadowColor = color;
    ctx.shadowBlur = 12;
    ctx.strokeStyle = color;
    ctx.lineWidth = th;
    ctx.beginPath();
    for (const [[x1, y1], [x2, y2]] of segs) { ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); }
    ctx.stroke();
    ctx.shadowBlur = 0;
    // bright core
    ctx.strokeStyle = 'rgba(255,255,255,0.8)';
    ctx.lineWidth = Math.max(1, th * 0.33);
    ctx.stroke();
    // joints
    for (let k = 5; k < 17; k++) {
      if (!ok(k)) continue;
      const [x, y] = pt(k);
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(x, y, th + 1.5, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#fff';
      ctx.beginPath(); ctx.arc(x, y, Math.max(1, th * 0.45), 0, Math.PI * 2); ctx.fill();
    }
    // head ring
    let hx = 0, hy = 0, hn = 0;
    for (let k = 0; k < 5; k++) if (ok(k)) { const [x, y] = pt(k); hx += x; hy += y; hn++; }
    if (hn) {
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(1.5, th * 0.5);
      ctx.beginPath(); ctx.arc(hx / hn, hy / hn, Math.max(8, S * 0.42), 0, Math.PI * 2); ctx.stroke();
    }
    // label tag above the head (or box)
    const [bx, by] = this.P(sk.box[0], sk.box[1]);
    const tx = hn ? hx / hn : bx, ty = Math.max(14, (hn ? hy / hn - Math.max(8, S * 0.42) - 10 : by - 6));
    ctx.font = '600 13px "Barlow Condensed", sans-serif';
    const w = ctx.measureText(label).width + 12;
    ctx.fillStyle = color;
    ctx.fillRect(tx - w / 2, ty - 15, w, 17);
    ctx.fillStyle = '#07090c';
    ctx.textAlign = 'center';
    ctx.fillText(label, tx, ty - 2);
    ctx.restore();
  }

  drawRange(f, sk) {
    const r = this.m.range(f);
    if (r == null || !sk[0] || !sk[1]) return;
    const hip = s => {
      const kp = s.kp;
      if (kp[35] > KP_CONF && kp[38] > KP_CONF) return this.P((kp[33] + kp[36]) / 2, (kp[34] + kp[37]) / 2);
      return this.P((s.box[0] + s.box[2]) / 2, s.box[1] + (s.box[3] - s.box[1]) * 0.55);
    };
    const [x1, y1] = hip(sk[0]), [x2, y2] = hip(sk[1]);
    const ctx = this.ctx;
    ctx.save();
    ctx.strokeStyle = 'rgba(124,245,255,0.7)';
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 6]);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = '500 11px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(124,245,255,0.95)';
    ctx.shadowColor = '#000'; ctx.shadowBlur = 4;
    ctx.fillText(`${r.toFixed(1)} BL`, (x1 + x2) / 2, (y1 + y2) / 2 - 8);
    ctx.restore();
  }

  drawFx(f, order, colors) {
    const ctx = this.ctx, fps = this.m.fps;
    const lo = f - FX_SECONDS * fps;
    for (const e of this.fxEvents) {
      if (e.frame > f) break;            // events are sorted by time
      if (e.frame < lo) continue;
      const age = (f - e.frame) / fps, k = 1 - age / FX_SECONDS;
      const [x, y] = this.P(e.x, e.y);
      const slot = order.indexOf(e.fighter - 1);
      const col = e.target ? '#ffc43d' : colors[slot];
      ctx.save();
      ctx.globalAlpha = k;
      ctx.strokeStyle = col;
      ctx.lineWidth = 1 + 3 * k;
      ctx.beginPath(); ctx.arc(x, y, 10 + age * (e.target ? 110 : 70), 0, Math.PI * 2); ctx.stroke();
      ctx.font = '700 18px "Barlow Condensed", sans-serif';
      ctx.textAlign = 'center';
      ctx.fillStyle = e.target ? '#ffc43d' : '#fff';
      ctx.shadowColor = '#000'; ctx.shadowBlur = 6;
      const txt = (e.kind === 'kick' ? 'KICK' : 'STRIKE') + (e.target ? ` · ${e.target}?` : '');
      ctx.fillText(txt, x, y - 22 - age * 50);
      ctx.restore();
    }
  }
}
