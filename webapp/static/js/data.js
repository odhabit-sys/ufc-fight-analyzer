// Loads analysis.json + pose.bin and exposes frame-indexed accessors.
// Layout documented in fight_analyzer/webexport.py.

export const COLORS = ['#ff3b4e', '#2fa8ff'];

export function fmtTime(t) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}

export function fmtClock(sec) {
  sec = Math.round(sec);
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

export async function loadAnalysis(id) {
  const [a, buf] = await Promise.all([
    fetch(`/api/jobs/${id}/analysis.json`).then(r => { if (!r.ok) throw new Error('analysis.json ' + r.status); return r.json(); }),
    fetch(`/api/jobs/${id}/pose.bin`).then(r => { if (!r.ok) throw new Error('pose.bin ' + r.status); return r.arrayBuffer(); }),
  ]);
  return new Model(a, new Int16Array(buf));
}

export class Model {
  constructor(a, pose) {
    this.a = a;
    this.pose = pose;
    this.fps = a.video.fps;
    this.n = a.series.momentum.length;
    this.duration = a.video.duration;
    this.stride = a.pose.stride;
    this.ps = a.pose.scale;
    this.events = a.events;
  }
  // Frame i is displayed from i/fps until (i+1)/fps, so the frame on screen at time t is
  // floor(t * fps). The small epsilon absorbs float error when t is a frame's exact
  // timestamp (requestVideoFrameCallback's mediaTime). Plain rounding was one frame
  // ahead after seeks that land between two frames.
  frameAt(t) { return Math.max(0, Math.min(this.n - 1, Math.floor(t * this.fps + 1e-3))); }
  // F1 (raw fighter 0) momentum share, 0..1
  momentum(f) { return this.a.series.momentum[f] / 1000; }
  range(f) { const v = this.a.series.range[f]; return v < 0 ? null : v / this.a.scale.range; }
  stat(i, key, f) {
    const v = this.a.series.fighters[i][key][f];
    const s = this.a.scale[key];
    return s ? v / s : v;
  }
  state(i, f) { return this.a.states[this.a.series.fighters[i].state[f]]; }
  // -> null or {held, box:[x1,y1,x2,y2], kp: Float32Array(17*3) as x,y,conf(0..1)} in video pixels
  skeleton(f, i) {
    const o = (f * 2 + i) * this.stride, p = this.pose;
    if (o + this.stride > p.length || !p[o]) return null;
    const s = this.ps, kp = new Float32Array(51);
    for (let k = 0; k < 17; k++) {
      kp[k * 3] = p[o + 5 + k * 3] / s;
      kp[k * 3 + 1] = p[o + 6 + k * 3] / s;
      kp[k * 3 + 2] = p[o + 7 + k * 3] / 100;
    }
    return { held: p[o] === 2, box: [p[o + 1] / s, p[o + 2] / s, p[o + 3] / s, p[o + 4] / s], kp };
  }
}
