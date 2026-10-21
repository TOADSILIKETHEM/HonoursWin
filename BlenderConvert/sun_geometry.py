"""Real 2029 Sun geometry for hyperbola flyby renders (pure Python + numpy, no bpy).

Imported by the Blender scripts that place the Sun in hyperbola runs, tested by
tests/test_sun_geometry.py. Regenerate the constants with regen_sun_constants.py.

Frames:
  J2000     = Horizons "Ecliptic of J2000.0", geocentric (CENTER='500@399').
  pericentre = real orbit frame of Apophis about Earth at closest approach:
              x = unit(r), z = unit(r cross v), y = z cross x (r, v at pericentre).
  scene     = Blender axes of a hyperbola run (Apophis-centred); its mapping to the
              pericentre frame comes from the data, not from this module.

Provenance: JPL Horizons API, VECTORS, CENTER='500@399', REF_PLANE='ECLIPTIC',
km and km/s, queried 2026-10-20. Closest approach 2029-04-13 21:46:00 TDB at
38,011 km: Apophis (99942) geocentric r, v there, and the geocentric Sun
direction there (command '10').

Sun disk: the real angular radius at that date (asin(R_sun / d_sun) = 0.2657 deg;
0.2666 deg is the 1 AU mean). The Sun turns once round the ecliptic per year
(about 0.9856 deg/day) as seen from Earth; over a flyby that is the only motion.
"""

import csv
import glob
import math
import os
from dataclasses import dataclass

import numpy as np

import earth_orientation

# --- Constants (regenerate with regen_sun_constants.py) ---------------------------
# Epoch string parseable by earth_orientation.julian_date.
CA_EPOCH_TDB = '2029-04-13 21:46:00'
# Apophis geocentric position (km) and velocity (km/s) at closest approach, J2000 ecliptic.
R_CA_KM = (-19187.2234811485, 32258.7096137982, 6007.9605574541)
V_CA_KMS = (6.3321929251, 3.4051973509, 1.8444680692)
# Geocentric unit vector to the Sun at closest approach, J2000 ecliptic.
SUN_CA_UNIT = (0.9147059482, 0.4041200656, -0.0000295845)
SUN_DISTANCE_CA_KM = 150035116.9
SUN_RADIUS_KM = 695700.0
SUN_ANGULAR_RADIUS_RAD = math.asin(SUN_RADIUS_KM / SUN_DISTANCE_CA_KM)
# Sidereal year: apparent geocentric Sun motion about the ecliptic pole.
SUN_ECLIPTIC_RATE_RAD_S = 2 * math.pi / (365.256363 * 86400.0)

# Bodies CSV `m` is in solar masses.
GM_SUN_KM3_S2 = 1.32712440018e11

# --- Scene placement and look -----------------------------------------------------
# Inside CAM_CLIP_END (2e7 BU); parallax from the earth_fixed camera at ~8e4 BU is
# <= 0.3 deg, accepted.
SUN_VISUAL_DISTANCE_BU = 1.5e7
# Makes the disk's radiance the one that would deliver the lamp's irradiance:
# L = E / (pi * a^2). Measured in Cycles 5.2.1 (tests/test_sun_render.py, 2026-10-20):
# a white Lambertian plane under a strength-10 sun lamp renders 3.1831 = 10 / pi,
# a strength-1 emitter renders 1, so the constant is 1 / pi (measured 0.31831).
SUN_EMISSION_CALIBRATION = 1.0 / math.pi
# Legibility knob: scales the disk's brightness without touching the lamp.
SUN_DISK_BRIGHTNESS_SCALE = 1.0


def _unit(v):
    v = np.asarray(v, dtype=float)
    norm = np.linalg.norm(v)
    if not norm > 0.0 or not math.isfinite(norm):
        raise ValueError('cannot normalise a zero-length or non-finite vector')
    return v / norm


def pericentre_frame(r, v):
    """3x3 rotation whose rows are x = unit(r), y = z cross x, z = unit(r cross v).

    ``F @ vec`` takes a J2000 vector into the pericentre frame.
    """
    x = _unit(r)
    z = _unit(np.cross(r, v))
    y = np.cross(z, x)
    return np.array([x, y, z])


def sun_direction_j2000(dt_s):
    """Geocentric unit vector to the Sun, ``dt_s`` seconds after closest approach.

    ``SUN_CA_UNIT`` rotated about +z (the ecliptic pole) by the Sun's mean motion.
    """
    a = SUN_ECLIPTIC_RATE_RAD_S * dt_s
    c, s = math.cos(a), math.sin(a)
    x, y, z = SUN_CA_UNIT
    return np.array([c * x - s * y, s * x + c * y, z])


def sun_visual_radius_bu():
    """Radius of the Sun sphere at ``SUN_VISUAL_DISTANCE_BU`` that subtends the true angular radius."""
    return SUN_VISUAL_DISTANCE_BU * math.tan(SUN_ANGULAR_RADIUS_RAD)


def sun_visual_location(direction):
    """Sun sphere location (Apophis-centred scene) along ``direction``.

    Raises ValueError for a zero-length direction; callers skip that frame's key.
    """
    return tuple(float(c) for c in SUN_VISUAL_DISTANCE_BU * _unit(direction))


def sun_disk_emission_strength(lamp_irradiance):
    """Emission strength for the Sun sphere, proportional to the sun lamp's irradiance.

    Radiance scales as irradiance / (angular radius)^2 for a small disk;
    ``SUN_EMISSION_CALIBRATION`` (1 / pi, measured) completes L = E / (pi * a^2).
    """
    return (SUN_EMISSION_CALIBRATION * lamp_irradiance
            / SUN_ANGULAR_RADIUS_RAD ** 2 * SUN_DISK_BRIGHTNESS_SCALE)


