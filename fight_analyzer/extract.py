"""Stage 1 (slow): pose estimation + camera motion for every frame, cached to disk."""
import pickle
import time

import cv2
import numpy as np

MOTION_WIDTH = 640  # camera motion is estimated on a downscaled grey frame


def pick_device(device):
    if device:
        return device
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def estimate_camera_motion(prev, curr, boxes, scale):
    """Return (M, is_cut). M is a 2x3 similarity transform mapping previous-frame
    pixel coordinates to current-frame coordinates (full resolution). Fighters are
    masked out so only the background (cage, canvas, crowd) drives the estimate."""
    identity = np.array([[1, 0, 0], [0, 1, 0]], np.float32)
    if prev is None:
        return identity, True

    hp = cv2.calcHist([prev], [0], None, [32], [0, 256])
    hc = cv2.calcHist([curr], [0], None, [32], [0, 256])
    cv2.normalize(hp, hp)
    cv2.normalize(hc, hc)
    hist_corr = cv2.compareHist(hp, hc, cv2.HISTCMP_CORREL)

    mask = np.full(prev.shape, 255, np.uint8)
    for x1, y1, x2, y2 in boxes * scale:
        pw, ph = 0.1 * (x2 - x1), 0.05 * (y2 - y1)
        mask[max(0, int(y1 - ph)):int(y2 + ph), max(0, int(x1 - pw)):int(x2 + pw)] = 0

    pts = cv2.goodFeaturesToTrack(prev, 400, 0.01, 8, mask=mask)
    if pts is None or len(pts) < 20:
        return identity, hist_corr < 0.6
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, curr, pts, None, winSize=(21, 21), maxLevel=3)
    good = st.ravel() == 1
    if good.sum() < 15:
        return identity, True
    M, inliers = cv2.estimateAffinePartial2D(pts[good], nxt[good], method=cv2.RANSAC,
                                             ransacReprojThreshold=2.0)
    n_in = 0 if inliers is None else int(inliers.sum())
    if M is None or n_in < 12 or n_in < 0.25 * good.sum() or hist_corr < 0.5:
        return identity, True
    M = M.astype(np.float32)
    M[:, 2] /= scale  # translation back to full-res pixels (rotation/scale are unitless)
    return M, False


def extract(video_path, cache_path, cfg, start_s=0.0, end_s=None, progress=None):
    """progress(done, total, last) is called after every batch when given (used by the web
    app); `last` is the newest frame's raw detections, for a live preview."""
    from ultralytics import YOLO

    device = pick_device(cfg.device)
    model = YOLO(cfg.pose_model)
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    f0 = int(round(start_s * fps))
    f1 = total if end_s is None else min(total, int(round(end_s * fps)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    scale = min(1.0, MOTION_WIDTH / W)
    small_size = (int(W * scale), int(H * scale))

    print(f"[extract] {video_path}  {W}x{H} @ {fps:.2f}fps  frames {f0}-{f1}  "
          f"model={cfg.pose_model} device={device}")
    frames, prev_small = [], None
    t0, n = time.time(), f1 - f0
    while len(frames) < n:
        batch = []
        while len(batch) < cfg.batch and len(frames) + len(batch) < n:
            ok, img = cap.read()
            if not ok:
                break
            batch.append(img)
        if not batch:
            break
        results = model.predict(batch, imgsz=cfg.imgsz, conf=cfg.det_conf, device=device,
                                verbose=False)
        for img, r in zip(batch, results):
            boxes = r.boxes.xyxy.cpu().numpy() if r.boxes is not None else np.zeros((0, 4))
            scores = r.boxes.conf.cpu().numpy() if r.boxes is not None else np.zeros(0)
            if r.keypoints is not None and len(boxes):
                kxy = r.keypoints.xy.cpu().numpy()
                kc = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None \
                    else np.ones(kxy.shape[:2])
            else:
                kxy, kc = np.zeros((0, 17, 2)), np.zeros((0, 17))
            small = cv2.cvtColor(cv2.resize(img, small_size, interpolation=cv2.INTER_AREA),
                                 cv2.COLOR_BGR2GRAY)
            M, cut = estimate_camera_motion(prev_small, small, boxes, scale)
            prev_small = small
            frames.append(dict(boxes=boxes.astype(np.float32), scores=scores.astype(np.float32),
                               kxy=kxy.astype(np.float32), kc=kc.astype(np.float32),
                               M=M, cut=cut))
        done = len(frames)
        el = time.time() - t0
        if progress:
            progress(done, n, frames[-1])
        if done // cfg.batch % 25 and done < n:
            continue
        print(f"\r[extract] {done}/{n} frames  {done / el:.1f} fps  "
              f"ETA {(n - done) / max(done / el, 1e-6):.0f}s   ", end="", flush=True)
    print()
    cap.release()
    data = dict(video=str(video_path), fps=fps, width=W, height=H, f0=f0,
                model=cfg.pose_model, imgsz=cfg.imgsz, frames=frames)
    with open(cache_path, "wb") as f:
        pickle.dump(data, f)
    return data


def load_cache(cache_path):
    with open(cache_path, "rb") as f:
        return pickle.load(f)
