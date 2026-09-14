"""JPL shape-model OBJ loading and BVH-based interior point sampling.

Moved from an exploratory scratchpad script into a reusable module for
viz_preprocess_lite.py's placeholder point-cloud generation. Needs
mathutils.bvhtree, so this module only runs under Blender's bundled Python
-- not the plain Windows venv.
"""

import numpy as np
from mathutils.bvhtree import BVHTree


def load_obj_shape(path):
    """Read an OBJ's vertices and triangle faces (ignores everything else)."""
    verts, faces = [], []
    with open(path) as fh:
        for line in fh:
            if line.startswith('v '):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith('f '):
                tokens = line.split()[1:]
                if len(tokens) != 3:
                    raise ValueError(
                        f'non-triangular face found in OBJ ({len(tokens)} vertices); '
                        f'only triangulated OBJs are supported: {line.strip()!r}'
                    )
                faces.append([int(t.split('/')[0]) - 1 for t in tokens])
    return np.asarray(verts, dtype=np.float64), np.asarray(faces, dtype=np.int32)


def center_and_scale(verts, target_radius):
    """Center on the bounding box and scale so the far-most vertex sits at ``target_radius``.

    Returns ``(scaled_verts, scale_factor)``.
    """
    centre = 0.5 * (verts.min(axis=0) + verts.max(axis=0))
    v = verts - centre
    scale = target_radius / np.linalg.norm(v, axis=1).max()
    return v * scale, scale


def build_bvh(verts, faces):
    return BVHTree.FromPolygons([tuple(v) for v in verts], [tuple(f) for f in faces])


def points_inside_shape(bvh, points):
    """Signed-distance sign test against the closed shell (per-point BVH nearest-face query)."""
    out = np.empty(len(points), dtype=bool)
    for i, p in enumerate(points):
        loc, nrm, _idx, _dist = bvh.find_nearest(tuple(p))
        out[i] = ((p[0] - loc.x) * nrm.x + (p[1] - loc.y) * nrm.y + (p[2] - loc.z) * nrm.z) < 0.0
    return out


def sample_points_in_shape(verts, faces, n_points, seed=0, batch_size=400_000):
    """Rejection-sample ``n_points`` inside the closed shell defined by ``verts``/``faces``.

    ``verts`` must already be in the caller's target units/scale (see
    :func:`center_and_scale`); a winding-inverted mesh (centroid classified
    outside) raises AssertionError.
    """
    bvh = build_bvh(verts, faces)
    if not points_inside_shape(bvh, np.zeros((1, 3)))[0]:
        raise ValueError('winding inverted: centre classified outside')
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    rng = np.random.default_rng(seed)
    kept, got = [], 0
    while got < n_points:
        cand = rng.uniform(lo, hi, size=(batch_size, 3))
        good = cand[points_inside_shape(bvh, cand)]
        kept.append(good)
        got += len(good)
    return np.concatenate(kept)[:n_points].astype(np.float32)
