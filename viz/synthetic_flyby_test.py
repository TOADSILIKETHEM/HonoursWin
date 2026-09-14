#!/usr/bin/env python3
"""Synthetic 'moving instance cloud' test manifest -- a stand-in for real 1M-particle
PHANTOM output, until such a simulation actually exists.

Reuses viz_preprocess_lite.py's shape sampling (same static rigid-body point cloud,
same volume-conserving grain radius) but writes one points file *per frame*, each a
rigid rotation of the base shape, and sets ``static: false``. This is what exercises
the DEMBulkInstanceBlender.py per-frame loading path (_instance_frame_change_handler)
end-to-end before any real per-frame DEM data is available.

The rotation is a synthetic rigid tumble -- a single axis and period, not real
per-grain physics -- so the manifest carries ``"synthetic": true`` and
``motion_model: "rigid_tumble"`` to make that unambiguous to any consumer. Real
per-frame motion (actual grain positions from a high-N DEM run) is still the
documented future extension of viz_preprocess_lite.py's ``--input-mode``; this script
does not attempt that.

Runs under Blender's bundled Python (needs mathutils, and shape_sampling needs
mathutils.bvhtree), same as viz_preprocess_lite.py:

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --background --python viz/synthetic_flyby_test.py -- \\
        --grains-dir DEMCSVs/torque_align_obj/run_0001_grains_output \\
        --bodies-dir DEMCSVs/torque_align_obj/run_0001_bodies_output \\
        --output-dir DEMCSVs/torque_align_obj/run_0001_viz_instance_flyby_test \\
        --shape-obj "BlenderConvert/Shapes/.../apophis_v233s7.obj" \\
        --n-points 1000000 --max-frames 48
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import mathutils
import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from viz.path_utils import manifest_relpath  # noqa: E402
from viz.shape_sampling import center_and_scale, load_obj_shape, sample_points_in_shape  # noqa: E402
from viz.viz_preprocess_lite import grain_radius_for, reference_scale_from_run  # noqa: E402

DEFAULT_SPIN_AXIS = (0.0, 0.0, 1.0)
DEFAULT_SPIN_PERIOD_HOURS = 30.4  # Apophis's approximate real rotation period


def _blender_argv(argv):
    if '--' in argv:
        return argv[argv.index('--') + 1:]
    return argv[1:]


def _frame_times_s(bodies_csvs):
    """time_s per frame, read from each bodies CSV's Apophis row; None entries if absent."""
    times = []
    for path in bodies_csvs:
        df = pd.read_csv(path, usecols=lambda c: c in ('name', 'time_s'))
        row = df[df['name'] == 'Apophis'] if 'name' in df.columns else df
        if row.empty or 'time_s' not in df.columns or pd.isna(row.iloc[0]['time_s']):
            times.append(None)
        else:
            times.append(float(row.iloc[0]['time_s']))
    return times


