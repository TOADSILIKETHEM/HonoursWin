"""Starburst and ghost kernels for the Sun glare, from one imperfect 7-blade iris.

Imported by DEMHeadlessRender.apply_sun_glare (Blender's numpy, no scipy). The PSF of
an aperture is |FFT(pupil)|^2 (Fraunhofer). A regular iris gives perfectly symmetric
spikes, so the pupil is a "dirty aperture" as in physically based flare rendering
(Hullin et al. 2011; Flare7K, arXiv 2210.06570; PBFG, ICCV 2025): per-blade angle and
apothem scatter, an off-centre iris, curved blades, rough edges, dust and scratches.
Odd blade count n gives 2n spikes. Seeded, so every render gets the same kernel.

PSF_OPTIONS = variant "J5" of the flare sweep Max picked (2026-10-21).

Ghosts (ghost_passes) are out-of-focus images of the same iris, from pairs of internal
reflections. In a centred lens each lies on the line Sun -> frame centre at
c + k (sun - c), k fixed per ghost, so they swing rigidly with the Sun. Blender's own
Ghosts glare is evenly spaced round discs; GHOSTS is set "gA" of the ghost sweep
(Max, 2026-10-21): 7 ghosts of uneven position, size, shape, colour and brightness.
"""
from functools import lru_cache

import numpy as np

DEFAULTS = dict(n=7, seed=1, m=4096, a=640.0, crop=1023, rot_deg=0.0, jitter_deg=0.0,
                jitter_apothem=0.0, centre_px=0.0, curve=0.0, rough=0.0, dust=0,
                dust_r=(2.0, 12.0), scratches=0, scratch_w=1.5)
PSF_OPTIONS = dict(seed=5, rot_deg=11.0, jitter_deg=6.0, jitter_apothem=0.1, centre_px=8.0,
                   curve=12.0, rough=0.002, dust=120, scratches=3)
# Summed per channel: R 600-680, G 500-580, B 420-490 nm, 9 wavelengths each.
BANDS_NM = ((600, 680), (500, 580), (420, 490))
WAVELENGTHS_PER_BAND = 9
REF_NM = 550.0


def pupil(o, rng):
    """Aperture mask (m x m float32), radius ~a px. Blade geometry is drawn from rng."""
    m, n, a = o["m"], o["n"], o["a"]
    y, x = np.mgrid[:m, :m].astype(np.float32) - m / 2 + 0.5
    ang = (np.deg2rad(o["rot_deg"]) + 2 * np.pi * np.arange(n) / n
           + np.deg2rad(o["jitter_deg"]) * rng.standard_normal(n))
    apo = 1 + o["jitter_apothem"] * rng.standard_normal(n)
    cx, cy = o["centre_px"] * rng.standard_normal(2)
    # Edge roughness: 12 random sinusoids along each blade edge (wavelengths 8..120 px).
    waves = [(rng.uniform(8, 120, 12), rng.uniform(0, 2 * np.pi, 12), rng.standard_normal(12))
             for _ in range(n)]
    dust = [(rng.uniform(-1, 1, 2), np.exp(rng.uniform(*np.log(o["dust_r"]))))
            for _ in range(o["dust"])]
    scratches = [(rng.uniform(-0.7, 0.7, 2), rng.uniform(0, np.pi), rng.uniform(0.15, 0.6))
                 for _ in range(o["scratches"])]

    inside = np.ones((m, m), bool)
    px, py = x - cx, y - cy
    grid = np.arange(-m, m + 1, dtype=np.float32)
    for k in range(n):
        nx, ny = np.cos(ang[k]), np.sin(ang[k])
        edge = a * apo[k]
        if o["rough"]:
            lam, ph, amp = waves[k]
            table = (amp[:, None] * np.sin(2 * np.pi * grid[None] / lam[:, None]
                                           + ph[:, None])).sum(0) / np.sqrt(12)
            along = -px * ny + py * nx
            edge = edge * (1 + o["rough"] * np.interp(along, grid, table).astype(np.float32))
        if o["curve"]:
            rc = o["curve"] * a
            off = a * apo[k] - rc
            inside &= np.hypot(px - nx * off, py - ny * off) <= rc + (edge - a * apo[k])
        else:
            inside &= px * nx + py * ny <= edge
    for c, r in dust:
        i0, j0 = int(m / 2 + cy + c[1] * a), int(m / 2 + cx + c[0] * a)
        R = int(r) + 2
        sy, sx = slice(max(i0 - R, 0), i0 + R + 1), slice(max(j0 - R, 0), j0 + R + 1)
        inside[sy, sx] &= np.hypot(px[sy, sx] - c[0] * a, py[sy, sx] - c[1] * a) > r
    for c, th, half in scratches:
        tx, ty = np.cos(th), np.sin(th)
        dx, dy = px - c[0] * a, py - c[1] * a
        t = dx * tx + dy * ty
        d = np.abs(-dx * ty + dy * tx - 0.0008 * t ** 2 / a)  # slight bow
        inside &= ~((d < o["scratch_w"] / 2) & (np.abs(t) < half * a))
    return inside.astype(np.float32)


