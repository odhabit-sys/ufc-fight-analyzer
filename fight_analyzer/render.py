"""MP4 export: the shared analysis loop (pipeline.py) -> burned-in HUD -> H.264 with audio."""
import csv
import json
import subprocess
import time

import cv2
import imageio_ffmpeg
import numpy as np

from .hud import HUD
from .pipeline import analyze
from .tracking import build_dets


def open_writer(out_path, W, H, fps, src_video, start_s, dur_s):
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps:.6f}", "-i", "-",
           "-ss", f"{start_s:.3f}", "-t", f"{dur_s:.3f}", "-i", str(src_video),
           "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def render(cache, out_path, cfg, names, layout="frame", pick=None, swap=False,
           preview=False, data_prefix=None):
    fps, f0 = cache["fps"], cache["f0"]
    start_idx = pick["frame"] if pick else 0
    n = len(cache["frames"]) - start_idx
    hud = HUD(cache["width"], cache["height"], fps, names, layout, cfg.kp_conf)
    start_s = (f0 + start_idx) / fps
    writer = open_writer(out_path, hud.W, hud.H, fps, cache["video"], start_s, n / fps)

    rows, all_events, t_start = [], [], time.time()
    sig = mom = None
    for r in analyze(cache, cfg, pick, swap):
        sig, mom = r.sig, r.mom
        all_events += r.events
        out = hud.render(r.frame, r.t, f0 + r.fi, sig, mom, r.vis, r.events, r.cut)
        writer.stdin.write(out.tobytes())

        row = dict(time=round(r.t, 3), frame=f0 + r.fi, f1_pct=round(r.share * 100, 1), cut=int(r.cut),
                   range_bl=None if sig.dist_bl is None else round(sig.dist_bl, 2))
        for i, f in enumerate(sig.f):
            p = f"f{i + 1}_"
            row.update({p + "visible": int(f.visible), p + "state": f.state,
                        p + "approach": round(f.approach, 3), p + "pressure": round(f.pressure, 3),
                        p + "activity": round(f.activity, 3), p + "posture": f.posture,
                        p + "punches": f.counts["punches"], p + "kicks": f.counts["kicks"],
                        p + "on_target": f.counts["on_target"], p + "control_s": round(f.time["ctrl"], 2)})
        rows.append(row)

        if preview:
            cv2.imshow("Fight Analyzer (q to stop)", cv2.resize(out, (out.shape[1] // 2, out.shape[0] // 2)))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        if r.k % 30 == 0:
            el = time.time() - t_start
            print(f"\r[render] {r.k + 1}/{n}  {(r.k + 1) / el:.1f} fps  F1 {r.share * 100:.0f}%  "
                  f"events {len(all_events)}   ", end="", flush=True)
    print()
    writer.stdin.close()
    writer.wait()
    if preview:
        cv2.destroyAllWindows()

    if data_prefix:
        with open(f"{data_prefix}_signals.csv", "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)
        with open(f"{data_prefix}_events.json", "w") as fh:
            json.dump([dict(t=round(e.t, 3), frame=f0 + e.frame, fighter=e.fighter + 1, kind=e.kind,
                            label=e.label, target=e.target,
                            victim=None if e.victim is None else e.victim + 1,
                            x=round(float(e.pos[0]), 1), y=round(float(e.pos[1]), 1))
                       for e in all_events], fh, indent=1)
    summary = {f"fighter{i + 1}": dict(**f.counts, **{k: round(v, 1) for k, v in f.time.items()})
               for i, f in enumerate(sig.f)}
    summary["final_f1_pct"] = round(mom.display * 100, 1)
    return summary


def interactive_pick(cache, cfg):
    """Show frames with numbered detections; click Fighter 1 then Fighter 2."""
    fps, frames = cache["fps"], cache["frames"]
    cap = cv2.VideoCapture(cache["video"])
    idx, picks, win = 0, [], "Click FIGHTER 1 then FIGHTER 2  |  n/p: +/-1s  r: reset  enter: ok  q: quit"
    clicks = []
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, lambda ev, x, y, *_: clicks.append((x, y)) if ev == cv2.EVENT_LBUTTONDOWN else None)
    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, cache["f0"] + idx)
        ok, frame = cap.read()
        if not ok:
            idx = max(0, idx - int(fps))
            continue
        dets = build_dets(frame, frames[idx], cfg)
        disp_scale = min(1.0, 1400 / frame.shape[1])
        while True:
            for x, y in clicks:
                x, y = x / disp_scale, y / disp_scale
                hits = [j for j, d in enumerate(dets) if d.box[0] <= x <= d.box[2] and d.box[1] <= y <= d.box[3]]
                if hits and len(picks) < 2:
                    j = min(hits, key=lambda j: dets[j].area)
                    if j not in picks:
                        picks.append(j)
            clicks.clear()
            view = frame.copy()
            for j, d in enumerate(dets):
                c = (78, 59, 255) if picks[:1] == [j] else (255, 168, 47) if picks[1:2] == [j] else (180, 180, 180)
                x1, y1, x2, y2 = d.box.astype(int)
                cv2.rectangle(view, (x1, y1), (x2, y2), c, 3)
                tag = "F1" if picks[:1] == [j] else "F2" if picks[1:2] == [j] else str(j)
                cv2.putText(view, tag, (x1 + 4, y1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, c, 2)
            cv2.putText(view, f"t={idx / fps:.1f}s  picked {len(picks)}/2", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
            cv2.imshow(win, cv2.resize(view, None, fx=disp_scale, fy=disp_scale))
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("n"), ord("p")):
                idx = int(np.clip(idx + (fps if key == ord("n") else -fps), 0, len(frames) - 1))
                picks = []
                break
            if key == ord("r"):
                picks = []
            if key in (13, 10) and len(picks) == 2:
                cv2.destroyAllWindows()
                cap.release()
                return dict(frame=idx, dets=picks)
            if key == ord("q"):
                cv2.destroyAllWindows()
                cap.release()
                return None
