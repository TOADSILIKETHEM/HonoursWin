#!/usr/bin/env python3
"""Preprocess a placeholder point cloud into a bulk instancing manifest (Option A).

Rejection-samples a shape OBJ into a static million-point cloud, scaled and
sized from a real run's grain npz / bodies CSV files, and writes a `viz_mode: "instance"`
manifest that DEMBulkInstanceBlender.py consumes exactly as
DEMBulkVizBlender.py consumes a `viz_mode: "composite"` manifest.

Runs under Blender's bundled Python (needs mathutils.bvhtree via
viz/shape_sampling.py), not the plain venv:

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --background --python viz/viz_preprocess_lite.py -- \\
        --grains-dir DEMCSVs/torque_align_obj/run_0001_grains_output \\
        --bodies-dir DEMCSVs/torque_align_obj/run_0001_bodies_output \\
        --output-dir DEMCSVs/torque_align_obj/run_0001_viz_instance \\
        --shape-obj "BlenderConvert/Shapes/.../apophis_v233s7.obj" \\
        --n-points 1000000

Real per-frame million-grain ingestion (`static: false`) is not
implemented -- deferred until such simulation data exists.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from viz.path_utils import manifest_relpath  # noqa: E402
from viz.shape_sampling import (  # noqa: E402
    center_and_scale,
    load_obj_shape,
    sample_points_in_shape,
)


def _blender_argv(argv):
    """Strip Blender's own args, returning everything after the ``--`` separator."""
    if '--' in argv:
        return argv[argv.index('--') + 1:]
    return argv[1:]


def reference_scale_from_run(grains_dir):
    """(reference_cluster_radius_bu, reference_grain_radius_bu, reference_n) from frame 1.

    Cluster radius is the frame-1 grains' max distance from the origin in
    x_vis/y_vis/z_vis (already Apophis-CoM-centered, per the grains npz
    convention); grain radius is the mean of Reff_vis -- uniform per run in
    practice, mean guards against float noise.
    """
    grains_dir = Path(grains_dir)
    files = sorted(glob.glob(str(grains_dir / '*.npz')))
    if not files:
        raise FileNotFoundError(
            f'No grain npz files in {grains_dir} (CSV-era folder? re-run DEMDumpConvert.py)'
        )
    d = np.load(files[0])
    for key in ('x_vis', 'y_vis', 'z_vis', 'Reff_vis'):
        if key not in d.files:
            raise ValueError(f'{files[0]} missing required key {key!r}')
    pts = np.column_stack([d['x_vis'], d['y_vis'], d['z_vis']]).astype(np.float64)
    cluster_radius = float(np.linalg.norm(pts, axis=1).max())
    grain_radius = float(d['Reff_vis'].mean())
    return cluster_radius, grain_radius, len(d['Reff_vis'])


def grain_radius_for(n_points, ref_n, ref_grain_radius_vis):
    """Volume-conserving grain radius at ``n_points``, anchored on the run's own reference."""
    return ref_grain_radius_vis * (ref_n / float(n_points)) ** (1.0 / 3.0)


def run_preprocess_lite(
    grains_dir,
    bodies_dir,
    output_dir,
    shape_obj,
    n_points,
    *,
    sim_name=None,
    run_name=None,
    seed=0,
):
    grains_dir = Path(grains_dir).resolve()
    bodies_dir = Path(bodies_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if run_name is None:
        name = grains_dir.name
        run_name = name.replace('_grains_output', '') if name.endswith('_grains_output') else name
    if sim_name is None:
        sim_name = grains_dir.parent.name

    cluster_radius, grain_radius, ref_n = reference_scale_from_run(grains_dir)
    print(f'reference: cluster_radius={cluster_radius:.4f} BU '
          f'grain_radius={grain_radius:.4f} BU (n={ref_n}, run={run_name})')

    if not Path(shape_obj).is_file():
        raise FileNotFoundError(f'shape OBJ not found: {shape_obj}')
    verts, faces = load_obj_shape(str(shape_obj))
    verts, scale = center_and_scale(verts, cluster_radius)
    print(f'shape: {len(verts)} verts scaled by {scale:.6f} to fit cluster_radius')

    pos = sample_points_in_shape(verts, faces, n_points, seed=seed)
    points_path = output_dir / 'points.npz'
    np.savez_compressed(points_path, pos=pos)
    print(f'wrote {len(pos):,} points -> {points_path}')

    grain_radius_vis = grain_radius_for(n_points, ref_n, grain_radius)

    bodies_csvs = sorted(glob.glob(str(bodies_dir / '*.csv')))
    frame_ids = [f'{i:05d}' for i in range(len(bodies_csvs))]

    rel_bodies = manifest_relpath(bodies_dir, output_dir)
    manifest = {
        'schema_version': 1,
        'viz_mode': 'instance',
        'sim_name': sim_name,
        'run_name': run_name,
        'n_frames': len(frame_ids),
        'frame_ids': frame_ids,
        'bodies_csv_dir': rel_bodies,
        'static': True,
        'points_path': 'points.npz',
        'grain_radius_vis': grain_radius_vis,
        'n_points': n_points,
        'reference_cluster_radius_vis': cluster_radius,
        'reference_grain_radius_vis': grain_radius,
        'reference_n': ref_n,
        'shape_obj': Path(shape_obj).resolve().as_posix(),
    }
    manifest_path = output_dir / 'manifest.json'
    with open(manifest_path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2)
    print(f'Wrote manifest -> {manifest_path}')
    return manifest_path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--grains-dir', type=Path, required=True)
    p.add_argument('--bodies-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--shape-obj', type=Path, required=True)
    p.add_argument('--n-points', type=int, default=1_000_000)
    p.add_argument('--sim-name', type=str, default=None)
    p.add_argument('--run-name', type=str, default=None)
    p.add_argument('--seed', type=int, default=0)
    args = p.parse_args(_blender_argv(sys.argv))

    print(f'viz_preprocess_lite: {args.grains_dir} + {args.shape_obj} -> {args.output_dir}')
    run_preprocess_lite(
        args.grains_dir, args.bodies_dir, args.output_dir, args.shape_obj,
        args.n_points, sim_name=args.sim_name, run_name=args.run_name, seed=args.seed,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