@dataclass(frozen=True)
class HyperbolaFrame:
    """Orbit of a hyperbola run, fitted from its bodies CSVs.

    ``rotation`` takes J2000 ecliptic vectors into the scene (Apophis-centred
    Blender axes); ``t_ca_sim_s`` is the sim time of closest approach.
    """
    rotation: np.ndarray
    t_ca_sim_s: float
    rp_km: float
    ecc: float


def fit_hyperbola_frame(times_s, rel_km, mu_km3_s2):
    """Fit the Kepler hyperbola of Apophis about Earth; None with fewer than 3 frames or a degenerate orbit.

    Degenerate means stationary or collinear positions, mu <= 0, or a near-parabolic
    fit whose closest-approach time or rotation is not finite.

    ``rel_km`` is Apophis - Earth, shape (n, 3), time-ordered. The conic
    ``|r| = p - ex (r.u) - ey (r.w)`` is linear in (p, ex, ey), so no
    pericentre sample is needed; the sense of travel sets the plane normal's
    sign. Closest-approach time is the mean of ``t_i - M_i / n`` over the samples.
    The rotation maps the real pericentre frame onto the fitted orbit axes, so
    the real 2029 Sun and Earth orientation follow the run's own geometry.
    """
    t = np.asarray(times_s, dtype=float)
    r = np.asarray(rel_km, dtype=float)
    if len(t) < 3 or not mu_km3_s2 > 0.0:
        return None
    try:
        z = _unit(np.cross(r[:-1], r[1:]).sum(axis=0))
        u = _unit(r[0] - (r[0] @ z) * z)
        w = np.cross(z, u)
        mag = np.linalg.norm(r, axis=1)
        A = np.column_stack([np.ones(len(r)), -(r @ u), -(r @ w)])
        p, ex, ey = np.linalg.lstsq(A, mag, rcond=None)[0]
        ecc = math.hypot(ex, ey)
        if ecc <= 1.0 or p <= 0.0:
            return None
        x_sim = _unit(ex * u + ey * w)
        y_sim = np.cross(z, x_sim)
        a = p / (1.0 - ecc * ecc)
        n = math.sqrt(mu_km3_s2 / abs(a) ** 3)
        theta = np.arctan2(r @ y_sim, r @ x_sim)
        F = 2.0 * np.arctanh(math.sqrt((ecc - 1.0) / (ecc + 1.0)) * np.tan(theta / 2.0))
        M = ecc * np.sinh(F) - F
        t_ca = float(np.mean(t - M / n))
        S = np.array([x_sim, y_sim, z])
        rotation = S.T @ pericentre_frame(R_CA_KM, V_CA_KMS)
        rp = float(p / (1.0 + ecc))
        if not (math.isfinite(t_ca) and math.isfinite(rp)
                and math.isfinite(ecc) and np.isfinite(rotation).all()):
            return None
        return HyperbolaFrame(rotation=rotation, t_ca_sim_s=t_ca, rp_km=rp, ecc=float(ecc))
    except (np.linalg.LinAlgError, ValueError, ZeroDivisionError):
        return None


def hyperbola_frame_from_bodies_dir(bodies_dir):
    """Fit the frame from every ``*.csv`` in a run's bodies dir (not just a render window).

    None for ephemeris runs (a ``Sun`` row in the first CSV), ``apophis_only`` runs
    (no ``Earth`` row), runs with fewer than 3 frames holding both bodies, and degenerate orbits.
    mu is Earth's ``m`` (solar masses) times ``GM_SUN_KM3_S2``.
    """
    files = sorted(glob.glob(os.path.join(bodies_dir, '*.csv')))
    times, rel, mu = [], [], None
    for i, path in enumerate(files):
        with open(path, newline='') as f:
            rows = {row['name']: row for row in csv.DictReader(f)}
        if i == 0 and ('Sun' in rows or 'Earth' not in rows):
            return None
        if 'Earth' not in rows or 'Apophis' not in rows:
            continue
        e, a = rows['Earth'], rows['Apophis']
        times.append(float(a['time_s']))
        rel.append([float(a[k]) - float(e[k]) for k in ('x_km', 'y_km', 'z_km')])
        mu = float(e['m']) * GM_SUN_KM3_S2
    if len(times) < 3:
        return None
    return fit_hyperbola_frame(times, np.array(rel), mu)


def sun_direction_scene(frame, time_s):
    """Unit vector to the Sun in the scene at sim time ``time_s``."""
    return frame.rotation @ sun_direction_j2000(time_s - frame.t_ca_sim_s)


def matrix_to_quaternion(m):
    """(w, x, y, z) with w >= 0 for a 3x3 rotation matrix."""
    m = np.asarray(m, dtype=float)
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0.0:
        s = 2.0 * math.sqrt(tr + 1.0)
        q = (0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s)
    elif m[0, 0] >= m[1, 1] and m[0, 0] >= m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        q = ((m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s)
    elif m[1, 1] >= m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        q = ((m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s)
    else:
        s = 2.0 * math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        q = ((m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s)
    if q[0] < 0.0:
        q = tuple(-c for c in q)
    return tuple(float(c) for c in q)


def earth_quaternion_scene(frame, time_s):
    """(w, x, y, z) rotating Earth-fixed vectors into the scene at sim time ``time_s``.

    The real 2029 Earth orientation (J2000 ecliptic, no sim frame offset) at
    ``time_s - t_ca_sim_s`` after closest approach, carried into the scene by
    ``frame.rotation``.
    """
    q_ecl = earth_orientation.earth_quaternion(time_s - frame.t_ca_sim_s, CA_EPOCH_TDB,
                                               frame_rotation_deg=0.0)
    return earth_orientation._quat_mul(matrix_to_quaternion(frame.rotation), q_ecl)
