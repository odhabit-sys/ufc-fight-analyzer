"""Momentum index: a decaying points tally per fighter, shown as a share.

    momentum_i(t) = sum of points earned, each decayed with a 20 s half-life
    share_1       = (momentum_1 + prior) / (momentum_1 + momentum_2 + 2*prior)

The prior keeps the bar near 50/50 until real evidence accumulates, and the decay
means the number reflects *recent* momentum, not the whole fight. Every point is
attributed to a category so the HUD (and you, in the video) can explain the number.
"""
import numpy as np

CATS = ("strikes", "pressure", "control", "big")


class Momentum:
    def __init__(self, cfg, fps):
        self.cfg, self.fps = cfg, fps
        self.decay = 0.5 ** (1.0 / (cfg.half_life_s * fps))
        self.m = np.zeros((2, len(CATS)))       # decaying, per category
        self.total = np.zeros((2, len(CATS)))   # undecayed totals, for the breakdown
        self.share = 0.5
        self.display = 0.5

    def _add(self, i, cat, pts):
        k = CATS.index(cat)
        self.m[i, k] += pts
        self.total[i, k] += pts

    def step(self, sig, events):
        w, dt = self.cfg.weights, 1.0 / self.fps
        self.m *= self.decay
        f = sig.f
        for i in (0, 1):
            me, opp = f[i], f[1 - i]
            if sig.engaged_standing:
                self._add(i, "pressure", dt * w["pressure"] * float(np.clip(me.approach, 0, 3)))
                self._add(i, "pressure", dt * w["retreat_gift"] * float(np.clip(-opp.approach, 0, 3)))
            if me.visible:
                self._add(i, "strikes", dt * w["activity"] * min(me.activity, 4.0))
            if me.controlling:
                self._add(i, "control", dt * w["control"])
        for e in events:
            if e.kind in ("punch", "kick"):
                self._add(e.fighter, "strikes", w[e.kind] + (w["on_target"] if e.target else 0))
            elif e.kind in ("knockdown", "takedown"):
                self._add(e.fighter, "big", w[e.kind])

        m = self.m.sum(1)
        p = self.cfg.prior
        self.share = float((m[0] + p) / (m.sum() + 2 * p))
        a = dt / self.cfg.display_tau_s
        self.display = (1 - a) * self.display + a * self.share
        return self.display

    def breakdown(self, i):
        """Where fighter i's CURRENT (decayed) momentum comes from."""
        return dict(zip(CATS, self.m[i]))