@lru_cache(maxsize=1)
def _iris_pupil():
    o = dict(DEFAULTS, **PSF_OPTIONS)
    return pupil(o, np.random.default_rng(o["seed"]))


def _bilinear(img, yy, xx):
    """img sampled at float pixel coords (yy, xx), zero outside (scipy map_coordinates order=1)."""
    h, w = img.shape
    y0, x0 = np.floor(yy).astype(np.int64), np.floor(xx).astype(np.int64)
    fy, fx = yy - y0, xx - x0
    out = np.zeros(yy.shape)
    for dy, wy in ((0, 1 - fy), (1, fy)):
        for dx, wx in ((0, 1 - fx), (1, fx)):
            yi, xi = y0 + dy, x0 + dx
            ok = (yi >= 0) & (yi < h) & (xi >= 0) & (xi < w)
            out += np.where(ok, img[np.clip(yi, 0, h - 1), np.clip(xi, 0, w - 1)], 0.0) * wy * wx
    return out


def starburst_psf(**overrides):
    """(crop, crop, 3) float32 RGB PSF, each channel summing to 1, cosine-tapered to the edge.

    One FFT at REF_NM; the PSF at wavelength lam is that one stretched by lam / REF_NM
    with energy kept (x s^2), so colour fringes scale physically.
    """
    o = dict(DEFAULTS, **PSF_OPTIONS)
    o.update(overrides)
    m, crop = o["m"], o["crop"]
    p = pupil(o, np.random.default_rng(o["seed"])) if overrides else _iris_pupil()
    ref = np.fft.fftshift(np.abs(np.fft.fft2(p.astype(np.complex64))) ** 2).astype(np.float64)
    ref /= ref.sum()
    h = crop // 2
    ry, rx = np.mgrid[-h:h + 1, -h:h + 1].astype(np.float64)
    rr = np.clip((np.hypot(rx, ry) / h - 0.6) / 0.4, 0, 1)
    taper = 0.5 * (1 + np.cos(np.pi * rr))
    psf = np.zeros((crop, crop, 3), np.float32)
    for c, (lo, hi) in enumerate(BANDS_NM):
        acc = np.zeros((crop, crop))
        for lam in np.linspace(lo, hi, WAVELENGTHS_PER_BAND):
            s = REF_NM / lam
            acc += _bilinear(ref, ry * s + m / 2, rx * s + m / 2) * s ** 2
        acc *= taper
        psf[..., c] = acc / acc.sum()
    return psf


# Sun flux above the glare threshold (100) in mia_full_B_s1_cb_x0.7/run_0001 frames 5-6
# (sum of radiance - 100 over the disk, ~200 px). Sets ghost strengths for a target
# surface brightness; the convolution scales with the actual flux each frame.
GHOST_FLUX_REF = 2.3e7
_AMBER, _GREEN, _MAGENTA, _CYAN, _VIOLET = ((1.0, 0.72, 0.38), (0.5, 1.0, 0.6), (1.0, 0.5, 0.9),
                                            (0.5, 0.85, 1.0), (0.75, 0.55, 1.0))
