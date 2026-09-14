#!/usr/bin/env python3
"""Preprocess DEM grain npz files (or PHANTOM dumps) into bulk Blender viz assets."""

from __future__ import annotations

import argparse
import glob
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
from viz.path_utils import manifest_relpath as _manifest_path  # noqa: E402


def _load_grains(path: Path) -> dict:
    d = np.load(path)
    n = len(d["x_rel_km"])
    pos = np.column_stack([d["x_rel_km"], d["y_rel_km"], d["z_rel_km"]]).astype(np.float64)
    radii = d["Reff_km"].astype(np.float64)
    mass = d["m"].astype(np.float64) if "m" in d.files else np.ones(n)
    vel_keys = ("vx", "vy", "vz")
    if all(k in d.files for k in vel_keys):
        vel = np.nan_to_num(np.column_stack([d[k] for k in vel_keys]).astype(np.float64), nan=0.0)
    else:
        vel = np.zeros((n, 3), dtype=np.float64)
    grain_id = (
        d["grain_id"].astype(np.uint32)
        if "grain_id" in d.files
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


def run_preprocess(
    grains_dir: Path,
    output_dir: Path,
    *,
    bodies_dir: Path | None = None,
    sim_name: str | None = None,
    run_name: str | None = None,
    vis_scale: float = GRAIN_VIS_SCALE,
    min_mass_frac: float = FRAGMENT_MIN_MASS_FRAC,
    max_ejecta: int | None = EJECTA_MAX_INSTANCES,
    envelope_method: str = "hull",
    max_frames: int | None = None,
) -> Path:
    grains_dir = grains_dir.resolve()
    output_dir = output_dir.resolve()
    grain_files = sorted(glob.glob(str(grains_dir / "*.npz")))
    if not grain_files:
        raise FileNotFoundError(
            f"No grain npz files in {grains_dir} (CSV-era folder? re-run DEMDumpConvert.py)"
        )

    if run_name is None:
        name = grains_dir.name
        run_name = name.replace("_grains_output", "") if name.endswith("_grains_output") else name
    if sim_name is None:
        sim_name = grains_dir.parent.name

    env_dir = output_dir / "envelopes"
    ej_dir = output_dir / "ejecta"
    met_dir = output_dir / "metrics"
    for d in (env_dir, ej_dir, met_dir):
        d.mkdir(parents=True, exist_ok=True)

    if max_frames is not None:
        grain_files = grain_files[:max_frames]

    frame_ids: list[str] = []
    rg_initial: float | None = None
    any_subsample = False

    for i, grain_path in enumerate(grain_files):
        frame_id = f"{i:05d}"
        frame_ids.append(frame_id)
        grains = _load_grains(Path(grain_path))
        metrics, rg_initial, envelopes, ejecta, _ = _process_frame(
            grains,
            rg_initial,
            vis_scale=vis_scale,
            min_mass_frac=min_mass_frac,
            max_ejecta=max_ejecta,
            envelope_method=envelope_method,
            frame_seed=i,
        )
        if metrics.get("ejecta_subsampled"):
            any_subsample = True

        for env in envelopes:
            fid = int(env["fragment_id"])
            out = env_dir / f"{frame_id}_f{fid}.npz"
            np.savez_compressed(
                out,
                verts=env["verts"],
                faces=env["faces"],
                fragment_id=np.int32(fid),
                mass_frac=np.float32(env["mass_frac"]),
                n_grains=np.int32(env["n_grains"]),
            )

        np.savez_compressed(
            ej_dir / f"{frame_id}.npz",
            pos=ejecta["pos"],
            radius=ejecta["radius"],
            grain_id=ejecta["grain_id"],
        )
        with open(met_dir / f"{frame_id}.json", "w", encoding="utf-8") as fh:
            json.dump(metrics, fh, indent=2)

        print(
            f"  [{frame_id}] fragments={metrics['n_fragments']} "
            f"ejecta={metrics['n_ejecta']} rg_ratio={metrics['rg_ratio']:.3f} "
            f"unbound={metrics['unbound_fraction']:.3f}"
        )

    # Relative to output_dir so the manifest survives an --output-dir that is
    # not a sibling of the grains/bodies folders; os.path.relpath (not Path.relative_to)
    # because it can walk up out of output_dir.
    bodies_path = (
        bodies_dir.resolve() if bodies_dir else grains_dir.parent / f"{run_name}_bodies_output"
    )
    rel_bodies = _manifest_path(bodies_path, output_dir)
    rel_grains = _manifest_path(grains_dir, output_dir)
    manifest = {
        "schema_version": 1,
        "viz_mode": "composite",
        "sim_name": sim_name,
        "run_name": run_name,
        "grain_vis_scale": vis_scale,
        "n_frames": len(frame_ids),
        "frame_ids": frame_ids,
        "fragment_min_mass_frac": min_mass_frac,
        "ejecta_max_instances": max_ejecta,
        "envelope_method": envelope_method,
        "input_mode": "npz",
        "bodies_csv_dir": rel_bodies,
        "grains_dir": rel_grains,
        "ejecta_subsampled": any_subsample,
    }
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"Wrote manifest -> {manifest_path}")
    return manifest_path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--grains-dir", type=Path, required=True, help="run_XXXX_grains_output/")
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
        help="npz = DEMDumpConvert.py grain files; dump mode reserved for P4 (not implemented yet)",
    )
    p.add_argument("--dump-dir", type=Path, default=None)
    args = p.parse_args()

    if args.input_mode == "dump":
        print("[ERROR] --input-mode dump is P4 (Objective 2 gate); use grain npz files for P0–P3.", file=sys.stderr)
        return 1

    print(f"viz_preprocess: {args.grains_dir} -> {args.output_dir}")
    run_preprocess(
        args.grains_dir,
        args.output_dir,
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
