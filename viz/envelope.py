"""Envelope surface generation from grain positions and radii."""

from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy.spatial import ConvexHull, cKDTree

try:
    from skimage.measure import marching_cubes
except ImportError as exc:
    marching_cubes = None  # type: ignore[assignment]
    _MARCHING_CUBES_IMPORT_ERROR = exc
else:
    _MARCHING_CUBES_IMPORT_ERROR = None


def convex_hull_envelope(
    pos_km: np.ndarray,
    radii_km: np.ndarray,
    vis_scale: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """P0 envelope: convex hull of centres inflated radially by max grain radius."""
    if len(pos_km) < 4:
        raise ValueError("convex hull requires at least 4 grains")

    hull = ConvexHull(pos_km)
    centroid = pos_km.mean(axis=0)
    max_r = float(radii_km.max())
    verts_km = pos_km[hull.vertices].copy()
    for i, v in enumerate(verts_km):
        direction = v - centroid
        norm = float(np.linalg.norm(direction))
        if norm > 1e-12:
            verts_km[i] = v + (direction / norm) * max_r
        else:
            verts_km[i] = v + max_r

    verts = (verts_km * vis_scale).astype(np.float32)
    faces = hull.simplices.astype(np.uint32)
    return verts, faces


def sdf_envelope_kdtree(
    pos_km: np.ndarray,
    radii_km: np.ndarray,
    vis_scale: float,
    *,
    grid_res: int = 48,
    padding_frac: float = 0.15,
    narrow_band_factor: float = 2.5,
) -> Tuple[np.ndarray, np.ndarray]:
    """P2 envelope: sphere-union SDF with KD-tree narrow-band evaluation."""
    if marching_cubes is None:
        raise ImportError(
            "scikit-image is required for SDF envelopes"
        ) from _MARCHING_CUBES_IMPORT_ERROR
    if len(pos_km) < 4:
        return convex_hull_envelope(pos_km, radii_km, vis_scale)

    mins = pos_km.min(axis=0) - radii_km.max()
    maxs = pos_km.max(axis=0) + radii_km.max()
    extent = maxs - mins
    pad = extent * padding_frac + radii_km.max()
    mins -= pad
    maxs += pad

    xs = np.linspace(mins[0], maxs[0], grid_res)
    ys = np.linspace(mins[1], maxs[1], grid_res)
    zs = np.linspace(mins[2], maxs[2], grid_res)
    grid = np.zeros((grid_res, grid_res, grid_res), dtype=np.float32)

    tree = cKDTree(pos_km)
    r_max = float(radii_km.max())
    voxel_diag = float(np.linalg.norm(np.array([
        (maxs[0] - mins[0]) / max(grid_res - 1, 1),
        (maxs[1] - mins[1]) / max(grid_res - 1, 1),
        (maxs[2] - mins[2]) / max(grid_res - 1, 1),
    ])))
    query_radius = r_max + voxel_diag * narrow_band_factor

    for iz, z in enumerate(zs):
        for iy, y in enumerate(ys):
            for ix, x in enumerate(xs):
                p = np.array([x, y, z])
                nearby_idx = tree.query_ball_point(p, query_radius)
                if not nearby_idx:
                    grid[iz, iy, ix] = 1.0
                    continue
                pts = pos_km[nearby_idx]
                rs = radii_km[nearby_idx]
                dists = np.linalg.norm(pts - p, axis=1) - rs
                grid[iz, iy, ix] = float(dists.min())

    try:
        verts_vox, faces, _, _ = marching_cubes(grid, level=0.0)
    except ValueError:
        return convex_hull_envelope(pos_km, radii_km, vis_scale)

    # Voxel indices → world km
    scale = (maxs - mins) / max(grid_res - 1, 1)
    verts_km = mins + verts_vox[:, [2, 1, 0]] * scale[[2, 1, 0]]
    verts = (verts_km * vis_scale).astype(np.float32)
    faces = faces.astype(np.uint32)
    return verts, faces


def build_envelope(
    pos_km: np.ndarray,
    radii_km: np.ndarray,
    vis_scale: float,
    method: str = "hull",
    **kwargs,
) -> Tuple[np.ndarray, np.ndarray]:
    """Build envelope mesh; ``method`` is ``hull`` or ``sdf``."""
    if method == "sdf":
        return sdf_envelope_kdtree(pos_km, radii_km, vis_scale, **kwargs)
    return convex_hull_envelope(pos_km, radii_km, vis_scale)
