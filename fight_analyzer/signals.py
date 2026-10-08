"""Turn tracked keypoints into fight signals and discrete events.

What each signal REALLY measures (be honest about this in the video):

  approach/pressure  Hip-centre velocity toward the opponent, after removing camera
                     motion. Only the image-plane component: movement straight toward
                     or away from the camera is invisible.
  activity           How fast the limbs move relative to the hips.
  punch/kick         A fast wrist (ankle) burst relative to the shoulder (hip) that ends
  attempts           with the limb extended and travelling toward the opponent.
                     Feints and fast hand-fighting can count too; blocked strikes count.
  on target?         At the strike's peak extension the fist/foot is inside the
                     opponent's head circle / torso box IN 2D. Overlap in the image is
                     not proof of contact (the fist can pass in front of the head).
  drop / possible KD Torso goes from vertical to horizontal. Called "possible knockdown"
                     only if it was sudden, the opponent landed an "on target?" strike in
                     the last 1.5 s and the opponent is still standing.
  takedown?          A drop at close range, credited to whoever ends up on top within 2 s
                     (otherwise logged as a scramble with no points).
  control            Opponent down, at close range, with my head clearly above theirs.
"""
import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from .smoothing import warp_points

LIMBS = [("L", "hand", 5, 7, 9), ("R", "hand", 6, 8, 10),
         ("L", "kick", 11, 13, 15), ("R", "kick", 12, 14, 16)]


@dataclass
class Event:
    t: float
    frame: int
    fighter: int          # who gets the credit
    kind: str             # punch | kick | knockdown | takedown | drop
    label: str
    pos: tuple            # image coordinates (for the HUD popup)
    target: str | None = None
    victim: int | None = None


def _mid(kp, kc, i, j, thr):
    if kc[i] > thr and kc[j] > thr:
        return (kp[i] + kp[j]) / 2
    return None


def _head(kp, kc, thr):
    ok = kc[:5] > thr
    return kp[:5][ok].mean(0) if ok.any() else None


class FighterSig:
    def __init__(self):
        self.S = None
        self.visible = False
        self.hip = None
        self.prev_hip = None
        self.prev_kp = self.prev_kc = None
        self.vel = np.zeros(2)          # BL/s, camera-stabilised
        self.approach = 0.0
        self.pressure = 0.0
        self.activity = 0.0
        self.posture = "UP"
        self.down_t = self.up_t = 0.0
        self.vy_hist = deque()
        self.bursts = {}
        self.last_hand_t = self.last_kick_t = -99.0
        self.last_on_target_t = -99.0
        self.controlling = False
        self.ctrl_run = 0.0
        self.head_y = 0.0
        self.state = "SEARCHING"
        self.counts = dict(punches=0, kicks=0, on_target=0, absorbed=0,
                           knockdowns=0, takedowns=0)
        self.time = dict(engaged=0.0, adv=0.0, ret=0.0, ctrl=0.0)


