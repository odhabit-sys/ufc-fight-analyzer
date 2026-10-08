"""Two-fighter identity tracking.

Generic multi-object trackers (ByteTrack/BoT-SORT) hand out new IDs whenever a
person is lost, and MMA breaks them constantly: clinches, crossing, camera cuts.
We only ever need TWO identities, so instead we keep two fixed slots and, every
frame, solve a 2xN assignment with a cost made of:

  * appearance  - colour histogram of the shorts and torso (the most stable cue
                  in MMA: fighters wear different shorts, the referee wears a shirt)
  * position    - distance to where the slot is predicted to be (camera-compensated)
  * overlap     - IoU with the predicted box

During clinches / overlap, and after camera cuts or long losses, position is
unreliable, so the cost shifts toward appearance only.
"""
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from .smoothing import warp_points

SH, HP, KN = (5, 6), (11, 12), (13, 14)


def box_iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _region_hist(hsv, x1, y1, x2, y2):
    h, w = hsv.shape[:2]
    x1, y1, x2, y2 = max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    hist = cv2.calcHist([hsv[y1:y2, x1:x2]], [0, 1, 2], None, [12, 4, 4],
                        [0, 180, 0, 256, 0, 256])
    cv2.normalize(hist, hist, 1, 0, cv2.NORM_L1)
    return hist


def _skin_ratio(ycrcb, x1, y1, x2, y2):
    h, w = ycrcb.shape[:2]
    x1, y1, x2, y2 = max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return 0.0
    roi = ycrcb[y1:y2, x1:x2]
    cr, cb = roi[..., 1], roi[..., 2]
    return float(((cr > 135) & (cr < 180) & (cb > 80) & (cb < 135)).mean())


def body_regions(kxy, kc, box, thr):
    """Torso and shorts rectangles, from keypoints when visible, else from the box."""
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    ok = kc > thr
    if ok[[5, 6, 11, 12]].all():
        pts = kxy[[5, 6, 11, 12]]
        tx1, ty1 = pts.min(0)
        tx2, ty2 = pts.max(0)
        if tx2 - tx1 < 0.3 * bw:  # side-on: widen around the centre
            cx = (tx1 + tx2) / 2
            tx1, tx2 = cx - 0.15 * bw, cx + 0.15 * bw
        th = ty2 - ty1
        torso = (tx1, ty1 + 0.15 * th, tx2, ty2 - 0.1 * th)
        hip_y = kxy[[11, 12], 1].mean()
        knee_y = kxy[[13, 14], 1].mean() if ok[[13, 14]].all() else hip_y + 0.6 * max(th, 1)
        hx1, hx2 = sorted(kxy[[11, 12], 0])
        pad = 0.25 * (hx2 - hx1) + 0.05 * bw
        leg = max(knee_y - hip_y, 0.15 * bh)
        shorts = (hx1 - pad, hip_y - 0.05 * leg, hx2 + pad, hip_y + 0.6 * leg)
    else:
        torso = (x1 + 0.25 * bw, y1 + 0.2 * bh, x2 - 0.25 * bw, y1 + 0.45 * bh)
        shorts = (x1 + 0.25 * bw, y1 + 0.45 * bh, x2 - 0.25 * bw, y1 + 0.62 * bh)
    return torso, shorts


