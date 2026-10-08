"""Web viewer export: analysis.json (stats, momentum, events) + pose.bin (skeletons).

The viewer looks everything up by FRAME INDEX (frame = round(video.currentTime * fps)),
so every per-frame quantity is stored column-wise, one array entry per frame:

analysis.json
  version, video{fps, frames, duration, width, height}
  fighters[2]{name, color}
  states[]                    names for the state codes used in series
  scale{key: divisor}         series are stored as ints; real value = int / scale[key]
  series
    momentum[n]               F1 momentum share * 1000 (F2 = 1000 - value)
    range[n]                  distance between fighters in body lengths * 10, -1 = unknown
    fighters[2]
      visible[n]              0 not visible, 1 measured, 2 held (briefly lost, last pose kept)
      state[n]                index into states[]
      pressure/activity/speed/approach[n]
      punches/kicks/onTarget/knockdowns/takedowns[n]   RUNNING totals at that frame
      advance/retreat/engaged/control[n]               RUNNING seconds * 10
  events[]                    {t, frame, kind, fighter, label, target, x, y}, plus derived
                              "exchange" events {t, end, frame, endFrame, count}
  pose{url, scale, stride, fields}  layout of pose.bin
  summary                     final totals

pose.bin  little-endian int16, frames x 2 fighters x 56:
  [0]      flag (0 none, 1 measured, 2 held)
  [1..4]   box x1,y1,x2,y2          (pixels * pose.scale)
  [5..55]  17 keypoints * (x, y, conf*100)   (x,y in pixels * pose.scale)
"""
import json

import numpy as np

from .pipeline import analyze

STATES = ["SEARCHING", "HOLDING", "ADVANCING", "RETREATING", "DOWN", "CONTROL"]
POSE_SCALE = 4          # quarter-pixel precision keeps smoothed skeletons from jittering
POSE_STRIDE = 56
COLORS = ["#ff3b4e", "#2fa8ff"]


def _exchanges(strikes, fps, window=3.0, min_strikes=5):
    """High-activity exchanges: >= min_strikes attempts within `window` s, both fighters
    involved. Derived purely from detected strike attempts."""
    out, i, n = [], 0, len(strikes)
    while i < n:
        j = i
        while j + 1 < n and strikes[j + 1]["t"] - strikes[i]["t"] <= window:
            j += 1
        group = strikes[i:j + 1]
        if len(group) >= min_strikes and len({e["fighter"] for e in group}) == 2:
            # extend while strikes keep coming within 1.5 s of the previous one
            while j + 1 < n and strikes[j + 1]["t"] - strikes[j]["t"] <= 1.5:
                j += 1
            group = strikes[i:j + 1]
            out.append(dict(kind="exchange", fighter=None, label="HIGH ACTIVITY",
                            t=group[0]["t"], end=group[-1]["t"], frame=group[0]["frame"],
                            endFrame=group[-1]["frame"], count=len(group)))
            i = j + 1
        else:
            i += 1
    return out


def export(cache, cfg, out_dir, names=("FIGHTER 1", "FIGHTER 2"), pick=None, progress=None):
    fps, f0 = cache["fps"], cache["f0"]
    n = len(cache["frames"])
    S = dict(momentum=1000, range=10, pressure=100, activity=100, speed=100, approach=100,
             advance=10, retreat=10, engaged=10, control=10)
    momentum = np.full(n, 500, np.int16)
    rng = np.full(n, -1, np.int16)
    per = [{k: np.zeros(n, np.int32) for k in
            ("visible", "state", "pressure", "activity", "speed", "approach", "punches", "kicks",
             "onTarget", "knockdowns", "takedowns", "advance", "retreat", "engaged", "control")}
           for _ in range(2)]
    pose = np.zeros((n, 2, POSE_STRIDE), np.int16)
    events, sig = [], None

    for r in analyze(cache, cfg, pick):
        fi, sig = r.fi, r.sig
        momentum[fi] = round(r.share * 1000)
        if sig.dist_bl is not None:
            rng[fi] = min(round(sig.dist_bl * 10), 32000)
        for i, f in enumerate(sig.f):
            a = per[i]
            a["visible"][fi] = 0 if r.vis[i] is None else (2 if r.held[i] else 1)
            a["state"][fi] = STATES.index(f.state) if f.state in STATES else 0
            a["pressure"][fi] = round(f.pressure * 100)
            a["activity"][fi] = round(f.activity * 100)
            a["speed"][fi] = round(float(np.linalg.norm(f.vel)) * 100)
            a["approach"][fi] = round(f.approach * 100)
            a["punches"][fi] = f.counts["punches"]
            a["kicks"][fi] = f.counts["kicks"]
            a["onTarget"][fi] = f.counts["on_target"]
            a["knockdowns"][fi] = f.counts["knockdowns"]
            a["takedowns"][fi] = f.counts["takedowns"]
            a["advance"][fi] = round(f.time["adv"] * 10)
            a["retreat"][fi] = round(f.time["ret"] * 10)
            a["engaged"][fi] = round(f.time["engaged"] * 10)
            a["control"][fi] = round(f.time["ctrl"] * 10)
            v = r.vis[i]
            if v is not None:
                kp, kc, box = v
                row = pose[fi, i]
                row[0] = 2 if r.held[i] else 1
                row[1:5] = np.round(np.asarray(box) * POSE_SCALE)
                k = np.empty((17, 3))
                k[:, :2] = np.round(kp * POSE_SCALE)
                k[:, 2] = np.round(kc * 100)
                row[5:] = k.reshape(-1)
        for e in r.events:
            events.append(dict(t=round(e.t, 3), frame=f0 + e.frame, kind=e.kind, fighter=e.fighter + 1,
                               label=e.label, target=e.target,
                               victim=None if e.victim is None else e.victim + 1,
                               x=round(float(e.pos[0]), 1), y=round(float(e.pos[1]), 1)))
        if progress and (r.k % 15 == 0):
            progress(r.k + 1, n)

    # scrambles carry no points and were noisy on real footage; keep them out of the viewer
    events = [e for e in events if not (e["kind"] == "drop" and e["victim"] is None)]
    strikes = [e for e in events if e["kind"] in ("punch", "kick")]
    events = sorted(events + _exchanges(strikes, fps), key=lambda e: e["t"])

    pose.astype("<i2").tofile(out_dir / "pose.bin")
    summary = {f"fighter{i + 1}": dict(**f.counts, **{k: round(v, 1) for k, v in f.time.items()})
               for i, f in enumerate(sig.f)} if sig else {}
    summary["final_momentum"] = int(momentum[-1])
    data = dict(
        version=1,
        video=dict(fps=fps, frames=n, duration=round(n / fps, 3),
                   width=cache["width"], height=cache["height"]),
        fighters=[dict(name=names[i], color=COLORS[i]) for i in (0, 1)],
        states=STATES,
        scale=S,
        series=dict(momentum=momentum.tolist(), range=rng.tolist(),
                    fighters=[{k: v.tolist() for k, v in a.items()} for a in per]),
        events=events,
        pose=dict(url="pose.bin", scale=POSE_SCALE, stride=POSE_STRIDE,
                  fields="flag, box[4], 17 x (x, y, conf*100)"),
        summary=summary,
    )
    with open(out_dir / "analysis.json", "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    return data
