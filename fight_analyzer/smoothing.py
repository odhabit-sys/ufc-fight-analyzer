"""One Euro filter (Casiez et al., 2012) for keypoints: smooth when still, responsive when fast."""
import math

import numpy as np


def _alpha(cutoff, dt):
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


def warp_points(M, pts):
    return pts @ M[:, :2].T + M[:, 2]


class KeypointFilter:
    def __init__(self, min_cutoff=1.2, beta=0.015, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.valid = None

    def reset(self):
        self.x = self.dx = self.valid = None

    def warp(self, M):
        """Move the filter state with the camera so pans/zooms don't cause lag."""
        if self.x is not None:
            self.x = warp_points(M, self.x)
            self.dx = self.dx @ M[:, :2].T

    def __call__(self, x, valid, dt):
        x = np.asarray(x, np.float64)
        if self.x is None:
            self.x, self.dx, self.valid = x.copy(), np.zeros_like(x), valid.copy()
            return self.x.copy()
        dx = (x - self.x) / dt
        a_d = _alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * np.linalg.norm(dx_hat, axis=1, keepdims=True)
        tau = 1.0 / (2 * math.pi * cutoff)
        a = 1.0 / (1.0 + tau / dt)
        x_hat = a * x + (1 - a) * self.x
        fresh = (valid & ~self.valid)[:, None]          # point just reappeared: snap to it
        x_hat = np.where(fresh, x, x_hat)
        dx_hat = np.where(fresh, 0.0, dx_hat)
        keep = valid[:, None]
        self.x = np.where(keep, x_hat, self.x)
        self.dx = np.where(keep, dx_hat, self.dx)
        self.valid = valid.copy()
        return self.x.copy()
