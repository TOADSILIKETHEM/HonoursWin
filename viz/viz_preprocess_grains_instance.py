#!/usr/bin/env python3
"""Grain frames -> per-frame GN instance point files for the real simulated grains.

Feeds BlenderConvert/DEMBulkInstanceBlender.py a ``viz_mode: "instance"``,
``static: false`` manifest in which every point is one real DEM grain (the
TUI's ``instance_grains`` render path) -- unlike viz_preprocess_lite.py's
static shape-model placeholder or synthetic_flyby_test.py's rigid tumble.
npz mode is numpy only; dump mode also needs sarracen + pandas (both in the
Windows .venv).

    python viz/viz_preprocess_grains_instance.py \\
        --grains-dir DEMCSVs/<sim>/run_XXXX_grains_output \\
        --bodies-dir DEMCSVs/<sim>/run_XXXX_bodies_output \\
        --output-dir DEMCSVs/<sim>/run_XXXX_viz_instance [--max-frames N]

    # straight from PHANTOM dumps (no grains npz; writes the bodies CSVs):
    python viz/viz_preprocess_grains_instance.py --input-mode dump \\
        --run-dir sobol_mass_runs/<sim>/run_XXXX \\
        --bodies-dir DEMCSVs/<sim>/run_XXXX_bodies_output \\
        --output-dir DEMCSVs/<sim>/run_XXXX_viz_instance
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from viz.fcurve_handles import SMOOTHING, right_handle_offsets  # noqa: E402
from viz.path_utils import manifest_relpath  # noqa: E402
from viz.dump_frames import iter_grain_frames  # noqa: E402


class GrainReappeared(ValueError):
    """A grain is absent between two frames it is present in (instances need one run of frames)."""


class InstanceBuilder:
    """One instance_grains preprocess run fed a frame at a time: add(grains) per frame, then finish().

    build_grains_instance() feeds it from one frame source; viz_preprocess_dump.py
    feeds it alongside CompositeBuilder so each dump is read once.
    """

    def __init__(
        self,
        output_dir: Path,
        *,
        bodies_dir: Path,
        grains_dir: Path | None = None,
        run_dir: Path | None = None,
        sim_name: str | None = None,
        run_name: str | None = None,
        rotation_seed: int = 0,
    ) -> None:
        self.bodies_dir = Path(bodies_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        if grains_dir is not None:
            grains_dir = Path(grains_dir).resolve()
            name_dir, suffix = grains_dir, "_grains_output"
        else:
            name_dir, suffix = self.bodies_dir, "_bodies_output"

        if run_name is None:
            name = name_dir.name
            run_name = name.replace(suffix, "") if name.endswith(suffix) else name
        if sim_name is None:
            sim_name = name_dir.parent.name
        self.grains_dir = grains_dir
        self.run_dir = run_dir
        self.sim_name = sim_name
        self.run_name = run_name
        self.rotation_seed = rotation_seed

        self.points_dir = self.output_dir / "points"
        self.frame_ids: list[str] = []
        self.frames: list[tuple[np.ndarray, np.ndarray]] = []  # per frame: sorted ids, their positions
        self.first_seen: dict[int, tuple[np.float32, np.ndarray]] = {}  # id -> (radius, rot) at first frame
        self._rng = np.random.default_rng(rotation_seed)

    def add(self, d) -> None:
        i = len(self.frame_ids)
        if i == 0:
            self.points_dir.mkdir(parents=True, exist_ok=True)
        gid = np.asarray(d["grain_id"])
        # Same draw as DEMGrainsBlenderEarthCam.py: grains new in this frame each
        # draw one Euler triple, in this frame's stored order, from one seeded
        # stream. Frame 0 draws first, so a fixed-set run keeps its rotations.
        new = [j for j, g in enumerate(gid.tolist()) if g not in self.first_seen]
        rots = self._rng.uniform(0.0, 2.0 * np.pi, size=(len(new), 3)).astype(np.float32)
        radius = np.asarray(d["Reff_vis"])
        for j, rot in zip(new, rots):
            self.first_seen[int(gid[j])] = (np.float32(radius[j]), rot)
        # Instance i must be the same grain in every frame, or the GN
        # per-instance rotation jumps between grains and flickers.
        order = np.argsort(gid, kind="stable")
        pos = np.column_stack([d["x_vis"], d["y_vis"], d["z_vis"]])[order].astype(np.float32)
        self.frames.append((gid[order], pos))
        self.frame_ids.append(f"{i:05d}")

    def finish(self) -> Path:
        # One slot per grain that ever appears; present[k, j] = grain j is in frame k.
        ids = np.unique(np.concatenate([g for g, _ in self.frames])).astype(np.int64)
        n_frames, n = len(self.frames), len(ids)
        pos = np.zeros((n_frames, n, 3), dtype=np.float32)
        present = np.zeros((n_frames, n), dtype=bool)
        for k, (g, p) in enumerate(self.frames):
            cols = np.searchsorted(ids, g)
            pos[k, cols] = p
            present[k, cols] = True

        first = present.argmax(axis=0)
        last = n_frames - 1 - present[::-1].argmax(axis=0)
        gaps = present.sum(axis=0) != last - first + 1
        if gaps.any():
            j = int(np.flatnonzero(gaps)[0])
            missing = next(k for k in range(first[j], last[j]) if not present[k, j])
            raise GrainReappeared(
                f"grain {ids[j]} is absent at frame {self.frame_ids[missing]} but present before and "
                "after it; instance meshes need each grain present over one run of frames"
            )

        # Absent slots hold the nearest present position (first before joining,
        # last after leaving): where per-sphere's F-curve rests beyond its end keys.
        # Only grains that join or leave need it, so a fixed set copies nothing.
        var = np.flatnonzero((first > 0) | (last < n_frames - 1))
        if var.size:
            rows = np.clip(np.arange(n_frames)[:, None], first[var], last[var])
            pos[:, var] = pos[rows, var]
        # Bezier handles of the per-sphere path's location F-curves, solved over each
        # grain's own keys (fcurve_handles.py), grouped by key range so the solve stays
        # vectorised. Zero outside the range, so the curve is flat there.
        handles = np.zeros_like(pos)
        for f, l in np.unique(np.stack([first, last], axis=1), axis=0):
            cols = np.flatnonzero((first == f) & (last == l))
            handles[f:l + 1, cols] = right_handle_offsets(pos[f:l + 1, cols]).astype(np.float32)

        radius = np.array([self.first_seen[int(g)][0] for g in ids], dtype=np.float32)
        rot = np.stack([self.first_seen[int(g)][1] for g in ids]).astype(np.float32)
        for k, fid in enumerate(self.frame_ids):
            np.savez_compressed(
                self.points_dir / f"{fid}.npz",
                pos=pos[k], radius=radius, rot=rot, handle=handles[k], grain_id=ids, present=present[k],
            )
        grain_radius_vis = float(np.median(radius))

        manifest = {
            "schema_version": 1,
            "viz_mode": "instance",
            "static": False,
            "source": "grains",
            "input_mode": "npz" if self.run_dir is None else "dump",
            "sim_name": self.sim_name,
            "run_name": self.run_name,
            "n_frames": len(self.frame_ids),
            "frame_ids": self.frame_ids,
            "points_dir": "points",
            "n_points": n,
            "variable_grain_set": bool(not present.all()),
            "grain_radius_vis": grain_radius_vis,
            "bodies_csv_dir": manifest_relpath(self.bodies_dir, self.output_dir),
            "bodies_start_index": 0,
            "interpolation": {"mode": "bezier", "auto_smoothing": SMOOTHING, "handle_key": "handle"},
            "rotation_seed": self.rotation_seed,
        }
        manifest_path = self.output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path


def build_grains_instance(
    grains_dir: Path | None,
    bodies_dir: Path,
    output_dir: Path,
    *,
    run_dir: Path | None = None,
    max_frames: int | None = None,
    sim_name: str | None = None,
    run_name: str | None = None,
    rotation_seed: int = 0,
) -> Path:
    """npz mode reads ``grains_dir``; dump mode (``run_dir``) reads the dumps and writes ``bodies_dir``."""
    b = InstanceBuilder(
        output_dir, bodies_dir=bodies_dir, grains_dir=grains_dir, run_dir=run_dir,
        sim_name=sim_name, run_name=run_name, rotation_seed=rotation_seed,
    )
    for _name, d in iter_grain_frames(
        grains_dir=b.grains_dir, run_dir=run_dir, bodies_dir=b.bodies_dir, max_frames=max_frames,
    ):
        b.add(d)
    return b.finish()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input-mode", choices=("npz", "dump"), default="npz",
                   help="npz = DEMDumpConvert.py grain files (--grains-dir); "
                        "dump = PHANTOM dumps (--run-dir), no grains npz")
    p.add_argument("--grains-dir", type=Path, default=None)
    p.add_argument("--run-dir", type=Path, default=None, help="PHANTOM run dir with sobol_* dumps")
    p.add_argument("--bodies-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--sim-name", type=str, default=None)
    p.add_argument("--run-name", type=str, default=None)
    p.add_argument("--rotation-seed", type=int, default=0,
                   help="per-grain orientation seed (DEMGrainsBlenderEarthCam.py GRAIN_RANDOM_ROTATION_SEED)")
    args = p.parse_args(argv)
    if args.input_mode == "npz" and args.grains_dir is None:
        p.error("--input-mode npz needs --grains-dir")
    if args.input_mode == "dump" and args.run_dir is None:
        p.error("--input-mode dump needs --run-dir")
    try:
        manifest_path = build_grains_instance(
            args.grains_dir if args.input_mode == "npz" else None,
            args.bodies_dir, args.output_dir,
            run_dir=args.run_dir if args.input_mode == "dump" else None,
            max_frames=args.max_frames, sim_name=args.sim_name, run_name=args.run_name,
            rotation_seed=args.rotation_seed,
        )
    except (FileNotFoundError, GrainReappeared) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
