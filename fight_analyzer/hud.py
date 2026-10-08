"""Broadcast-style analysis HUD. Shapes are drawn with OpenCV, text with Pillow
(real fonts). Drop .ttf files into assets/fonts/ named title.ttf / num.ttf / mono.ttf
to restyle the whole thing."""
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
# RGB colours
RED, BLUE = (255, 59, 78), (47, 168, 255)
CYAN, WHITE, GREY, DIM = (124, 245, 255), (232, 238, 245), (128, 138, 150), (52, 60, 70)
BG, PANEL = (7, 9, 12), (13, 17, 23)
AMBER, GREEN = (255, 196, 61), (80, 255, 160)
FCOL = [RED, BLUE]
STATE_COL = {"ADVANCING": GREEN, "RETREATING": AMBER, "DOWN": RED, "CONTROL": CYAN,
             "HOLDING": WHITE, "SEARCHING": GREY}

EDGES = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
         (11, 13), (13, 15), (12, 14), (14, 16)]

FONTS = {
    "title": [ROOT / "assets/fonts/title.ttf", "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"],
    "num": [ROOT / "assets/fonts/num.ttf", "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"],
    "mono": [ROOT / "assets/fonts/mono.ttf", "/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"],
}


def bgr(c):
    return (int(c[2]), int(c[1]), int(c[0]))


def fmt_t(t):
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


