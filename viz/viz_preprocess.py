#!/usr/bin/env python3
"""Preprocess DEM grain frames (grains npz or PHANTOM dumps) into bulk Blender viz assets."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import QhullError

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from viz.constants import (  # noqa: E402
    EJECTA_MAX_INSTANCES,
    FRAGMENT_MIN_MASS_FRAC,
    GRAIN_VIS_SCALE,
)
from viz.dem_fof import (  # noqa: E402
    assign_fragments_and_ejecta,
    mass_weighted_rg,
    unbound_mass_main_body,
    main_body_mask,
)
from viz.envelope import build_envelope  # noqa: E402
from viz.dump_frames import iter_grain_frames  # noqa: E402
from viz.path_utils import manifest_relpath as _manifest_path  # noqa: E402


def _grains_from(d) -> dict:
    """Arrays _process_frame needs, from a grains npz or a dump frame's grains dict."""
    n = len(d["x_rel_km"])
    pos = np.column_stack([d["x_rel_km"], d["y_rel_km"], d["z_rel_km"]]).astype(np.float64)
    radii = d["Reff_km"].astype(np.float64)
    mass = d["m"].astype(np.float64) if "m" in d else np.ones(n)
    vel_keys = ("vx", "vy", "vz")
    if all(k in d for k in vel_keys):
        vel = np.nan_to_num(np.column_stack([d[k] for k in vel_keys]).astype(np.float64), nan=0.0)
    else:
        vel = np.zeros((n, 3), dtype=np.float64)
    grain_id = (
        d["grain_id"].astype(np.uint32)
        if "grain_id" in d
        else np.arange(n, dtype=np.uint32)
    )
    return {
        "pos": pos,
        "radii": radii,
        "mass": mass,
        "vel": vel,
        "grain_id": grain_id,
    }


def _select_ejecta_arrays(
    pos_vis: np.ndarray,
    radius_vis: np.ndarray,
    grain_id: np.ndarray,
    mass: np.ndarray,
    ejecta_mask: np.ndarray,
    max_instances: int | None,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, bool]:
    """Return ejecta arrays, subsampling by mass if over cap."""
    idx = np.where(ejecta_mask)[0]
    if len(idx) == 0:
        empty_f = np.array([], dtype=np.float32)
        empty_u = np.array([], dtype=np.uint32)
        return empty_f.reshape(0, 3), empty_f, empty_u, False

    if max_instances is None or max_instances <= 0 or len(idx) <= max_instances:
        return pos_vis[idx], radius_vis[idx], grain_id[idx], False

    weights = mass[idx].astype(np.float64)
    if not np.isfinite(weights).all() or weights.sum() <= 0.0:
        weights = np.ones(len(idx), dtype=np.float64)
    rng = np.random.default_rng(seed)
    # Efraimidis-Spirakis weighted sampling without replacement: one O(n) key
    # per candidate plus a partition, instead of the sequential rejection loop
    # numpy uses for choice(replace=False, p=...) — that loop dominates at the
    # 50k cap.
    keys = np.log(rng.random(len(idx))) / np.maximum(weights, np.finfo(np.float64).tiny)
    chosen = idx[np.argpartition(keys, -max_instances)[-max_instances:]]
    return pos_vis[chosen], radius_vis[chosen], grain_id[chosen], True


def _process_frame(
    grains: dict,
    rg_initial: float | None,
    *,
    vis_scale: float,
    min_mass_frac: float,
    max_ejecta: int | None,
    envelope_method: str,
    frame_seed: int,
) -> tuple[dict, float | None, list[dict], dict, dict]:
    pos = grains["pos"]
    radii = grains["radii"]
    mass = grains["mass"]
    vel = grains["vel"]
    grain_id = grains["grain_id"]

    rg = mass_weighted_rg(pos, mass)
    if rg_initial is None:
        rg_initial = rg
        rg_ratio = 1.0
    elif rg_initial > 0.0:
        rg_ratio = rg / rg_initial
    else:
        rg_ratio = 1.0

    fragment_masks, ejecta_mask, _labels = assign_fragments_and_ejecta(
        pos, mass, vel, rg_ratio, min_mass_frac
    )
    mb = main_body_mask(pos, mass, rg_ratio=rg_ratio)
    m_tot = float(mass.sum())
    unbound = unbound_mass_main_body(pos, mass, vel, main_mask=mb)
    unbound_frac = unbound / m_tot if m_tot > 0.0 else 0.0

    pos_vis = pos * vis_scale
    radius_vis = radii * vis_scale

    e_pos, e_rad, e_gid, subsampled = _select_ejecta_arrays(
        pos_vis, radius_vis, grain_id, mass, ejecta_mask, max_ejecta, seed=frame_seed
    )

    envelopes: list[dict] = []
    for frag_id, fmask in enumerate(fragment_masks):
        f_pos = pos[fmask]
        f_rad = radii[fmask]
        if len(f_pos) < 4:
            continue
        try:
            verts, faces = build_envelope(f_pos, f_rad, vis_scale, method=envelope_method)
        except (ValueError, QhullError) as exc:
            # One degenerate fragment must not abort the whole run.
            print(f"  [warn] fragment {frag_id} ({len(f_pos)} grains): "
                  f"no envelope ({type(exc).__name__}); skipped")
            continue
        mass_frac = float(mass[fmask].sum()) / m_tot if m_tot > 0 else 0.0
        envelopes.append({
            "fragment_id": frag_id,
            "verts": verts,
            "faces": faces,
            "mass_frac": mass_frac,
            "n_grains": int(fmask.sum()),
        })

    metrics = {
        "rg_ratio": float(rg_ratio),
        "unbound_fraction": float(unbound_frac),
        "n_fragments": len(envelopes),
        "n_ejecta": int(len(e_pos)),
        "ejecta_subsampled": bool(subsampled),
    }
    ejecta = {"pos": e_pos.astype(np.float32), "radius": e_rad.astype(np.float32), "grain_id": e_gid}
    return metrics, rg_initial, envelopes, ejecta, grains


