"""Stage 2 core: the per-frame analysis loop shared by every output.

    for r in analyze(cache, cfg): ...   # one FrameResult per video frame

identity tracking -> keypoint smoothing -> signals/events -> momentum. The consumers
(render.py = MP4 with burned-in HUD, webexport.py = data for the web viewer) only
decide what to do with each result, so both always show exactly the same analysis.
"""
from dataclasses import dataclass

import cv2

from .scoring import Momentum
from .signals import SignalEngine
from .smoothing import KeypointFilter
from .tracking import FighterTracker, build_dets

HOLD_FRAMES = 3  # keep drawing a briefly-lost fighter for this many frames


@dataclass
class FrameResult:
    k: int              # index within this run (0 = first analysed frame)
    fi: int             # index into cache["frames"]
    t: float            # seconds from the start of the video file
    frame: object       # BGR image
    cut: bool
    obs: list           # per fighter (kp, kc, box) measured this frame, or None
    vis: list           # per fighter what to draw (obs, or held for HOLD_FRAMES), or None
    held: list          # per fighter True when vis is a held (not measured) pose
    events: list        # signals.Event objects that fired this frame
    sig: SignalEngine   # live state (read it during the iteration, it mutates)
    mom: Momentum
    share: float        # displayed F1 momentum share, 0..1


def analyze(cache, cfg, pick=None, swap=False):
    """pick = {"frame": n, "dets": [i, j]} (indices into build_dets() of that frame).
    By default (CLI) the analysis starts AT the picked frame. With "from_start": True
    (web app) the fighters' appearance is learned on the picked frame and the whole
    video is analysed from frame 0."""
    fps, f0, frames = cache["fps"], cache["f0"], cache["frames"]
    from_start = bool(pick and pick.get("from_start"))
    cap = cv2.VideoCapture(cache["video"])
    start_idx = pick["frame"] if (pick and not from_start) else 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0 + start_idx)
    n = len(frames) - start_idx

    tracker = FighterTracker(cfg, fps)
    if from_start:
        pick_dets = build_dets(read_frame(cache["video"], f0 + pick["frame"]), frames[pick["frame"]], cfg)
        tracker.init_with(pick_dets[pick["dets"][0]], pick_dets[pick["dets"][1]], pick_dets)
        if swap:
            tracker.slots[0], tracker.slots[1] = tracker.slots[1], tracker.slots[0]
        tracker.begin_reacquire()
    filters = [KeypointFilter(cfg.euro_min_cutoff, cfg.euro_beta) for _ in range(2)]
    sig = SignalEngine(cfg, fps, (cache["height"], cache["width"]))
    mom = Momentum(cfg, fps)
    last_vis, waited = [None, None], 0
    try:
        for k in range(n):
            fi = start_idx + k
            ok, frame = cap.read()
            if not ok:
                break
            fd = frames[fi]
            M, cut = fd["M"], bool(fd["cut"]) and k > 0
            t = (f0 + fi) / fps
            dets = build_dets(frame, fd, cfg)

            if not tracker.initialized:
                if pick and k == 0 and not from_start:
                    tracker.init_with(dets[pick["dets"][0]], dets[pick["dets"][1]], dets)
                else:
                    tracker.try_auto_init(dets, waited)
                    waited += 1
                if tracker.initialized and swap:
                    tracker.slots[0], tracker.slots[1] = tracker.slots[1], tracker.slots[0]
            assigned = tracker.update(dets, M, cut) if tracker.initialized else [None, None]

            obs = [None, None]
            for i, d in enumerate(assigned):
                flt = filters[i]
                if d is None:
                    if tracker.slots[i].lost > HOLD_FRAMES:
                        flt.reset()
                        last_vis[i] = None
                    continue
                if cut or tracker.slots[i].lost > 0:
                    flt.reset()
                else:
                    flt.warp(M)
                kp = flt(d.kxy, d.kc > cfg.kp_conf, 1.0 / fps)
                obs[i] = (kp, d.kc, d.box)
                last_vis[i] = obs[i]

            events = sig.update(fi, t, obs, M, cut)
            share = mom.step(sig, events)
            vis = [obs[i] if obs[i] is not None else last_vis[i] for i in (0, 1)]
            held = [obs[i] is None and vis[i] is not None for i in (0, 1)]
            yield FrameResult(k, fi, t, frame, cut, obs, vis, held, events, sig, mom, share)
    finally:
        cap.release()


def read_frame(video, index):
    """One frame by index (seeking is frame-exact on the constant-frame-rate files the
    web app produces; checked against sequential decoding)."""
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise ValueError(f"could not read frame {index}")
    return img
