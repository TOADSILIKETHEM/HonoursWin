"""Earth-fixed and Earth-chase camera framing (pure numpy; used by BlenderConvert/DEMCinematicSetup.py).

The Blender scene is Apophis-centred: Apophis sits at the origin and Earth's
empty is keyed at (earth - apophis) * EARTH_VIS_SCALE. In Earth's frame Apophis
therefore sits at -earth_pos[i]. earth_fixed_pose() picks one camera pose,
relative to Earth's centre, that frames Earth plus Apophis's path, so a camera
parented to the Earth empty with that pose keeps Earth still on screen while
Apophis flies across.
"""
import math

import numpy as np


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else None


def _rotate(v, axis, angle_rad):
    """Rodrigues rotation of v about the unit vector axis."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return v * c + np.cross(axis, v) * s + axis * float(np.dot(axis, v)) * (1.0 - c)


def apophis_path(earth_pos, window_bu=None, window_ca_factor=None):
    """Apophis positions in Earth's frame, optionally only those within window_bu of Earth's centre.

    window_ca_factor (used when window_bu is None) sets the window to that multiple of
    the closest-approach distance. The window always keeps the closest-approach point,
    so it never returns an empty path.
    """
    path = -np.asarray(earth_pos, dtype=np.float64).reshape(-1, 3)
    if len(path) == 0:
        raise ValueError("no Earth positions to frame (bodies CSV has no Earth row?)")
    dist = np.linalg.norm(path, axis=1)
    if window_bu is None and window_ca_factor is not None:
        window_bu = float(window_ca_factor) * float(dist.min())
    if window_bu is None:
        return path
    keep = dist <= float(window_bu)
    keep[int(np.argmin(dist))] = True
    return path[keep]


def orbit_normal(rel):
    """Unit normal of the relative orbit traced by rel (n, 3), from its swept angular momentum.

    A straight radial or one-point path has none, so fall back to any axis
    perpendicular to the closest-approach direction.
    """
    rel = np.asarray(rel, dtype=np.float64).reshape(-1, 3)
    normal = _unit(np.cross(rel[:-1], rel[1:]).sum(axis=0)) if len(rel) > 1 else None
    if normal is not None:
        return normal
    ca_dir = _unit(rel[int(np.argmin(np.linalg.norm(rel, axis=1)))])
    if ca_dir is None:
        return np.array([0.0, 0.0, 1.0])
    normal = _unit(np.cross(ca_dir, [0.0, 0.0, 1.0]))
    return normal if normal is not None else _unit(np.cross(ca_dir, [0.0, 1.0, 0.0]))


def _tan_halves(fov_rad, aspect):
    """tan of the half-angles (across, up) for Blender's FOV on the long side (sensor_fit AUTO)."""
    t = math.tan(0.5 * fov_rad)
    return (t, t / aspect) if aspect >= 1.0 else (t * aspect, t)


def earth_chase_offsets(cores, earth_pos, fov_rad, aspect, *, ref_fov_rad, ref_dist_bu, drop=1.0 / 3.0):
    """Per-frame camera position minus core for the over-the-shoulder chase, and the up axis.

    The camera sits behind Apophis on the Earth line, raised along the orbit normal
    so that, aimed at Earth's centre, Apophis lands `drop` of the half-height below
    the middle (1/3 = lower third). Its distance scales with 1 / tan(fov / 2) from
    ref_dist_bu at ref_fov_rad, so Apophis keeps its screen size and a narrow lens
    only magnifies Earth behind it (telephoto).

    Returns (offsets (n, 3), up (3,)): up = orbit normal, the camera's screen-up.
    """
    cores = np.asarray(cores, dtype=np.float64).reshape(-1, 3)
    rel = np.asarray(earth_pos, dtype=np.float64).reshape(-1, 3) - cores
    up = orbit_normal(rel)
    dist = float(ref_dist_bu) * math.tan(0.5 * ref_fov_rad) / math.tan(0.5 * fov_rad)
    theta = math.atan(_tan_halves(fov_rad, aspect)[1] * float(drop))  # Apophis below the Earth axis
    length = np.linalg.norm(rel, axis=1)
    elev = _chase_elevation(length, dist, theta)
    toward = rel / np.maximum(length, 1e-12)[:, None]
    offsets = (-toward * np.cos(elev)[:, None] + up * np.sin(elev)[:, None]) * dist
    return offsets, up


