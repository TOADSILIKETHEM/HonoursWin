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

from viz.path_utils import manifest_relpath  # noqa: E402


class GrainCountMismatch(ValueError):
    """A frame's grain count differs from frame 0 (instance meshes need a fixed count)."""


def build_grains_instance(
    grains_dir: Path,
    bodies_dir: Path,
    output_dir: Path,
    *,
    max_frames: int | None = None,
    sim_name: str | None = None,
    run_name: str | None = None,
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
    n0: int | None = None
    grain_radius_vis = 0.0
    for i, path in enumerate(grain_files):
        fid = f"{i:05d}"
        d = np.load(path)
        # Instance i must be the same grain in every frame, or the GN
        # per-instance random rotation jumps between grains and flickers.
        order = np.argsort(np.asarray(d["grain_id"]), kind="stable")
        pos = np.column_stack([d["x_vis"], d["y_vis"], d["z_vis"]])[order].astype(np.float32)
        radius = np.asarray(d["Reff_vis"])[order].astype(np.float32)
        if n0 is None:
            n0 = len(pos)
            grain_radius_vis = float(np.median(radius))
        elif len(pos) != n0:
            raise GrainCountMismatch(f"frame {fid} has {len(pos)} grains, frame 00000 has {n0}")
        np.savez_compressed(points_dir / f"{fid}.npz", pos=pos, radius=radius)
        frame_ids.append(fid)

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
    args = p.parse_args(argv)
    try:
        manifest_path = build_grains_instance(
            args.grains_dir, args.bodies_dir, args.output_dir,
            max_frames=args.max_frames, sim_name=args.sim_name, run_name=args.run_name,
        )
    except (FileNotFoundError, GrainCountMismatch) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
