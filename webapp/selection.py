"""Fighter selection: choose a few good frames to pick the fighters on, using ONLY the
pose cache from the detection stage (no new model inference).

A good frame shows at least two full-body people inside the cage, clearly separated.
We take the best such frame from each of N equal slices of the fight, so if the first
one is a bad angle the user can step to another part of the fight.
"""
import json

import cv2
import numpy as np

from fight_analyzer.pipeline import read_frame
from fight_analyzer.tracking import box_iou, build_dets

N_SLICES = 6


def _frame_score(fd, W, H, cfg):
    """Cheap pre-filter on cached boxes/keypoints (no image needed)."""
    people = []
    for box, kc in zip(fd["boxes"], fd["kc"]):
        x1, y1, x2, y2 = box
        legs = (kc[13:17] > cfg.kp_conf).sum()
        if legs >= 2 and (x2 - x1) * (y2 - y1) > 0.02 * W * H and y2 > 0.55 * H:
            people.append(box)
    if len(people) < 2:
        return 0.0
    people.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    a, b = people[0], people[1]
    if box_iou(a, b) > 0.1:        # overlapping / clinching: hard to click
        return 0.0
    area = lambda bb: (bb[2] - bb[0]) * (bb[3] - bb[1])
    # prefer two large, similarly sized people, both fully inside the frame
    inside = all(bb[0] > 2 and bb[2] < W - 2 for bb in (a, b))
    return float(np.sqrt(area(a) * area(b)) / (W * H)) * (1.0 if inside else 0.5)


def build_selection(cache, cfg, out_dir):
    """Writes select_<frame>.jpg files + selection.json; returns the selection dict."""
    path = out_dir / "selection.json"
    if path.exists():
        return json.loads(path.read_text())
    W, H, frames = cache["width"], cache["height"], cache["frames"]
    n = len(frames)
    scores = np.array([_frame_score(fd, W, H, cfg) for fd in frames])
    chosen = []
    for k in range(N_SLICES):
        lo, hi = k * n // N_SLICES, (k + 1) * n // N_SLICES
        if hi > lo and scores[lo:hi].max() > 0:
            chosen.append(lo + int(np.argmax(scores[lo:hi])))
    if not chosen:                     # nothing scored: fall back to evenly spaced frames
        chosen = [int(x) for x in np.linspace(0, n - 1, N_SLICES)]

    out = []
    for fi in chosen:
        img = read_frame(cache["video"], cache["f0"] + fi)
        cv2.imwrite(str(out_dir / f"select_{fi}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        dets = build_dets(img, frames[fi], cfg)   # same filtered list the pipeline indexes
        out.append(dict(frame=fi, t=round(fi / cache["fps"], 2), score=round(float(scores[fi]), 4), people=[
            dict(i=j, box=[round(float(v), 1) for v in d.box], likely_fighter=bool(d.candidate))
            for j, d in enumerate(dets)]))
    best = max(range(len(out)), key=lambda k: out[k]["score"])
    sel = dict(width=W, height=H, default=best, frames=out)
    path.write_text(json.dumps(sel))
    return sel
