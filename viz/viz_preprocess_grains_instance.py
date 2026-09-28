#!/usr/bin/env python3
"""Grain npz -> per-frame GN instance point files for the real simulated grains.

Feeds BlenderConvert/DEMBulkInstanceBlender.py a ``viz_mode: "instance"``,
``static: false`` manifest in which every point is one real DEM grain (the
TUI's ``instance_grains`` render path) -- unlike viz_preprocess_lite.py's
static shape-model placeholder or synthetic_flyby_test.py's rigid tumble.
numpy only, so it runs in the Windows .venv (or any plain Python).

    python viz/viz_preprocess_grains_instance.py \\
        --grains-dir DEMCSVs/<sim>/run_XXXX_grains_output \\
        --bodies-dir DEMCSVs/<sim>/run_XXXX_bodies_output \\
        --output-dir DEMCSVs/<sim>/run_XXXX_viz_instance [--max-frames N]
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from viz.fcurve_handles import SMOOTHING, right_handle_offsets  # noqa: E402
from viz.path_utils import manifest_relpath  # noqa: E402


class GrainCountMismatch(ValueError):
    """A frame's grain set differs from frame 0 (instance meshes need a fixed set)."""


def build_grains_instance(
    grains_dir: Path,
    bodies_dir: Path,
    output_dir: Path,
    *,
    max_frames: int | None = None,
    sim_name: str | None = None,
    run_name: str | None = None,
    rotation_seed: int = 0,
) -> Path:
    grains_dir = Path(grains_dir).resolve()
    bodies_dir = Path(bodies_dir).resolve()
    output_dir = Path(output_dir).resolve()

    grain_files = sorted(glob.glob(str(grains_dir / "*.npz")))
    if not grain_files:
        raise FileNotFoundError(
            f"No grain npz files in {grains_dir} (CSV-era folder? re-run DEMDumpConvert.py)"
        )
    if max_frames is not None:
        grain_files = grain_files[:max_frames]

    if run_name is None:
        name = grains_dir.name
        run_name = name.replace("_grains_output", "") if name.endswith("_grains_output") else name
    if sim_name is None:
        sim_name = grains_dir.parent.name

    points_dir = output_dir / "points"
    points_dir.mkdir(parents=True, exist_ok=True)

    frame_ids: list[str] = []
    ids0: np.ndarray | None = None
    rot = None
    positions = []
    radius = None
    for i, path in enumerate(grain_files):
        fid = f"{i:05d}"
        d = np.load(path)
        # Instance i must be the same grain in every frame, or the GN
        # per-instance rotation jumps between grains and flickers.
        order = np.argsort(np.asarray(d["grain_id"]), kind="stable")
        pos = np.column_stack([d["x_vis"], d["y_vis"], d["z_vis"]])[order].astype(np.float32)
        if ids0 is None:
            ids0 = np.asarray(d["grain_id"])[order]
            radius = np.asarray(d["Reff_vis"])[order].astype(np.float32)
            # Same draw as DEMGrainsBlenderEarthCam.py: one Euler triple per
            # grain in frame 0's stored order, so each grain gets the exact
            # orientation (and rock pattern) it has in the per-sphere render.
            rng = np.random.default_rng(rotation_seed)
            rot = rng.uniform(0.0, 2.0 * np.pi, size=(len(order), 3))[order].astype(np.float32)
        elif len(pos) != len(ids0):
            raise GrainCountMismatch(f"frame {fid} has {len(pos)} grains, frame 00000 has {len(ids0)}")
        elif not np.array_equal(np.asarray(d["grain_id"])[order], ids0):
            raise GrainCountMismatch(f"frame {fid} has different grain ids from frame 00000")
        positions.append(pos)
        frame_ids.append(fid)

    # Bezier handles of the per-sphere path's location F-curves, so instances
    # follow the same path between sim frames (fcurve_handles.py).
    handles = right_handle_offsets(np.stack(positions)).astype(np.float32)
    for fid, pos, h in zip(frame_ids, positions, handles):
        np.savez_compressed(
            points_dir / f"{fid}.npz",
            pos=pos, radius=radius, rot=rot, handle=h, grain_id=ids0,
        )
    n0 = len(ids0)
    grain_radius_vis = float(np.median(radius))

    manifest = {
        "schema_version": 1,
        "viz_mode": "instance",
        "static": False,
        "source": "grains",
        "sim_name": sim_name,
        "run_name": run_name,
        "n_frames": len(frame_ids),
        "frame_ids": frame_ids,
        "points_dir": "points",
        "n_points": n0,
        "grain_radius_vis": grain_radius_vis,
        "bodies_csv_dir": manifest_relpath(bodies_dir, output_dir),
        "bodies_start_index": 0,
        "interpolation": {"mode": "bezier", "auto_smoothing": SMOOTHING, "handle_key": "handle"},
        "rotation_seed": rotation_seed,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--grains-dir", type=Path, required=True)
    p.add_argument("--bodies-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--sim-name", type=str, default=None)
    p.add_argument("--run-name", type=str, default=None)
    p.add_argument("--rotation-seed", type=int, default=0,
                   help="per-grain orientation seed (DEMGrainsBlenderEarthCam.py GRAIN_RANDOM_ROTATION_SEED)")
    args = p.parse_args(argv)
    try:
        manifest_path = build_grains_instance(
            args.grains_dir, args.bodies_dir, args.output_dir,
            max_frames=args.max_frames, sim_name=args.sim_name, run_name=args.run_name,
            rotation_seed=args.rotation_seed,
        )
    except (FileNotFoundError, GrainCountMismatch) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