def _chase_elevation(length, dist, theta):
    """Elevation e (per frame) of the camera above the Earth line such that, aimed at
    Earth (distance `length` from the core), the core sits `theta` below the view axis.

    Angle(core) - angle(Earth) below the line = e - atan(d sin e / (L + d cos e)); it
    rises from below theta at e = theta, so bisect on [theta, 89 deg]. When even 89 deg
    falls short (Earth closer than the camera distance) the camera stops at 89 deg.
    """
    length = np.asarray(length, dtype=np.float64)

    def miss(e):
        return e - np.arctan2(dist * np.sin(e), length + dist * np.cos(e)) - theta

    lo = np.full_like(length, theta)
    hi = np.full_like(length, math.radians(89.0))
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        low = miss(mid) < 0
        lo, hi = np.where(low, mid, lo), np.where(low, hi, mid)
    return 0.5 * (lo + hi)


def earth_fixed_pose(earth_pos, earth_radius_bu, fov_rad, aspect, *, tilt_deg=20.0, margin=1.15,
                     window_bu=None, window_ca_factor=3.0):
    """Camera pose relative to Earth's centre framing Earth and Apophis's path.

    earth_pos: (n, 3) Earth positions in the Apophis-centred scene (BU).
    fov_rad: the camera's FOV across its larger image side (Blender lens_unit 'FOV',
    sensor_fit 'AUTO'); aspect = width / height.
    tilt_deg: the view starts face-on to the orbit plane and tilts this far toward
    the closest-approach point, so Apophis passes in front of Earth, not behind.
    window_bu / window_ca_factor: frame only the path near Earth (see apophis_path);
    the default 3 x closest approach, since a hyperbola run starts 4e5 km out and a
    whole-path frame leaves Apophis under a pixel. window_ca_factor=None = whole path.

    Returns (offset, right, up): offset is the camera position minus Earth's centre;
    right / up are the camera's local +X / +Y in world axes (it looks along up x right).
    """
    path = apophis_path(earth_pos, window_bu, window_ca_factor)
    ca = path[int(np.argmin(np.linalg.norm(path, axis=1)))]
    ca_dir = _unit(ca)
    if ca_dir is None:
        ca_dir = np.array([1.0, 0.0, 0.0])

    normal = orbit_normal(path)
    # back = from the scene toward the camera (camera local +Z)
    tilt_axis = _unit(np.cross(normal, ca_dir))
    back = normal if tilt_axis is None else _rotate(normal, tilt_axis, math.radians(tilt_deg))
    back = _unit(back)

    # Long side of the frame along the path's chord (fits 16:9 to a flyby).
    chord = path[-1] - path[0]
    right = _unit(chord - back * float(np.dot(chord, back)))
    if right is None:
        right = _unit(np.cross([0.0, 0.0, 1.0], back)) if abs(back[2]) < 0.99 else np.array([1.0, 0.0, 0.0])
        right = _unit(right - back * float(np.dot(right, back)))
    up = np.cross(back, right)

    # Points to keep in view: the path, plus Earth's limb in the image plane.
    r = float(earth_radius_bu)
    pts = np.vstack([path, r * right, -r * right, r * up, -r * up])
    xs, ys = pts @ right, pts @ up
    cx, cy = 0.5 * (xs.min() + xs.max()), 0.5 * (ys.min() + ys.max())
    centre = cx * right + cy * up

    tan_x, tan_y = _tan_halves(fov_rad, aspect)
    rel = pts - centre
    depth = rel @ back  # > 0: nearer the camera than the aim plane
    lat_x, lat_y = np.abs(rel @ right) * margin, np.abs(rel @ up) * margin
    # A point at depth d and lateral offset l fits when l / (dist - d) <= tan(half fov).
    # Earth's near side (depth r) must also stay in front of the camera.
    dist = max(float(np.max(depth + lat_x / tan_x)), float(np.max(depth + lat_y / tan_y)), 2.0 * r)
    return centre + back * dist, right, up
