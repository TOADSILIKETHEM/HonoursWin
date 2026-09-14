"""Envelope surface generation from grain positions and radii."""

from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial import QhullError

try:
    from skimage.measure import marching_cubes
except ImportError as exc:
    marching_cubes = None  # type: ignore[assignment]
    _MARCHING_CUBES_IMPORT_ERROR = exc
else:
    _MARCHING_CUBES_IMPORT_ERROR = None


def _orient_faces_outward(
    verts_km: np.ndarray,
    faces: np.ndarray,
    centroid: np.ndarray,
) -> np.ndarray:
    """Flip triangle windings whose normal points back toward ``centroid``.

    Neither qhull nor marching cubes guarantees outward winding, and Blender
    shades from the winding order, so half a surface renders inverted without
    this pass.
    """
    if len(faces) == 0:
        return faces
    tri = verts_km[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    outward = (normals * (tri.mean(axis=1) - centroid)).sum(axis=1) > 0.0
    faces[~outward] = faces[~outward][:, ::-1]
    return faces


def convex_hull_envelope(
    pos_km: np.ndarray,
    radii_km: np.ndarray,
    vis_scale: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """P0 envelope: convex hull of centres inflated radially by max grain radius."""
    if len(pos_km) < 4:
        raise ValueError("convex hull requires at least 4 grains")

    try:
        hull = ConvexHull(pos_km)
    except QhullError:
        # A flat or near-flat fragment (a few grains still on a lattice plane)
        # has no 3-D hull. 'QJ' joggles the input just enough to give one.
        hull = ConvexHull(pos_km, qhull_options="QJ")

    centroid = pos_km.mean(axis=0)
    max_r = float(radii_km.max())

    # hull.vertices compacts the point set; hull.simplices still indexes the
    # *input* array, so the triangles must be remapped into the compact one.
    verts_km = pos_km[hull.vertices]
    remap = np.full(len(pos_km), -1, dtype=np.int64)
    remap[hull.vertices] = np.arange(len(hull.vertices))
    faces = remap[hull.simplices]

    direction = verts_km - centroid
    norm = np.linalg.norm(direction, axis=1, keepdims=True)
    verts_km = verts_km + np.divide(direction, np.where(norm > 1e-12, norm, 1.0)) * max_r

    faces = _orient_faces_outward(verts_km, faces, centroid)
    verts = (verts_km * vis_scale).astype(np.float32)
    return verts, faces.astype(np.uint32)


def sdf_envelope(
    pos_km: np.ndarray,
    radii_km: np.ndarray,
    vis_scale: float,
    *,
    grid_res: int = 48,
    padding_frac: float = 0.15,
    narrow_band_factor: float = 2.5,
) -> Tuple[np.ndarray, np.ndarray]:
    """P2 envelope: sphere-union SDF evaluated on a narrow band, marching cubes."""
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
    axes = (xs, ys, zs)
    scale = (maxs - mins) / max(grid_res - 1, 1)

    voxel_diag = float(np.linalg.norm(scale))
    band = voxel_diag * narrow_band_factor
    query_radius = float(radii_km.max()) + band

    # Narrow-band scatter: each grain only writes the voxels its own influence
    # sphere covers, so cost scales with the grains rather than with grid_res**3.
    # Voxels no grain reaches keep a positive sentinel (outside the surface).
    grid = np.full((grid_res, grid_res, grid_res), query_radius, dtype=np.float32)
    reach = radii_km + band
    lo = np.ceil((pos_km - reach[:, None] - mins) / scale).astype(np.int64)
    hi = np.floor((pos_km + reach[:, None] - mins) / scale).astype(np.int64)
    np.clip(lo, 0, grid_res - 1, out=lo)
    np.clip(hi, 0, grid_res - 1, out=hi)

    for i in range(len(pos_km)):
        (ix0, iy0, iz0), (ix1, iy1, iz1) = lo[i], hi[i]
        if ix0 > ix1 or iy0 > iy1 or iz0 > iz1:
            continue
        dx = axes[0][ix0:ix1 + 1] - pos_km[i, 0]
        dy = axes[1][iy0:iy1 + 1] - pos_km[i, 1]
        dz = axes[2][iz0:iz1 + 1] - pos_km[i, 2]
        # grid is indexed [iz, iy, ix]
        d2 = (dz[:, None, None] ** 2) + (dy[None, :, None] ** 2) + (dx[None, None, :] ** 2)
        block = grid[iz0:iz1 + 1, iy0:iy1 + 1, ix0:ix1 + 1]
        np.minimum(block, np.sqrt(d2) - radii_km[i], out=block)

    try:
        # Our field is negative inside and positive outside, so the exterior is
        # the greater region: 'ascent' is what makes the normals face outward.
        verts_vox, faces, _, _ = marching_cubes(grid, level=0.0, gradient_direction="ascent")
    except (ValueError, RuntimeError):
        return convex_hull_envelope(pos_km, radii_km, vis_scale)

    # marching_cubes returns verts in the array's (z, y, x) index order; reorder
    # the columns to (x, y, z) but keep ``scale`` in its own x/y/z order.
    verts_km = mins + verts_vox[:, [2, 1, 0]] * scale
    faces = _orient_faces_outward(verts_km, faces.astype(np.int64), verts_km.mean(axis=0))
    verts = (verts_km * vis_scale).astype(np.float32)
    return verts, faces.astype(np.uint32)


def build_envelope(
    pos_km: np.ndarray,
    radii_km: np.ndarray,
    vis_scale: float,
    method: str = "hull",
    **kwargs,
) -> Tuple[np.ndarray, np.ndarray]:
    """Build envelope mesh; ``method`` is ``hull`` or ``sdf``."""
    if method == "sdf":
        return sdf_envelope(pos_km, radii_km, vis_scale, **kwargs)
    return convex_hull_envelope(pos_km, radii_km, vis_scale)
