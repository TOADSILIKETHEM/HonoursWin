"""Blender F-curve handles for per-frame point tracks (numpy only, no bpy).

DEMGrainsBlenderEarthCam.py (per-sphere) keyframes every grain's location
once per sim frame, and Blender turns those keys into Bezier curves with
AUTO_CLAMPED handles and "Continuous Acceleration" auto-smoothing (the
Blender 5.x default for new F-curves, and the setting in the Blender install
this pipeline renders with). Instance points cannot carry keyframes, so the
instance path stores the same handles next to each frame's positions and
DEMBulkInstanceBlender.py evaluates the cubic itself (:func:`evaluate`).

Ported from Blender's BKE_nurb_handle_smooth_fcurve (curve.cc) for keys one
frame apart with constant extrapolation:
- handle x sits 1/3 of a frame from its key, so a segment is a cubic in t;
- first and last keys get flat handles (ease in/out);
- interior right-handle offsets h solve h[i-1] + 4 h[i] + h[i+1] = y[i+1] - y[i-1]
  (continuous first and second derivative), then AUTO_CLAMPED limits each h
  to the neighbouring key steps (no overshoot, flat at extrema) by locking and
  re-solving, exactly as Blender's tridiagonal_solve_with_limits does.
sobol/tests/test_fcurve_handles.py checks this against Blender's own
FCurve.evaluate().
"""

import numpy as np

SMOOTHING = 'CONT_ACCEL'


def _thomas(a, b, c, d):
    """Solve tridiagonal systems column-wise; arrays are (n, m)."""
    n = len(b)
    cp = np.empty_like(c)
    dp = np.empty_like(d)
    cp[0] = c[0] / b[0]
    dp[0] = d[0] / b[0]
    for i in range(1, n):
        m = b[i] - a[i] * cp[i - 1]
        cp[i] = c[i] / m
        dp[i] = (d[i] - a[i] * dp[i - 1]) / m
    x = np.empty_like(d)
    x[-1] = dp[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


def _clamp_limits(dy_next, dy_prev):
    """Blender's bezier_clamp for an AUTO_CLAMPED key: range allowed for its handle offset."""
    hmax = np.full(dy_next.shape, np.inf)
    hmin = np.full(dy_next.shape, -np.inf)
    for dy in (dy_next, dy_prev):
        pos = dy > 0
        neg = dy < 0
        zero = ~pos & ~neg
        hmax = np.where(pos, np.minimum(hmax, dy), hmax)
        hmin = np.where(pos, 0.0, hmin)
        hmax = np.where(neg, 0.0, hmax)
        hmin = np.where(neg, np.maximum(hmin, dy), hmin)
        hmax = np.where(zero, 0.0, hmax)
        hmin = np.where(zero, 0.0, hmin)
    return hmin, hmax


def right_handle_offsets(y):
    """Right-handle y offsets ``h`` (same shape as ``y``) for keys ``y[0..n-1]`` along axis 0.

    Left handle of key i sits at ``y[i] - h[i]``, right handle at ``y[i] + h[i]``.
    """
    y = np.asarray(y, dtype=np.float64)
    shape = y.shape
    n = shape[0]
    cols = y.reshape(n, -1)
    h = np.zeros_like(cols)
    if n < 3:
        return h.reshape(shape)

    m = cols.shape[1]
    dy = np.diff(cols, axis=0)  # dy[i] = y[i+1] - y[i]
    a0 = np.zeros((n, m))
    b0 = np.ones((n, m))
    c0 = np.zeros((n, m))
    d0 = np.zeros((n, m))  # rows 0 and n-1: locked flat end handles
    a0[1:-1] = 1.0
    b0[1:-1] = 4.0
    c0[1:-1] = 1.0
    d0[1:-1] = dy[1:] + dy[:-1]

    hmin = np.zeros((n, m))
    hmax = np.zeros((n, m))
    hmin[1:-1], hmax[1:-1] = _clamp_limits(dy[1:], dy[:-1])

    a, b, c, d = a0.copy(), b0.copy(), c0.copy(), d0.copy()
    locked = np.zeros((n, m), dtype=bool)
    unlocks = np.zeros((n, m), dtype=np.int8)

    for _ in range(10 * n + 10):
        h = _thomas(a, b, c, d)
        over = (h < hmin) | (h > hmax)
        target = np.where(h > hmax, hmax, hmin)
        # Lock overshooting handles that have somewhere nonzero to go; only if a
        # curve has none of those, lock its overshooting ones at zero.
        nonzero = over & (target != 0.0)
        col_has_nonzero = nonzero.any(axis=0)
        lock_now = np.where(col_has_nonzero, nonzero, over)
        overshoot_cols = over.any(axis=0)

        locked |= lock_now
        a = np.where(lock_now, 0.0, a)
        c = np.where(lock_now, 0.0, c)
        b = np.where(lock_now, 1.0, b)
        d = np.where(lock_now, target, d)

        # Curves that locked nothing this round may release handles that now
        # want to move back inside their range (at most twice per handle).
        state = np.zeros_like(h)
        state[1:-1] = a0[1:-1] * h[:-2] + b0[1:-1] * h[1:-1] + c0[1:-1] * h[2:]
        relax = (d0 - state) * b0
        release = (
            locked & (unlocks < 2) & ~overshoot_cols[None, :]
            & (((relax > 0) & (h < hmax)) | ((relax < 0) & (h > hmin)))
        )
        if release.any():
            locked &= ~release
            unlocks += release.astype(np.int8)
            a = np.where(release, a0, a)
            b = np.where(release, b0, b)
            c = np.where(release, c0, c)
            d = np.where(release, d0, d)

        if not overshoot_cols.any() and not release.any():
            return h.reshape(shape)
    raise RuntimeError('F-curve handle solve did not converge')


def evaluate(y0, h0, y1, h1, t):
    """Value at fraction ``t`` in [0, 1] between key 0 (value y0, right offset h0)
    and key 1 (value y1, right offset h1)."""
    u = 1.0 - t
    return (u * u * u) * y0 + (3.0 * u * u * t) * (y0 + h0) + (3.0 * u * t * t) * (y1 - h1) + (t * t * t) * y1


def evaluate_track(y, h, idx):
    """Value of the whole track at fractional key index ``idx`` (clamped to the keys)."""
    n = len(y)
    idx = min(max(float(idx), 0.0), float(n - 1))
    k = int(np.floor(idx))
    if k >= n - 1:
        return np.asarray(y[n - 1], dtype=np.float64)
    return evaluate(y[k], h[k], y[k + 1], h[k + 1], idx - k)