# k (position on the Sun-centre line), radius px at 1080p, shape, tint (lens-coating colours),
# surface brightness (scene-linear), chroma (R/B size split: colour-fringed edges).
# Ghosts near the centre (small |k|) are kept small so Apophis stays clear.
GHOSTS = (
    (-1.30, 85, "iris_soft", _AMBER, 0.025, 0.04),
    (-0.75, 22, "iris", _GREEN, 0.10, 0.03),
    (-0.52, 46, "ring", _MAGENTA, 0.04, 0.05),
    (-0.33, 10, "disc", _CYAN, 0.12, 0.02),
    (0.38, 30, "iris", _VIOLET, 0.06, 0.04),
    (0.62, 14, "iris_soft", _GREEN, 0.08, 0.03),
    (1.45, 40, "disc", _AMBER, 0.03, 0.05),
)
# Edge blur (Gaussian sigma / radius) per shape: defocus differs between ghosts.
_GHOST_SOFTNESS = {"iris": 0.015, "disc": 0.04, "ring": 0.02, "iris_soft": 0.08}


def _resize(img, factor):
    """Bilinear resize by factor, corners aligned (scipy.ndimage.zoom order=1)."""
    n_in = np.array(img.shape)
    n_out = np.maximum(np.round(n_in * factor).astype(int), 1)
    step = (n_in - 1) / np.maximum(n_out - 1, 1)
    yy, xx = np.meshgrid(np.arange(n_out[0]) * step[0], np.arange(n_out[1]) * step[1],
                         indexing="ij")
    return _bilinear(img, yy, xx)


def _gaussian_blur(img, sigma):
    if sigma <= 0:
        return img
    r = int(4 * sigma + 0.5)
    g = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    g /= g.sum()
    img = np.apply_along_axis(np.convolve, 0, img, g, mode="same")
    return np.apply_along_axis(np.convolve, 1, img, g, mode="same")


def _ghost_shape(kind, R):
    """(n, n) mask of radius ~R px: the iris (sharp, soft or bright-rimmed ring) or a disc."""
    n = int(2 * R * 1.25) | 1
    yy, xx = np.mgrid[:n, :n] - n // 2
    rho = np.hypot(yy, xx) / R
    if kind == "disc":
        m = (rho <= 1).astype(float)
    else:
        p = _iris_pupil()
        ys, xs = np.nonzero(p > 0.5)
        cy, cx = int(ys.mean()), int(xs.mean())
        half = int(max(np.ptp(ys), np.ptp(xs)) / 2) + 8
        z = _resize(p[cy - half:cy + half + 1, cx - half:cx + half + 1],
                    2 * R / (2 * DEFAULTS["a"]))
        m = np.zeros((n, n))
        o = (n - z.shape[0]) // 2
        if o >= 0:
            m[o:o + z.shape[0], o:o + z.shape[0]] = z
        else:
            m = z[-o:-o + n, -o:-o + n]
        if kind == "ring":
            m = m * (0.25 + 0.75 * np.clip(rho, 0, 1) ** 6)
    return np.clip(_gaussian_blur(m, _GHOST_SOFTNESS[kind] * R), 0, None)


def _ghost_kernel(kind, R, chroma):
    """(n, n, 3) float32, each channel summing to 1; red drawn larger, blue smaller."""
    base = _ghost_shape(kind, R)
    n = base.shape[0]
    out = np.zeros((n, n, 3), np.float32)
    for c, s in enumerate((1 + chroma, 1.0, 1 - chroma)):
        ch = _resize(base, s)
        m = ch.shape[0]
        if m >= n:
            o = (m - n) // 2
            ch = ch[o:o + n, o:o + n]
        else:
            o = (n - m) // 2
            ch = np.pad(ch, ((o, n - m - o), (o, n - m - o)))
        out[..., c] = ch / ch.sum()
    return out


def ghost_passes():
    """One dict per GHOSTS entry: kernel (n, n, 3), strength, tint (r, g, b), scale |k|, angle.

    Convolve the thresholded image with kernel (Kernel glare at strength, tinted), then
    scale by |k| about the frame centre and rotate pi when k < 0. The kernel radius is
    r / |k| so the placed ghost is r px; strength gives the target surface brightness
    for GHOST_FLUX_REF (a unit-sum kernel spreads the flux over its area).
    """
    passes = []
    for k, r, kind, tint, bright, chroma in GHOSTS:
        ker = _ghost_kernel(kind, r / abs(k), chroma)
        area = int((ker[..., 1] > 0.5 * ker[..., 1].max()).sum())
        passes.append(dict(kernel=ker, strength=bright * area / GHOST_FLUX_REF, tint=tint,
                           scale=abs(k), angle=float(np.pi) if k < 0 else 0.0))
    return passes