def run_synthetic_flyby(
    grains_dir,
    bodies_dir,
    output_dir,
    shape_obj,
    n_points,
    *,
    start_frame=0,
    max_frames=48,
    spin_axis=DEFAULT_SPIN_AXIS,
    spin_period_hours=DEFAULT_SPIN_PERIOD_HOURS,
    sim_name=None,
    run_name=None,
    seed=0,
):
    grains_dir = Path(grains_dir).resolve()
    bodies_dir = Path(bodies_dir).resolve()
    output_dir = Path(output_dir).resolve()
    points_dir = output_dir / 'points'
    points_dir.mkdir(parents=True, exist_ok=True)

    if run_name is None:
        name = grains_dir.name
        run_name = name.replace('_grains_output', '') if name.endswith('_grains_output') else name
    if sim_name is None:
        sim_name = grains_dir.parent.name

    cluster_radius, ref_grain_radius, ref_n = reference_scale_from_run(grains_dir)
    print(f'reference: cluster_radius={cluster_radius:.4f} BU '
          f'grain_radius={ref_grain_radius:.4f} BU (n={ref_n}, run={run_name})')

    if not Path(shape_obj).is_file():
        raise FileNotFoundError(f'shape OBJ not found: {shape_obj}')
    verts, faces = load_obj_shape(str(shape_obj))
    verts, scale = center_and_scale(verts, cluster_radius)
    print(f'shape: {len(verts)} verts scaled by {scale:.6f} to fit cluster_radius')

    base_pos = sample_points_in_shape(verts, faces, n_points, seed=seed)
    grain_radius_vis = grain_radius_for(n_points, ref_n, ref_grain_radius)

    all_bodies_csvs = sorted(glob.glob(str(bodies_dir / '*.csv')))
    if not all_bodies_csvs:
        raise FileNotFoundError(f'No body CSVs in {bodies_dir}')
    if start_frame >= len(all_bodies_csvs):
        raise ValueError(
            f'--start-frame {start_frame} is past the last available body CSV '
            f'index ({len(all_bodies_csvs) - 1})'
        )
    bodies_csvs = all_bodies_csvs[start_frame:start_frame + max_frames]
    frame_ids = [f'{i:05d}' for i in range(len(bodies_csvs))]
    print(f'using body CSVs [{start_frame}:{start_frame + len(bodies_csvs)}] '
          f'of {len(all_bodies_csvs)} available')
    times = _frame_times_s(bodies_csvs)
    if all(t is None for t in times):
        # No real timestamps to drive the tumble from (this run's bodies CSVs
        # don't carry time_s) -- fall back to a fixed number of rotations
        # spread evenly over the frame range, just enough to see it turn.
        fallback_total_turns = 1.5
        dt_fallback = fallback_total_turns * spin_period_hours * 3600.0 / max(1, len(frame_ids) - 1)
        print(f'WARNING: no time_s in bodies CSVs -- faking {fallback_total_turns} '
              f'rotations evenly over {len(frame_ids)} frames instead.')
        times = [i * dt_fallback for i in range(len(frame_ids))]
    else:
        first_known = next(t for t in times if t is not None)
        dt_fallback = 1.0
        times = [t if t is not None else first_known + i * dt_fallback for i, t in enumerate(times)]
    t0 = times[0]

    est_mb = n_points * 3 * 4 / 1e6 * 0.6  # rough, compressed
    print(f'writing {len(frame_ids)} frames x {n_points:,} points '
          f'(~{est_mb * len(frame_ids):.0f} MB estimated) -> {points_dir}')

    axis = mathutils.Vector(spin_axis).normalized()
    period_s = spin_period_hours * 3600.0
    angles_rad = []
    for frame_id, t_s in zip(frame_ids, times):
        angle = 2.0 * np.pi * ((t_s - t0) / period_s)
        angles_rad.append(angle)
        q = mathutils.Quaternion(axis, angle)
        rot = np.array(q.to_matrix(), dtype=np.float32)
        pos = (base_pos @ rot.T).astype(np.float32)
        np.savez_compressed(points_dir / f'{frame_id}.npz', pos=pos)
    print(f'wrote {len(frame_ids)} per-frame point files.')

    rel_bodies = manifest_relpath(bodies_dir, output_dir)
    manifest = {
        'schema_version': 1,
        'viz_mode': 'instance',
        'sim_name': sim_name,
        'run_name': run_name,
        'n_frames': len(frame_ids),
        'frame_ids': frame_ids,
        'bodies_csv_dir': rel_bodies,
        'bodies_start_index': start_frame,
        'static': False,
        'synthetic': True,
        'motion_model': 'rigid_tumble',
        'points_dir': 'points',
        'grain_radius_vis': grain_radius_vis,
        'n_points': n_points,
        'reference_cluster_radius_vis': cluster_radius,
        'reference_grain_radius_vis': ref_grain_radius,
        'reference_n': ref_n,
        'shape_obj': Path(shape_obj).resolve().as_posix(),
        'spin_axis': list(spin_axis),
        'spin_period_hours': spin_period_hours,
        'angles_rad': angles_rad,
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
    p.add_argument('--start-frame', type=int, default=0,
                    help='index into the sorted body CSVs to start from (0-based)')
    p.add_argument('--max-frames', type=int, default=48)
    p.add_argument('--spin-period-hours', type=float, default=DEFAULT_SPIN_PERIOD_HOURS)
    p.add_argument('--sim-name', type=str, default=None)
    p.add_argument('--run-name', type=str, default=None)
    p.add_argument('--seed', type=int, default=0)
    args = p.parse_args(_blender_argv(sys.argv))

    print(f'synthetic_flyby_test: {args.grains_dir} + {args.shape_obj} -> {args.output_dir}')
    run_synthetic_flyby(
        args.grains_dir, args.bodies_dir, args.output_dir, args.shape_obj,
        args.n_points, start_frame=args.start_frame, max_frames=args.max_frames,
        spin_period_hours=args.spin_period_hours,
        sim_name=args.sim_name, run_name=args.run_name, seed=args.seed,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
