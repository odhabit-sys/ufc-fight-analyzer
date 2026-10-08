#!/usr/bin/env python3
"""Tracking QA: run the identity tracker (no HUD) and save tiled snapshots every N seconds,
showing F1 (red), F2 (blue), the hidden referee slot (green), all detections (grey) and
detections rejected as spectators (dark red). Judge identity by eye, then re-run with a
different --offset to check frames you did not tune on.

    python tools/review_grid.py output/fight_0-end_yolo11m-pose_960.pose.pkl --step 2.5
    python tools/review_grid.py output/...pose.pkl --step 2.5 --offset 1.25   # held-out frames
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fight_analyzer.config import Config  # noqa: E402
from fight_analyzer.extract import load_cache  # noqa: E402
from fight_analyzer.tracking import FighterTracker, build_dets  # noqa: E402

EDGES = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
         (11, 13), (13, 15), (12, 14), (14, 16)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cache")
    ap.add_argument("--pick", help="pick.json (default: the one next to the cache)")
    ap.add_argument("--step", type=float, default=2.5)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--out", default="output/review")
    args = ap.parse_args()

    cache, cfg = load_cache(args.cache), Config()
    fps = cache["fps"]
    pick_path = args.pick or str(Path(args.cache)).split("_yolo")[0] + ".pick.json"
    pick = json.load(open(pick_path)) if Path(pick_path).exists() else None
    start = pick["frame"] if pick else 0
    targets = [int(round(t * fps)) for t in np.arange(args.offset, len(cache["frames"]) / fps, args.step)]
    targets = [f for f in targets if f >= start]
    cap = cv2.VideoCapture(cache["video"])
    cap.set(cv2.CAP_PROP_POS_FRAMES, cache["f0"] + start)
    tr, tiles, waited = FighterTracker(cfg, fps), [], 0
    for fi in range(start, targets[-1] + 1):
        ok, fr = cap.read()
        if not ok:
            break
        fd = cache["frames"][fi]
        dets = build_dets(fr, fd, cfg)
        if not tr.initialized:
            if pick and fi == start:
                tr.init_with(dets[pick["dets"][0]], dets[pick["dets"][1]], dets)
            else:
                tr.try_auto_init(dets, waited)
                waited += 1
        a = tr.update(dets, fd["M"], bool(fd["cut"]) and fi > start) if tr.initialized else [None, None]
        if fi not in targets:
            continue
        v = fr.copy()
        for d in dets:
            b = d.box.astype(int)
            cv2.rectangle(v, tuple(b[:2]), tuple(b[2:]), (160, 160, 160) if d.candidate else (0, 0, 140), 1)
        for i, d in enumerate(a):
            c = (60, 60, 255) if i == 0 else (255, 160, 40)
            if d is None:
                cv2.putText(v, f"F{i + 1} LOST", (10 + 160 * i, 30), 0, 0.8, c, 2)
                continue
            b = d.box.astype(int)
            cv2.rectangle(v, tuple(b[:2]), tuple(b[2:]), c, 2)
            for p, q in EDGES:
                if d.kc[p] > cfg.kp_conf and d.kc[q] > cfg.kp_conf:
                    cv2.line(v, tuple(d.kxy[p].astype(int)), tuple(d.kxy[q].astype(int)), c, 2)
            cv2.putText(v, f"F{i + 1}", (b[0] + 3, b[1] + 24), 0, 0.9, c, 3)
        ref = tr.slots[2]
        if ref.template is not None and ref.lost == 0:
            b = ref.box.astype(int)
            cv2.rectangle(v, tuple(b[:2]), tuple(b[2:]), (0, 220, 0), 2)
            cv2.putText(v, "REF", (b[0] + 3, b[1] + 24), 0, 0.8, (0, 220, 0), 2)
        cv2.putText(v, f"{(cache['f0'] + fi) / fps:.1f}s{' CUT' if fd['cut'] else ''}",
                    (8, v.shape[0] - 10), 0, 0.9, (0, 255, 255), 2)
        tiles.append(cv2.resize(v, (640, 360)))
    for k, s in enumerate(range(0, len(tiles), 12)):
        T = tiles[s:s + 12]
        while len(T) % 3:
            T.append(np.zeros_like(T[0]))
        path = f"{args.out}_{k}.jpg"
        cv2.imwrite(path, np.vstack([np.hstack(T[i:i + 3]) for i in range(0, len(T), 3)]))
        print(path)


if __name__ == "__main__":
    main()