class SignalEngine:
    def __init__(self, cfg, fps, frame_hw):
        self.cfg, self.fps, self.dt = cfg, fps, 1.0 / fps
        self.frame_hw = frame_hw
        self.pending = None
        self.engaged_standing = False
        self.f = [FighterSig(), FighterSig()]
        self.dist_bl = None
        self.range_label = "--"

    # ------------------------------------------------------------------------------------
    def update(self, fi, t, fighters, M, cut):
        """fighters: [ (kp, kc, box) | None, (kp, kc, box) | None ]  (kp = smoothed)"""
        cfg, events = self.cfg, []
        for i, obs in enumerate(fighters):
            self._body(self.f[i], obs, M, cut, t)

        a, b = self.f
        both = a.visible and b.visible
        if both:
            S = (a.S + b.S) / 2
            self.dist_bl = float(np.linalg.norm(a.hip - b.hip) / S)
            d = self.dist_bl
            self.range_label = ("CLINCH" if d < 1.3 else "CLOSE" if d < 2.5
                                else "STRIKING" if d < 4.5 else "OUTSIDE")
        else:
            self.dist_bl, self.range_label = None, "--"

        for i in (0, 1):
            me, opp = self.f[i], self.f[1 - i]
            obs, opp_obs = fighters[i], fighters[1 - i]
            if obs is not None:
                events += self._strikes(i, me, opp, obs, opp_obs, fi, t, cut)
        for i in (0, 1):
            events += self._posture(i, self.f[i], self.f[1 - i], fighters[i], fi, t)
        self._movement(cut)
        events += self._resolve_pending(fi, t)

        for i in (0, 1):
            obs = fighters[i]
            if obs is not None:
                self.f[i].prev_kp, self.f[i].prev_kc = obs[0].copy(), obs[1].copy()
                self.f[i].prev_hip = self.f[i].hip.copy()
            else:
                self.f[i].prev_kp = self.f[i].prev_hip = None
        return events

    # ------------------------------------------------------------------------------------
    def _body(self, s, obs, M, cut, t):
        cfg = self.cfg
        if obs is None:
            s.visible = False
            s.vel *= 0.9
            s.bursts.clear()
            return
        kp, kc, box = obs
        thr = cfg.kp_conf
        s.visible = True
        sh, hp = _mid(kp, kc, 5, 6, thr), _mid(kp, kc, 11, 12, thr)
        bh = box[3] - box[1]
        s.hip = hp if hp is not None else np.array([(box[0] + box[2]) / 2, box[1] + 0.55 * bh])
        hd = _head(kp, kc, thr)
        s.head_y = hd[1] if hd is not None else (sh[1] if sh is not None else box[1] + 0.1 * bh)
        torso = np.linalg.norm(sh - hp) if sh is not None and hp is not None else None
        s.angle = None
        if torso is not None and torso > 1:
            v = sh - hp
            s.angle = math.degrees(math.atan2(abs(v[0]), -v[1]))
        if s.S is None:
            s.S = torso if torso else 0.3 * bh
        elif torso and s.posture == "UP" and (s.angle or 0) < 30:
            s.S = 0.95 * s.S + 0.05 * torso
        s.S = max(s.S, 0.12 * bh, 5.0)

        if s.prev_hip is not None and not cut:
            v = (s.hip - warp_points(M, s.prev_hip[None])[0]) / self.dt / s.S
            s.vel = 0.75 * s.vel + 0.25 * np.clip(v, -15, 15)
            s.vy_hist.append((t, v[1]))
            ok = (kc[5:] > thr) & (s.prev_kc[5:] > thr)
            if ok.any():
                rel = kp[5:] - s.hip
                prel = s.prev_kp[5:] - s.prev_hip
                spd = np.linalg.norm(rel - prel, axis=1)[ok] / self.dt / s.S
                act = float(np.clip(np.mean(spd), 0, 10))
                a = self.dt / 0.5
                s.activity = (1 - a) * s.activity + a * act
        else:
            s.vel *= 0.5
        while s.vy_hist and t - s.vy_hist[0][0] > 0.6:
            s.vy_hist.popleft()

    # ------------------------------------------------------------------------------------
    def _strikes(self, i, me, opp, obs, opp_obs, fi, t, cut):
        cfg, events = self.cfg, []
        kp, kc, _ = obs
        thr = cfg.kp_conf
        if me.prev_kp is None or cut:
            me.bursts.clear()
            return events
        pk, pc = me.prev_kp, me.prev_kc
        for side, kind, a, m, e in LIMBS:
            key = side + kind
            if not (kc[[a, m, e]] > thr).all() or not (pc[[a, e]] > thr).all():
                me.bursts.pop(key, None)
                continue
            rel, prel = (kp[e] - kp[a]) / me.S, (pk[e] - pk[a]) / me.S
            speed = np.linalg.norm(rel - prel) / self.dt
            if speed > cfg.speed_cap:
                me.bursts.pop(key, None)
                continue
            seg = np.linalg.norm(kp[a] - kp[m]) + np.linalg.norm(kp[m] - kp[e]) + 1e-6
            ext = np.linalg.norm(kp[e] - kp[a]) / seg
            vthr = cfg.punch_speed if kind == "hand" else cfg.kick_speed
            b = me.bursts.get(key)
            if b is None:
                if speed > vthr:
                    me.bursts[key] = dict(kind=kind, side=side, start=pk[e].copy(), t0=t,
                                          ext=ext, pos=kp[e].copy(), raise_=self._raise(kp, kc, e, me.S),
                                          opp=None if opp_obs is None else (opp_obs[0].copy(), opp_obs[1].copy(), opp.S))
                continue
            if ext > b["ext"]:
                b["ext"], b["pos"] = ext, kp[e].copy()
                b["raise_"] = max(b["raise_"], self._raise(kp, kc, e, me.S))
                if opp_obs is not None:
                    b["opp"] = (opp_obs[0].copy(), opp_obs[1].copy(), opp.S)
            if speed < 0.5 * vthr or t - b["t0"] > cfg.max_burst_s:
                del me.bursts[key]
                ev = self._finalize(i, me, opp, b, fi, t)
                if ev:
                    events.append(ev)
        return events

    def _raise(self, kp, kc, e, S):
        other = 31 - e  # 15 <-> 16
        if e not in (15, 16) or kc[other] <= self.cfg.kp_conf:
            return 0.0
        return float((kp[other][1] - kp[e][1]) / S)  # +ve = kicking ankle is higher

    def _finalize(self, i, me, opp, b, fi, t):
        cfg = self.cfg
        if b["opp"] is None or not opp.visible or self.dist_bl is None:
            return None
        if self.dist_bl > cfg.strike_range:
            return None
        okp, okc, oS = b["opp"]
        thr = cfg.kp_conf
        head = _head(okp, okc, thr)
        chest = _mid(okp, okc, 5, 6, thr)
        aim = head if head is not None else chest if chest is not None else opp.hip
        d_strike, d_aim = b["pos"] - b["start"], aim - b["start"]
        cos = float(d_strike @ d_aim / (np.linalg.norm(d_strike) * np.linalg.norm(d_aim) + 1e-6))
        if cos < cfg.toward_cos:
            return None
        if b["kind"] == "hand":
            if b["ext"] < cfg.arm_extension or t - me.last_hand_t < cfg.hand_refractory_s:
                return None
            me.last_hand_t = t
            me.counts["punches"] += 1
            kind, label = "punch", f"{'LEFT' if b['side'] == 'L' else 'RIGHT'} HAND"
        else:
            if (b["ext"] < cfg.leg_extension or b["raise_"] < cfg.kick_raise
                    or me.posture != "UP" or t - me.last_kick_t < cfg.kick_refractory_s):
                return None
            me.last_kick_t = t
            me.counts["kicks"] += 1
            kind, label = "kick", f"{'LEFT' if b['side'] == 'L' else 'RIGHT'} KICK"

        target, p = None, b["pos"]
        if head is not None and np.linalg.norm(p - head) < cfg.head_radius * oS:
            target = "HEAD"
        else:
            tor = okp[[5, 6, 11, 12]][okc[[5, 6, 11, 12]] > thr]
            if len(tor) >= 3:
                lo, hi = tor.min(0), tor.max(0)
                pad = 0.1 * (hi - lo)
                if ((p > lo - pad) & (p < hi + pad)).all():
                    target = "BODY"
            if target is None and kind == "kick":
                leg = okp[11:17][okc[11:17] > thr]
                if len(leg) >= 3 and ((p > leg.min(0)) & (p < leg.max(0))).all():
                    target = "LEG"
        if target:
            me.counts["on_target"] += 1
            opp.counts["absorbed"] += 1
            me.last_on_target_t = t
        return Event(t, fi, i, kind, label, tuple(p), target)

    # ------------------------------------------------------------------------------------
    def _posture(self, i, me, opp, obs, fi, t):
        cfg, events = self.cfg, []
        if obs is None:
            return events
        kp, kc, box = obs
        thr = cfg.kp_conf
        bw, bh = box[2] - box[0], box[3] - box[1]
        aspect = bw / max(bh, 1)
        H, W = self.frame_hw
        clipped = box[0] < 3 or box[1] < 3 or box[2] > W - 3 or box[3] > H - 3
        # box shape only means something when the whole body is in frame
        full_body = not clipped and (kc[[11, 12, 13, 14, 15, 16]] > thr).sum() >= 4
        wide = full_body and aspect > 1.3
        hp = _mid(kp, kc, 11, 12, thr)
        head_low = hp is not None and kc[0] > thr and kp[0][1] > hp[1] + 0.2 * me.S
        down_sig = (me.angle is not None and me.angle > cfg.down_angle) or wide or head_low
        up_sig = ((me.angle is not None and me.angle < cfg.up_angle) or (me.angle is None and not wide)) \
            and not wide and not head_low
        me.down_t = me.down_t + self.dt if down_sig else 0.0
        me.up_t = me.up_t + self.dt if up_sig else 0.0

        if me.posture == "UP" and me.down_t >= cfg.down_hold_s:
            me.posture = "DOWN"
            sudden = max((vy for _, vy in me.vy_hist), default=0) >= cfg.sudden_drop
            recent_hit = t - opp.last_on_target_t <= cfg.kd_window_s
            close = self.dist_bl is not None and self.dist_bl < 2.0
            pos = tuple(me.hip)
            # Bending over a downed opponent (ground-and-pound) is not "going down": if the
            # opponent's head is clearly below mine, I'm on top.
            on_top = opp.visible and opp.head_y > me.head_y + 0.3 * me.S
            if on_top:
                pass
            elif recent_hit and sudden and opp.visible and opp.posture == "UP":
                opp.counts["knockdowns"] += 1
                events.append(Event(t, fi, 1 - i, "knockdown", "POSSIBLE KNOCKDOWN", pos, victim=i))
            elif close and opp.visible:
                # Takedowns often bring BOTH fighters down, so don't decide yet: credit
                # whoever ends up on top within 2 s (see _resolve_pending).
                if self.pending is None:
                    self.pending = dict(t=t, pos=pos)
            elif (sudden and opp.visible and opp.posture == "UP"
                  and opp.head_y < me.head_y - 0.3 * me.S):
                # only announce a plain drop when we can SEE the opponent standing above;
                # with the opponent hidden we can't tell a slip from ground-and-pound
                events.append(Event(t, fi, i, "drop", "FIGHTER DOWN", pos, victim=i))
        elif me.posture == "DOWN" and me.up_t >= cfg.up_hold_s:
            me.posture = "UP"
        return events

    def _resolve_pending(self, fi, t):
        p = self.pending
        if p is None:
            return []
        for i in (0, 1):
            if self.f[i].ctrl_run >= self.cfg.takedown_ctrl_s:   # sustained, not a flicker
                self.pending = None
                self.f[i].counts["takedowns"] += 1
                return [Event(t, fi, i, "takedown", "TAKEDOWN?", p["pos"], victim=1 - i)]
        if t - p["t"] > 2.5:
            self.pending = None
            return [Event(t, fi, 0, "drop", "SCRAMBLE", p["pos"])]
        return []

    # ------------------------------------------------------------------------------------
    def _movement(self, cut):
        cfg, dt = self.cfg, self.dt
        a, b = self.f
        both = a.visible and b.visible and self.dist_bl is not None
        for me, opp in ((a, b), (b, a)):
            me.controlling = False
            if both:
                d = opp.hip - me.hip
                me.approach = float(me.vel @ (d / (np.linalg.norm(d) + 1e-6)))
                # Control = opponent down, close, and MY HEAD clearly above theirs. (Torso
                # angle alone failed on real footage: a fighter on his back with legs up
                # looks "upright" in 2D and was credited with control and a takedown.)
                if (opp.posture == "DOWN" and self.dist_bl < 2.5
                        and me.head_y < opp.head_y - 0.3 * me.S):
                    me.controlling = True
            else:
                me.approach *= 0.9
            k = dt / 1.0
            me.pressure = (1 - k) * me.pressure + k * max(me.approach, 0.0)

        engaged = both and not cut and self.dist_bl < cfg.engage_range
        standing = a.posture == "UP" and b.posture == "UP"
        for me in (a, b):
            if engaged and standing:
                me.time["engaged"] += dt
                if me.approach > cfg.advance_thresh:
                    me.time["adv"] += dt
                elif me.approach < -cfg.advance_thresh:
                    me.time["ret"] += dt
            me.ctrl_run = me.ctrl_run + dt if me.controlling else 0.0
            if me.controlling:
                me.time["ctrl"] += dt
            if not me.visible:
                me.state = "SEARCHING"
            elif me.controlling:
                me.state = "CONTROL"
            elif me.posture == "DOWN":
                me.state = "DOWN"
            elif me.approach > cfg.advance_thresh:
                me.state = "ADVANCING"
            elif me.approach < -cfg.advance_thresh:
                me.state = "RETREATING"
            else:
                me.state = "HOLDING"
        self.engaged_standing = engaged and standing