@dataclass
class Det:
    box: np.ndarray
    score: float
    kxy: np.ndarray
    kc: np.ndarray
    app: dict = None
    candidate: bool = True     # False = looks like a spectator, never assigned

    @property
    def center(self):
        return np.array([(self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2])

    @property
    def area(self):
        return float((self.box[2] - self.box[0]) * (self.box[3] - self.box[1]))


def build_dets(frame, fd, cfg):
    """Turn cached raw detections into Det objects with appearance descriptors."""
    H, W = frame.shape[:2]
    hsv = ycrcb = None
    dets = []
    for box, score, kxy, kc in zip(fd["boxes"], fd["scores"], fd["kxy"], fd["kc"]):
        if (kc > cfg.kp_conf).sum() < cfg.min_visible_kps:
            continue
        if (box[2] - box[0]) * (box[3] - box[1]) < cfg.min_box_area * W * H:
            continue
        if hsv is None:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
        torso, shorts = body_regions(kxy, kc, box, cfg.kp_conf)
        app = dict(torso=_region_hist(hsv, *torso), shorts=None, skin=_skin_ratio(ycrcb, *torso))
        # The shorts are the only reliable identity cue (two bare backs look alike), so
        # only describe them when most of the region is actually in frame.
        sx1, sy1, sx2, sy2 = shorts
        full = max(1.0, (sx2 - sx1) * (sy2 - sy1))
        cx1, cy1, cx2, cy2 = max(0, sx1), max(0, sy1), min(W, sx2), min(H, sy2)
        inside = max(0.0, cx2 - cx1) * max(0.0, cy2 - cy1)
        if inside / full >= 0.6 and inside >= cfg.min_shorts_px:
            app["shorts"] = _region_hist(hsv, *shorts)
        dets.append(Det(box.copy(), float(score), kxy.copy(), kc.copy(), app))
    # Spectators behind the cage show up as head-and-shoulders boxes that end mid-frame
    # with no legs visible, and are much smaller than the people inside the cage.
    if dets:
        biggest = max(np.sqrt(d.area) for d in dets)
        for d in dets:
            legs_visible = (d.kc[13:17] > cfg.kp_conf).any()
            floating = ((not legs_visible and d.box[3] < cfg.floating_bottom * H)
                        or d.box[3] < cfg.min_bottom * H)   # ends in the upper half: in the stands
            small = np.sqrt(d.area) < cfg.min_rel_size * biggest
            d.candidate = not (floating or small)
    return dets


def app_distance(tmpl, app):
    """Bhattacharyya distance (0 = identical, 1 = totally different), shorts-weighted."""
    total, wsum = 0.0, 0.0
    for key, w in (("shorts", 0.65), ("torso", 0.35)):
        if tmpl.get(key) is not None and app.get(key) is not None:
            total += w * cv2.compareHist(tmpl[key], app[key], cv2.HISTCMP_BHATTACHARYYA)
            wsum += w
    return total / wsum if wsum else 0.5


class Slot:
    def __init__(self):
        self.box = None
        self.vel = np.zeros(2)       # px/frame in camera-stabilised coordinates
        self.template = None
        self.lost = 0
        self.noncand = 0             # consecutive frames spent on a spectator-looking box
        self.pending, self.pending_n = None, 0   # unconfirmed jump target
        self.lost_by_jump = False

    def init(self, det):
        self.box = det.box.astype(np.float64).copy()
        self.vel[:] = 0
        self.template = {k: (v.copy() if isinstance(v, np.ndarray) else v)
                         for k, v in det.app.items()}
        self.lost = 0

    def predict(self, M, cut):
        if self.box is None:
            return
        if cut:
            self.vel[:] = 0
            return
        corners = warp_points(M, self.box.reshape(2, 2))
        self.box = corners.reshape(4) + np.tile(self.vel, 2)

    @property
    def center(self):
        b = self.box
        return np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])

    def adapt(self, app, lr):
        for key in ("shorts", "torso"):
            if self.template.get(key) is not None and app.get(key) is not None:
                h = (1 - lr) * self.template[key] + lr * app[key]
                self.template[key] = h / max(h.sum(), 1e-9)