class HUD:
    def __init__(self, src_w, src_h, fps, names, layout="frame", kp_conf=0.35):
        self.fps, self.names, self.layout, self.kp_conf = fps, names, layout, kp_conf
        self._fonts = {}
        if layout == "frame":
            self.W, self.H = 1920, 1080
            ax, ay, aw, ah = 240, 110, 1440, 810
            s = min(aw / src_w, ah / src_h)
            vw, vh = int(src_w * s) // 2 * 2, int(src_h * s) // 2 * 2
            self.vr = (ax + (aw - vw) // 2, ay + (ah - vh) // 2, vw, vh)
            self.R = dict(top=(0, 0, 1920, 110), left=(0, 110, 240, 1080),
                          right=(1680, 110, 1920, 1080), timeline=(262, 950, 1180, 1064),
                          feed=(1200, 950, 1666, 1064))
        else:
            s = 1080 / src_h
            self.W, self.H = int(src_w * s) // 2 * 2, 1080
            self.vr = (0, 0, self.W, self.H)
            W = self.W
            self.R = dict(top=(0, 0, W, 100), left=(16, 640, 256, 1064),
                          right=(W - 256, 640, W - 16, 1064),
                          timeline=(W // 2 - 400, 984, W // 2 + 400, 1064),
                          feed=(W - 496, 112, W - 16, 230))
        self.scale = self.vr[2] / src_w
        self.bg = self._make_bg()
        self.history = deque(maxlen=int(65 * fps))
        self.marks = deque()
        self.popups, self.banners = [], []
        self.feed = deque(maxlen=5)
        self.texts = []

    # ---- helpers ------------------------------------------------------------------------
    def font(self, kind, size):
        key = (kind, size)
        if key not in self._fonts:
            f = None
            for p in FONTS[kind]:
                if Path(p).exists():
                    f = ImageFont.truetype(str(p), size)
                    break
            self._fonts[key] = f or ImageFont.load_default(size)
        return self._fonts[key]

    def text(self, x, y, s, kind="mono", size=14, color=WHITE, anchor="la", alpha=255):
        self.texts.append((x, y, s, kind, size, tuple(color) + (int(alpha),), anchor))

    def _flush_text(self, img):
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil, "RGBA")
        for x, y, s, kind, size, color, anchor in self.texts:
            d.text((x, y), s, font=self.font(kind, size), fill=color, anchor=anchor)
        self.texts.clear()
        return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)

    @staticmethod
    def panel(img, r, color=PANEL, alpha=0.85, border=DIM):
        x1, y1, x2, y2 = map(int, r)
        roi = img[y1:y2, x1:x2]
        roi[:] = (roi * (1 - alpha) + np.array(bgr(color)) * alpha).astype(np.uint8)
        if border:
            cv2.rectangle(img, (x1, y1), (x2 - 1, y2 - 1), bgr(border), 1)

    @staticmethod
    def brackets(img, x1, y1, x2, y2, color, L, th=2):
        x1, y1, x2, y2, L = map(int, (x1, y1, x2, y2, L))
        for cx, cy, dx, dy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
            cv2.line(img, (cx, cy), (cx + dx * L, cy), color, th, cv2.LINE_AA)
            cv2.line(img, (cx, cy), (cx, cy + dy * L), color, th, cv2.LINE_AA)

    def bar(self, img, x, y, w, h, frac, color):
        cv2.rectangle(img, (x, y), (x + w, y + h), bgr(DIM), -1)
        fw = int(w * float(np.clip(frac, 0, 1)))
        if fw > 0:
            cv2.rectangle(img, (x, y), (x + fw, y + h), bgr(color), -1)

    def _make_bg(self):
        bg = np.full((self.H, self.W, 3), bgr(BG), np.uint8)
        if self.layout == "frame":
            for x in range(0, self.W, 40):
                cv2.line(bg, (x, 0), (x, self.H), (16, 14, 12), 1)
            for y in range(0, self.H, 40):
                cv2.line(bg, (0, y), (self.W, y), (16, 14, 12), 1)
        return bg

    def to_canvas(self, p):
        return (int(self.vr[0] + p[0] * self.scale), int(self.vr[1] + p[1] * self.scale))

    # ---- main entry -----------------------------------------------------------------------
    def render(self, frame, t, fi, sig, mom, vis, events, cut):
        """vis: per fighter (kp, kc, box) to draw, or None."""
        x0, y0, vw, vh = self.vr
        canvas = self.bg.copy()
        canvas[y0:y0 + vh, x0:x0 + vw] = cv2.resize(frame, (vw, vh), interpolation=cv2.INTER_AREA)

        self.history.append((t, mom.display))
        for e in events:
            self._on_event(e, t)

        self._skeletons(canvas, sig, vis)
        self._fighter_tags(canvas, sig, vis)
        self._range_line(canvas, sig, vis)
        self._popups(canvas, t)
        self._video_frame(canvas, t, fi, sig, cut)
        self._top_bar(canvas, mom)
        for i in (0, 1):
            self._side_panel(canvas, i, sig, mom)
        self._timeline(canvas, t)
        self._feed(canvas)
        self._banners(canvas, t)
        return self._flush_text(canvas)

    # ---- events -----------------------------------------------------------------------------
    def _on_event(self, e, t):
        col = FCOL[e.fighter]
        if e.kind in ("punch", "kick"):
            txt = ("KICK" if e.kind == "kick" else "STRIKE") + (f" · {e.target}?" if e.target else "")
            self.popups.append(dict(t0=t, pos=e.pos, text=txt, color=col, hit=bool(e.target)))
            detail = e.label + (f" · {e.target}?" if e.target else "")
            self.feed.appendleft((e.t, e.fighter, detail, WHITE))
        else:
            if e.kind == "takedown":
                sub, bc = f"FIGHTER {e.fighter + 1} ON TOP", FCOL[e.fighter]
            elif e.kind == "knockdown":
                sub, bc = f"FIGHTER {e.victim + 1} DOWN", AMBER
            elif e.victim is None:
                sub, bc = "BOTH FIGHTERS DOWN · NO CLEAR TOP POSITION", CYAN
            else:
                sub, bc = f"FIGHTER {e.victim + 1}", FCOL[e.victim]
            self.banners.append(dict(t0=t, text=e.label, sub=sub, color=bc))
            self.feed.appendleft((e.t, e.fighter, e.label, AMBER if e.kind == "knockdown" else WHITE))
        self.marks.append((e.t, e.fighter, e.kind))

    # ---- footage overlays ----------------------------------------------------------------------
    def _skeletons(self, canvas, sig, vis):
        x0, y0, vw, vh = self.vr
        roi = canvas[y0:y0 + vh, x0:x0 + vw]
        glow = np.zeros_like(roi)
        drawn = []
        for i, v in enumerate(vis):
            if v is None:
                continue
            kp, kc, _ = v
            pts = (kp * self.scale).astype(int)
            ok = kc > self.kp_conf
            S = (sig.f[i].S or 60) * self.scale
            th = int(np.clip(S / 28, 2, 6))
            col = bgr(FCOL[i])
            segs = [(tuple(pts[a]), tuple(pts[b])) for a, b in EDGES if ok[a] and ok[b]]
            if ok[0] and ok[5] and ok[6]:
                segs.append((tuple(pts[0]), tuple(((pts[5] + pts[6]) // 2))))
            for a, b in segs:
                cv2.line(glow, a, b, col, th * 4, cv2.LINE_AA)
            drawn.append((i, pts, ok, segs, th, col, S))
        if not drawn:
            return
        small = cv2.resize(glow, (vw // 3, vh // 3))
        small = cv2.GaussianBlur(small, (0, 0), 5)
        roi[:] = cv2.add(roi, cv2.resize(small, (vw, vh)))
        for i, pts, ok, segs, th, col, S in drawn:
            for a, b in segs:
                cv2.line(roi, a, b, col, th, cv2.LINE_AA)
                cv2.line(roi, a, b, (255, 255, 255), max(1, th // 3), cv2.LINE_AA)
            for j in range(5, 17):
                if ok[j]:
                    cv2.circle(roi, tuple(pts[j]), th + 2, col, -1, cv2.LINE_AA)
                    cv2.circle(roi, tuple(pts[j]), max(1, th - 1), (255, 255, 255), -1, cv2.LINE_AA)
            head = pts[:5][ok[:5]]
            if len(head):
                hc = head.mean(0).astype(int)
                cv2.circle(roi, tuple(hc), int(max(8, 0.45 * S)), col, max(1, th // 2), cv2.LINE_AA)

    def _fighter_tags(self, canvas, sig, vis):
        for i, v in enumerate(vis):
            if v is None:
                continue
            _, _, box = v
            f = sig.f[i]
            x1, y1 = self.to_canvas(box[:2])
            x2, y2 = self.to_canvas(box[2:])
            col = bgr(FCOL[i])
            self.brackets(canvas, x1, y1, x2, y2, col, 0.15 * min(x2 - x1, y2 - y1), 2)
            label = f"F{i + 1}  {self.names[i]}"
            tw = int(self.font("title", 22).getlength(label)) + 26
            tx, ty = x1, max(self.vr[1], y1 - 30)
            cv2.rectangle(canvas, (tx, ty), (tx + tw, ty + 24), col, -1)
            self.text(tx + 8, ty + 3, label, "title", 22, (10, 10, 10))
            self.text(tx, ty + 28 if ty + 28 < y1 else y1 + 4, f.state, "mono", 12,
                      STATE_COL.get(f.state, WHITE))
            spd = np.linalg.norm(f.vel)
            if spd > 0.3 and f.S:
                h = self.to_canvas(f.hip)
                tip = (int(h[0] + f.vel[0] * f.S * 0.35 * self.scale),
                       int(h[1] + f.vel[1] * f.S * 0.35 * self.scale))
                cv2.arrowedLine(canvas, h, tip, bgr(WHITE), 2, cv2.LINE_AA, tipLength=0.3)

    def _range_line(self, canvas, sig, vis):
        if sig.dist_bl is None or vis[0] is None or vis[1] is None:
            return
        a, b = np.array(self.to_canvas(sig.f[0].hip)), np.array(self.to_canvas(sig.f[1].hip))
        n = max(2, int(np.linalg.norm(b - a) / 14))
        for k in range(0, n, 2):
            p, q = a + (b - a) * k / n, a + (b - a) * (k + 1) / n
            cv2.line(canvas, tuple(p.astype(int)), tuple(q.astype(int)), bgr(CYAN), 1, cv2.LINE_AA)
        m = ((a + b) / 2).astype(int)
        self.text(m[0], m[1] - 8, f"{sig.range_label} · {sig.dist_bl:.1f} BL", "mono", 12, CYAN, "md")

    def _popups(self, canvas, t):
        keep = []
        for p in self.popups:
            age = t - p["t0"]
            if age > 0.8:
                continue
            keep.append(p)
            c = self.to_canvas(p["pos"])
            fade = 1 - age / 0.8
            r = int(12 + age * (90 if p["hit"] else 50))
            cv2.circle(canvas, c, r, bgr(AMBER if p["hit"] else p["color"]),
                       max(1, int(4 * fade)), cv2.LINE_AA)
            self.text(c[0], c[1] - 22 - age * 60, p["text"], "title", 26,
                      AMBER if p["hit"] else WHITE, "md", 255 * fade)
        self.popups = keep

    def _video_frame(self, canvas, t, fi, sig, cut):
        x0, y0, vw, vh = self.vr
        sy = y0 + int(((t % 4) / 4) * vh)
        band = canvas[sy:sy + 2, x0:x0 + vw]
        band[:] = cv2.add(band, np.full_like(band, (40, 50, 20)))
        if self.layout != "frame":  # overlay: HUD panels already occupy the corners
            self.text(x0 + vw // 2, self.R["top"][3] + 8,
                      f"T {fmt_t(t)}  ·  {'CUT / NEW ANGLE' if cut else 'CAM STABILIZED'}",
                      "mono", 12, CYAN, "ma")
            return
        self.brackets(canvas, x0 + 6, y0 + 6, x0 + vw - 7, y0 + vh - 7, bgr(CYAN), 30, 2)
        if int(t * 2) % 2 == 0:
            cv2.circle(canvas, (x0 + 26, y0 + 28), 6, bgr(RED), -1, cv2.LINE_AA)
        self.text(x0 + 40, y0 + 20, "ANALYZING", "mono", 14, WHITE)
        self.text(x0 + vw - 22, y0 + 20, f"T {fmt_t(t)}  ·  F {fi:05d}", "mono", 14, WHITE, "ra")
        cam = "CUT / NEW ANGLE" if cut else "STABILIZED"
        self.text(x0 + 22, y0 + vh - 34, f"POSE: 17-KPT  ·  CAM: {cam}", "mono", 12, CYAN)
        rng = sig.range_label if sig.dist_bl is None else f"{sig.range_label}  {sig.dist_bl:.1f} BL"
        self.text(x0 + vw - 22, y0 + vh - 34, f"RANGE: {rng}", "mono", 12, CYAN, "ra")

    # ---- interface panels ---------------------------------------------------------------------------
    def _top_bar(self, canvas, mom):
        x1, y1, x2, y2 = self.R["top"]
        frame = self.layout == "frame"
        self.panel(canvas, self.R["top"], BG if frame else PANEL, 0.95 if frame else 0.7, None)
        cv2.line(canvas, (x1, y2 - 1), (x2, y2 - 1), bgr(DIM), 1)
        W = x2 - x1
        p = mom.display
        bx1, bx2, by = x1 + 360, x2 - 360, y1 + 44
        split = int(bx1 + (bx2 - bx1) * p)
        cv2.rectangle(canvas, (bx1, by), (split, by + 26), bgr(RED), -1)
        cv2.rectangle(canvas, (split, by), (bx2, by + 26), bgr(BLUE), -1)
        for k in range(1, 10):
            x = int(bx1 + (bx2 - bx1) * k / 10)
            cv2.line(canvas, (x, by + 20), (x, by + 26), (20, 20, 20), 1)
        mid = (bx1 + bx2) // 2
        cv2.line(canvas, (mid, by - 4), (mid, by + 30), bgr(GREY), 1)
        cv2.rectangle(canvas, (split - 2, by - 8), (split + 2, by + 34), (255, 255, 255), -1)

        self.text(x1 + 24, y1 + 14, "RED CORNER · F1", "mono", 12, GREY)
        self.text(x1 + 24, y1 + 32, self.names[0], "title", 40, WHITE)
        self.text(x2 - 24, y1 + 14, "F2 · BLUE CORNER", "mono", 12, GREY, "ra")
        self.text(x2 - 24, y1 + 32, self.names[1], "title", 40, WHITE, "ra")
        self.text(bx1 - 16, by + 13, f"{round(p * 100)}%", "num", 52, RED, "rm")
        self.text(bx2 + 16, by + 13, f"{100 - round(p * 100)}%", "num", 52, BLUE, "lm")
        self.text(x1 + W // 2, y1 + 12, "MOMENTUM INDEX  //  EXPERIMENTAL", "title", 24, CYAN, "ma")
        self.text(x1 + W // 2, by + 38, "computer-vision activity score · not an official result or win probability",
                  "mono", 11, GREY, "ma")

    def _side_panel(self, canvas, i, sig, mom):
        r = self.R["left" if i == 0 else "right"]
        x1, y1, x2, y2 = r
        frame = self.layout == "frame"
        self.panel(canvas, r, PANEL, 0.92 if frame else 0.72)
        f, col = sig.f[i], FCOL[i]
        cv2.rectangle(canvas, (x1, y1), (x2, y1 + 4), bgr(col), -1)
        L, w = x1 + 18, x2 - x1 - 36
        y = y1 + 16
        self.text(L, y, f"FIGHTER {i + 1}", "title", 26, col)
        y += 34
        self.text(L, y, "STATUS", "mono", 11, GREY)
        self.text(L, y + 14, f.state, "title", 30, STATE_COL.get(f.state, WHITE))
        y += 54

        c = f.counts
        stats = [("PUNCHES", c["punches"]), ("KICKS", c["kicks"]), ("ON TARGET?", c["on_target"]),
                 ("KD? / TD?", f"{c['knockdowns']}/{c['takedowns']}")]
        if not frame:
            stats = stats[:3]
        cw = w // 2
        for k, (lab, val) in enumerate(stats):
            cx, cy = L + (k % 2) * cw, y + (k // 2) * 62
            self.text(cx, cy, lab, "mono", 11, GREY)
            self.text(cx, cy + 14, str(val), "num", 38, WHITE)
        y += 62 * ((len(stats) + 1) // 2) + 6

        for lab, val, mx in (("PRESSURE", f.pressure, 1.2), ("ACTIVITY", f.activity, 4.0),
                             ("SPEED", float(np.linalg.norm(f.vel)), 3.0)):
            self.text(L, y, lab, "mono", 11, GREY)
            self.text(L + w, y, f"{val:.2f}", "mono", 11, WHITE, "ra")
            self.bar(canvas, L, y + 16, w, 6, val / mx, col)
            y += 34
            if not frame and lab == "ACTIVITY":
                break

        eng = max(f.time["engaged"], 1e-6)
        adv, ret = f.time["adv"] / eng, f.time["ret"] / eng
        self.text(L, y, "ADVANCE vs RETREAT", "mono", 11, GREY)
        y += 16
        cv2.rectangle(canvas, (L, y), (L + w, y + 8), bgr(DIM), -1)
        cv2.rectangle(canvas, (L, y), (L + int(w * adv), y + 8), bgr(GREEN), -1)
        cv2.rectangle(canvas, (L + w - int(w * ret), y), (L + w, y + 8), bgr(AMBER), -1)
        self.text(L, y + 12, f"ADV {adv * 100:.0f}%", "mono", 11, GREEN)
        self.text(L + w, y + 12, f"RET {ret * 100:.0f}%", "mono", 11, AMBER, "ra")
        y += 36
        ct = f.time["ctrl"]
        self.text(L, y, "CONTROL TIME", "mono", 11, GREY)
        self.text(L + w, y, f"{int(ct // 60)}:{int(ct % 60):02d}", "mono", 11, WHITE, "ra")
        y += 30
        if not frame:
            return

        self.text(L, y, "MOMENTUM SOURCES (NOW)", "mono", 11, GREY)
        y += 20
        bd = mom.breakdown(i)
        mx = max(1e-6, max(max(mom.breakdown(0).values()), max(mom.breakdown(1).values())))
        for lab, key in (("STRIKES", "strikes"), ("PRESSURE", "pressure"),
                         ("CONTROL", "control"), ("KD / TD", "big")):
            self.text(L, y, lab, "mono", 11, WHITE)
            self.text(L + w, y, f"{bd[key]:.1f}", "mono", 11, GREY, "ra")
            self.bar(canvas, L, y + 15, w, 5, bd[key] / mx, col)
            y += 30
        self.text(L, y2 - 40, "? = 2D proximity at peak", "mono", 10, GREY)
        self.text(L, y2 - 26, "    extension, not confirmed", "mono", 10, GREY)
        self.text(L, y2 - 12, "    contact", "mono", 10, GREY)

    def _timeline(self, canvas, t):
        x1, y1, x2, y2 = self.R["timeline"]
        self.panel(canvas, self.R["timeline"], PANEL, 0.9 if self.layout == "frame" else 0.7)
        self.text(x1, y1 - 16, "MOMENTUM TIMELINE · LAST 60 s", "mono", 11, GREY)
        w, h = x2 - x1, y2 - y1
        yc = y1 + h // 2
        win = 60.0
        pts = [(int(x2 - (t - th) / win * w), int(y2 - s * h)) for th, s in self.history if t - th <= win]
        if len(pts) >= 2:
            poly = np.array([(pts[0][0], yc)] + pts + [(pts[-1][0], yc)], np.int32)
            mask = np.zeros((h, w), np.uint8)
            cv2.fillPoly(mask, [poly - [x1, y1]], 255)
            roi = canvas[y1:y2, x1:x2]
            for sl, c in ((slice(0, h // 2), RED), (slice(h // 2, h), BLUE)):
                sub, m = roi[sl], mask[sl] > 0
                sub[m] = (sub[m] * 0.55 + np.array(bgr(c)) * 0.45).astype(np.uint8)
            cv2.polylines(canvas, [np.array(pts, np.int32)], False, (255, 255, 255), 2, cv2.LINE_AA)
        for x in range(x1, x2, 12):
            cv2.line(canvas, (x, yc), (x + 5, yc), bgr(GREY), 1)
        while self.marks and t - self.marks[0][0] > win:
            self.marks.popleft()
        for te, fi_, kind in self.marks:
            x = int(x2 - (t - te) / win * w)
            if kind == "knockdown":
                cv2.line(canvas, (x, y1), (x, y2), bgr(AMBER), 2)
            elif kind in ("punch", "kick"):
                yy = y1 + 2 if fi_ == 0 else y2 - 8
                cv2.line(canvas, (x, yy), (x, yy + 6), bgr(FCOL[fi_]), 2)
            else:
                cv2.line(canvas, (x, y1), (x, y2), bgr(FCOL[fi_]), 1)
        self.text(x1 + 6, y1 + 4, "F1", "mono", 10, RED)
        self.text(x1 + 6, y2 - 16, "F2", "mono", 10, BLUE)
        self.text(x2 - 4, y2 + 2, "now", "mono", 10, GREY, "ra")

    def _feed(self, canvas):
        x1, y1, x2, y2 = self.R["feed"]
        self.panel(canvas, self.R["feed"], PANEL, 0.9 if self.layout == "frame" else 0.7)
        self.text(x1, y1 - 16, "EVENT LOG", "mono", 11, GREY)
        y = y1 + 8
        rows = 5 if self.layout == "frame" else 4
        for te, fi_, label, c in list(self.feed)[:rows]:
            self.text(x1 + 10, y, fmt_t(te), "mono", 12, GREY)
            self.text(x1 + 82, y, f"F{fi_ + 1}", "mono", 12, FCOL[fi_])
            self.text(x1 + 110, y, label, "mono", 12, c)
            y += 21

    def _banners(self, canvas, t):
        x0, y0, vw, vh = self.vr
        keep = []
        for b in self.banners[-1:]:
            age = t - b["t0"]
            if age > 2.5:
                continue
            keep.append(b)
            a = min(1.0, age / 0.15, (2.5 - age) / 0.3)
            cx, cy = x0 + vw // 2, y0 + int(vh * 0.16)
            r = (cx - 330, cy - 44, cx + 330, cy + 44)
            self.panel(canvas, r, BG, 0.75 * a, None)
            cv2.rectangle(canvas, (r[0], r[1]), (r[0] + 8, r[3]), bgr(b["color"]), -1)
            self.text(cx, cy - 6, b["text"], "title", 52, b["color"], "mm", 255 * a)
            self.text(cx, cy + 30, b["sub"], "mono", 14, WHITE, "mm", 255 * a)
        self.banners = keep