class CompositeBuilder:
    """One composite preprocess run fed a frame at a time: add(grains) per frame, then finish().

    run_preprocess() feeds it from one frame source; viz_preprocess_dump.py
    feeds it alongside InstanceBuilder so each dump is read once.
    """

    def __init__(
        self,
        output_dir: Path,
        *,
        grains_dir: Path | None = None,
        run_dir: Path | None = None,
        bodies_dir: Path | None = None,
        sim_name: str | None = None,
        run_name: str | None = None,
        vis_scale: float = GRAIN_VIS_SCALE,
        min_mass_frac: float = FRAGMENT_MIN_MASS_FRAC,
        max_ejecta: int | None = EJECTA_MAX_INSTANCES,
        envelope_method: str = "hull",
    ) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.dump_mode = run_dir is not None
        if self.dump_mode:
            if bodies_dir is None:
                raise ValueError("dump mode needs bodies_dir")
            name_dir, suffix = Path(bodies_dir).resolve(), "_bodies_output"
        else:
            grains_dir = Path(grains_dir).resolve()
            name_dir, suffix = grains_dir, "_grains_output"

        if run_name is None:
            name = name_dir.name
            run_name = name.replace(suffix, "") if name.endswith(suffix) else name
        if sim_name is None:
            sim_name = name_dir.parent.name
        self.grains_dir = grains_dir
        self.bodies_dir = bodies_dir
        self.sim_name = sim_name
        self.run_name = run_name
        self.vis_scale = vis_scale
        self.min_mass_frac = min_mass_frac
        self.max_ejecta = max_ejecta
        self.envelope_method = envelope_method

        self.env_dir = self.output_dir / "envelopes"
        self.ej_dir = self.output_dir / "ejecta"
        self.met_dir = self.output_dir / "metrics"
        # dump mode: DEMBulkVizBlender.py builds its tracking camera from
        # <grains_dir>/*.npz x_vis/y_vis/z_vis only; with no grains npz we write
        # just those (float64, so the camera is identical to the npz route).
        self.cam_dir = self.output_dir / "grains"
        for d in (self.env_dir, self.ej_dir, self.met_dir) + ((self.cam_dir,) if self.dump_mode else ()):
            d.mkdir(parents=True, exist_ok=True)
        if self.dump_mode:
            for old in self.cam_dir.glob("*.npz"):
                old.unlink()

        self.frame_ids: list[str] = []
        self.rg_initial: float | None = None
        self.any_subsample = False

    def add(self, d) -> None:
        i = len(self.frame_ids)
        frame_id = f"{i:05d}"
        self.frame_ids.append(frame_id)
        grains = _grains_from(d)
        if self.dump_mode:
            np.savez(self.cam_dir / f"{frame_id}.npz",
                     x_vis=np.asarray(d["x_vis"]), y_vis=np.asarray(d["y_vis"]), z_vis=np.asarray(d["z_vis"]))
        metrics, self.rg_initial, envelopes, ejecta, _ = _process_frame(
            grains,
            self.rg_initial,
            vis_scale=self.vis_scale,
            min_mass_frac=self.min_mass_frac,
            max_ejecta=self.max_ejecta,
            envelope_method=self.envelope_method,
            frame_seed=i,
        )
        if metrics.get("ejecta_subsampled"):
            self.any_subsample = True

        for env in envelopes:
            fid = int(env["fragment_id"])
            out = self.env_dir / f"{frame_id}_f{fid}.npz"
            np.savez_compressed(
                out,
                verts=env["verts"],
                faces=env["faces"],
                fragment_id=np.int32(fid),
                mass_frac=np.float32(env["mass_frac"]),
                n_grains=np.int32(env["n_grains"]),
            )

        np.savez_compressed(
            self.ej_dir / f"{frame_id}.npz",
            pos=ejecta["pos"],
            radius=ejecta["radius"],
            grain_id=ejecta["grain_id"],
        )
        with open(self.met_dir / f"{frame_id}.json", "w", encoding="utf-8") as fh:
            json.dump(metrics, fh, indent=2)

        print(
            f"  [{frame_id}] fragments={metrics['n_fragments']} "
            f"ejecta={metrics['n_ejecta']} rg_ratio={metrics['rg_ratio']:.3f} "
            f"unbound={metrics['unbound_fraction']:.3f}"
        )

    def finish(self) -> Path:
        # Relative to output_dir so the manifest survives an --output-dir that is
        # not a sibling of the grains/bodies folders; os.path.relpath (not Path.relative_to)
        # because it can walk up out of output_dir.
        bodies_path = (
            Path(self.bodies_dir).resolve() if self.bodies_dir
            else self.grains_dir.parent / f"{self.run_name}_bodies_output"
        )
        rel_bodies = _manifest_path(bodies_path, self.output_dir)
        rel_grains = _manifest_path(self.cam_dir if self.dump_mode else self.grains_dir, self.output_dir)
        manifest = {
            "schema_version": 1,
            "viz_mode": "composite",
            "sim_name": self.sim_name,
            "run_name": self.run_name,
            "grain_vis_scale": self.vis_scale,
            "n_frames": len(self.frame_ids),
            "frame_ids": self.frame_ids,
            "fragment_min_mass_frac": self.min_mass_frac,
            "ejecta_max_instances": self.max_ejecta,
            "envelope_method": self.envelope_method,
            "input_mode": "dump" if self.dump_mode else "npz",
            "bodies_csv_dir": rel_bodies,
            "grains_dir": rel_grains,
            "ejecta_subsampled": self.any_subsample,
        }
        manifest_path = self.output_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)

        print(f"Wrote manifest -> {manifest_path}")
        return manifest_path