class FighterTracker:
    """Slots 0 and 1 are the fighters. Slot 2 is the REFEREE: tracked exactly like a
    fighter but never drawn or scored. Its only job is to claim the referee so neither
    fighter slot can take him. (On real footage the referee's dark shirt/trousers looked
    as similar to the black-shorts fighter as that fighter did to himself after a camera
    change, so an absolute colour threshold alone could not keep them apart.)"""

    def __init__(self, cfg, fps):
        self.cfg, self.fps = cfg, fps
        self.slots = [Slot(), Slot(), Slot()]
        self.initialized = False
        self.overlap = False

    # ---- initialisation --------------------------------------------------------------
    def init_with(self, d1, d2, dets=None, ref=None):
        self.slots[0].init(d1)
        self.slots[1].init(d2)
        if ref is None and dets:
            # referee guess: the largest remaining full-body person
            rest = [d for d in dets if d is not d1 and d is not d2 and d.candidate
                    and (d.kc[13:17] > self.cfg.kp_conf).any()]
            ref = max(rest, key=lambda d: d.area) if rest else None
        if ref is not None:
            self.slots[2].init(ref)
        self.initialized = True

    def begin_reacquire(self):
        """After init_with() on a frame other than the current one: forget positions and
        treat every slot as lost, so they are re-found by appearance alone (the same path
        used after camera cuts). Lets the user pick fighters on any frame of the video
        while the analysis still starts at frame 0."""
        for s in self.slots:
            if s.template is not None:
                s.lost = 10 ** 6
                s.vel[:] = 0

    def try_auto_init(self, dets, frames_waited):
        """Pick the two largest, shirtless-looking people. After ~3 s of not finding two
        shirtless people (e.g. women's bouts in rash guards), fall back to the two largest."""
        pool = [d for d in dets if d.candidate]
        cands = [d for d in pool if d.app["skin"] >= self.cfg.min_skin_auto_init]
        if len(cands) < 2 and frames_waited > 3 * self.fps:
            cands = pool
        if len(cands) < 2:
            return False
        a, b = sorted(cands, key=lambda d: -d.area)[:2]
        if a.center[0] > b.center[0]:
            a, b = b, a  # Fighter 1 = left at the start
        self.init_with(a, b, pool)
        return True

    # ---- per-frame update --------------------------------------------------------------
    def update(self, dets, M, cut):
        cfg = self.cfg
        active = [i for i, s in enumerate(self.slots) if s.template is not None]
        prev_centers = [s.center if s.box is not None else None for s in self.slots]
        for i in active:
            self.slots[i].predict(M, cut)
        self.overlap = box_iou(self.slots[0].box, self.slots[1].box) > 0.15
        out = [None] * len(self.slots)
        if dets:
            app = np.array([[app_distance(self.slots[i].template, d.app) for d in dets]
                            if i in active else [9.0] * len(dets) for i in range(len(self.slots))])
            C = np.full((len(self.slots), len(dets)), 9.0)
            for i in active:
                s = self.slots[i]
                lost_s = s.lost / self.fps
                reacq = cut or lost_s > cfg.reacquire_after_s
                if reacq:
                    wa, wp, wi = 1.0, 0.0, 0.0
                elif self.overlap and i < 2:
                    wa, wp, wi = 0.7, 0.15, 0.15
                else:
                    wa, wp, wi = cfg.app_weight, cfg.pos_weight, cfg.iou_weight
                diag = np.hypot(s.box[2] - s.box[0], s.box[3] - s.box[1]) + 1e-6
                others = [k for k in active if k != i]
                for j, d in enumerate(dets):
                    iou = box_iou(s.box, d.box)
                    # spectator filter, except for a person we are continuously tracking
                    if not d.candidate and not (iou > 0.3 and s.lost <= 2
                                                and s.noncand < cfg.max_noncand_s * self.fps):
                        continue
                    a = app[i, j]
                    # A fresh identity decision (after a loss or a camera cut) needs the shorts.
                    if reacq and i < 2 and d.app["shorts"] is None:
                        continue
                    # A weak match that looks about equally like the other fighter is a coin
                    # flip; stay lost rather than risk an identity swap.
                    # (applies to the referee slot too, so it can't grab an ambiguous fighter)
                    nearest_other = min((app[k, j] for k in others), default=9.0)
                    if a > cfg.weak_match and nearest_other - a < cfg.ambiguous_margin:
                        continue
                    gate = cfg.app_gate_reacquire if reacq else cfg.app_gate
                    if a > gate and not (iou > 0.5 and not self.overlap):
                        continue
                    # No stealing: if this box is clearly the continuation of the OTHER
                    # fighter's track, only take it on strong appearance evidence. (On real
                    # footage a fighter turning his back failed his own appearance gate for a
                    # moment and the other slot grabbed him: a swap. Lost beats swapped.)
                    if i < 2:
                        o = self.slots[1 - i]
                        if o.lost <= 2:
                            iou_o = box_iou(o.box, d.box)
                            # (also covers a merged two-fighter blob on the ground: whoever
                            # had it keeps it instead of the label flipping every few frames)
                            if iou_o > 0.5 and app[1 - i, j] - a < cfg.steal_margin:
                                continue
                    pos = min(np.linalg.norm(s.center - d.center) / diag, 2.0) / 2.0
                    # Relative appearance: how much more this person looks like slot i
                    # than like anyone else we track. Far more robust than absolute colour
                    # distance (black shorts "match" any dark clothing in absolute terms).
                    rel = max(0.0, a + cfg.app_contrast * (a - min(nearest_other, 1.0)))
                    C[i, j] = wa * rel + wp * pos + wi * (1 - iou)
            rows, cols = linear_sum_assignment(C)
            for i, j in zip(rows, cols):
                if C[i, j] < cfg.match_gate:
                    out[i] = dets[j]

        # Jump confirmation: a tracked slot that suddenly lands on a box nowhere near where
        # it was predicted must see that jump repeat for a few frames before we believe it.
        # (On real ground footage, labels hopped for 1-2 frames onto a spectator or onto a
        # sub-box of the tangle; those single-frame hops are what made skeletons flicker.)
        for i in active:
            s, d = self.slots[i], out[i]
            if d is None or cut or s.lost > 0:
                s.pending, s.pending_n = None, 0
                continue
            if box_iou(s.box, d.box) >= 0.2:
                s.pending, s.pending_n = None, 0
                continue
            if s.pending is not None and box_iou(s.pending, d.box) > 0.5:
                s.pending_n += 1
            else:
                s.pending_n = 1
            s.pending = d.box.copy()
            if s.pending_n < cfg.jump_confirm_frames:
                out[i] = None
                s.lost_by_jump = True

        for i in active:
            s, d = self.slots[i], out[i]
            if d is None:
                if s.lost_by_jump:
                    s.lost_by_jump = False   # held back, not really lost: keep tracking mode
                    s.vel *= 0.8
                    continue
                s.lost += 1
                s.vel *= 0.8
                continue
            if prev_centers[i] is not None and not cut and s.lost == 0:
                disp = d.center - warp_points(M, prev_centers[i][None])[0]
                s.vel = 0.6 * s.vel + 0.4 * disp
            else:
                s.vel[:] = 0
            s.box = d.box.astype(np.float64).copy()
            s.lost = 0
            s.noncand = 0 if d.candidate else s.noncand + 1
            # adapt only when clearly this identity (lets templates follow new camera angles
            # without drifting onto the opponent during clinches)
            j = next(k for k, x in enumerate(dets) if x is d)
            margin = min((app[k, j] for k in active if k != i), default=1.0) - app[i, j]
            if not self.overlap and app[i, j] < cfg.adapt_max_dist and margin > cfg.adapt_margin:
                s.adapt(d.app, cfg.template_lr)
        return out[:2]