def run_preprocess(
    grains_dir: Path | None,
    output_dir: Path,
    *,
    run_dir: Path | None = None,
    bodies_dir: Path | None = None,
    sim_name: str | None = None,
    run_name: str | None = None,
    vis_scale: float = GRAIN_VIS_SCALE,
    min_mass_frac: float = FRAGMENT_MIN_MASS_FRAC,
    max_ejecta: int | None = EJECTA_MAX_INSTANCES,
    envelope_method: str = "hull",
    max_frames: int | None = None,
) -> Path:
    """npz mode reads ``grains_dir``; dump mode (``run_dir``) reads PHANTOM dumps and writes ``bodies_dir``."""
    b = CompositeBuilder(
        output_dir, grains_dir=None if run_dir is not None else grains_dir, run_dir=run_dir,
        bodies_dir=bodies_dir, sim_name=sim_name, run_name=run_name, vis_scale=vis_scale,
        min_mass_frac=min_mass_frac, max_ejecta=max_ejecta, envelope_method=envelope_method,
    )
    for _name, d in iter_grain_frames(
        grains_dir=b.grains_dir, run_dir=run_dir, bodies_dir=bodies_dir, max_frames=max_frames,
    ):
        b.add(d)
    return b.finish()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--grains-dir", type=Path, default=None, help="run_XXXX_grains_output/ (npz mode)")
    p.add_argument("--output-dir", type=Path, required=True, help="run_XXXX_viz/")
    p.add_argument("--bodies-dir", type=Path, default=None, help="run_XXXX_bodies_output/")
    p.add_argument("--sim-name", type=str, default=None)
    p.add_argument("--run-name", type=str, default=None)
    p.add_argument("--grain-vis-scale", type=float, default=GRAIN_VIS_SCALE)
    p.add_argument("--fragment-min-mass-frac", type=float, default=FRAGMENT_MIN_MASS_FRAC)
    p.add_argument("--ejecta-max-instances", type=int, default=EJECTA_MAX_INSTANCES)
    p.add_argument(
        "--envelope-method",
        choices=("hull", "sdf"),
        default="hull",
        help="hull=P0 convex hull; sdf=P2 sphere-union SDF",
    )
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument(
        "--input-mode",
        choices=("npz", "dump"),
        default="npz",
        help="npz = DEMDumpConvert.py grain files (--grains-dir); "
             "dump = PHANTOM dumps (--run-dir, needs --bodies-dir), no grains npz",
    )
    p.add_argument("--run-dir", type=Path, default=None, help="PHANTOM run dir with sobol_* dumps")
    args = p.parse_args(argv)

    if args.input_mode == "npz" and args.grains_dir is None:
        p.error("--input-mode npz needs --grains-dir")
    if args.input_mode == "dump" and (args.run_dir is None or args.bodies_dir is None):
        p.error("--input-mode dump needs --run-dir and --bodies-dir")

    src = args.run_dir if args.input_mode == "dump" else args.grains_dir
    print(f"viz_preprocess ({args.input_mode}): {src} -> {args.output_dir}")
    run_preprocess(
        args.grains_dir if args.input_mode == "npz" else None,
        args.output_dir,
        run_dir=args.run_dir if args.input_mode == "dump" else None,
        bodies_dir=args.bodies_dir,
        sim_name=args.sim_name,
        run_name=args.run_name,
        vis_scale=args.grain_vis_scale,
        min_mass_frac=args.fragment_min_mass_frac,
        max_ejecta=args.ejecta_max_instances,
        envelope_method=args.envelope_method,
        max_frames=args.max_frames,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
