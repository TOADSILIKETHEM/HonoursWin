#!/usr/bin/env python3
"""One pass over a run's PHANTOM dumps feeds composite and/or instance_grains preprocess.

Each dump is read once (sarracen) and its frame handed to every requested
builder, instead of each preprocess script reading every dump itself (spec
2026-09-29 §3b). A builder that fails is dropped and reported; the others
finish. Writes the bodies CSVs once.

    python viz/viz_preprocess_dump.py --run-dir sobol_mass_runs/<sim>/run_XXXX \\
        --bodies-dir DEMCSVs/<sim>/run_XXXX_bodies_output \\
        --composite-dir DEMCSVs/<sim>/run_XXXX_viz [--envelope-method hull|sdf] \\
        --instance-dir DEMCSVs/<sim>/run_XXXX_viz_instance [--max-frames N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from viz.dump_frames import iter_grain_frames  # noqa: E402
from viz.viz_preprocess import CompositeBuilder  # noqa: E402
from viz.viz_preprocess_grains_instance import InstanceBuilder  # noqa: E402


def run_dump_preprocess(run_dir, bodies_dir, builders: dict, *, max_frames=None) -> dict:
    """{name: manifest Path | the exception that stopped that builder}, in ``builders`` order."""
    live = dict(builders)
    out: dict = {}
    try:
        for _name, d in iter_grain_frames(run_dir=run_dir, bodies_dir=bodies_dir, max_frames=max_frames):
            for key, b in list(live.items()):
                try:
                    b.add(d)
                except Exception as exc:  # one path's failure must not stop the other
                    out[key] = exc
                    del live[key]
            if not live:
                break
    except Exception as exc:  # reading the dumps failed: no builder can finish
        out.update({key: exc for key in live})
        live = {}
    for key, b in live.items():
        try:
            out[key] = b.finish()
        except Exception as exc:
            out[key] = exc
    return {key: out[key] for key in builders}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, required=True, help="PHANTOM run dir with sobol_* dumps")
    p.add_argument("--bodies-dir", type=Path, required=True)
    p.add_argument("--composite-dir", type=Path, default=None, help="run_XXXX_viz/")
    p.add_argument("--envelope-method", choices=("hull", "sdf"), default="hull")
    p.add_argument("--instance-dir", type=Path, default=None, help="run_XXXX_viz_instance/")
    p.add_argument("--rotation-seed", type=int, default=0)
    p.add_argument("--max-frames", type=int, default=None)
    args = p.parse_args(argv)
    if args.composite_dir is None and args.instance_dir is None:
        p.error("need --composite-dir and/or --instance-dir")

    targets = {}
    if args.composite_dir is not None:
        targets["composite"] = args.composite_dir
    if args.instance_dir is not None:
        targets["instance_grains"] = args.instance_dir
    # success = manifest.json exists afterwards, so drop any stale one first
    for d in targets.values():
        (d / "manifest.json").unlink(missing_ok=True)

    builders = {}
    if "composite" in targets:
        builders["composite"] = CompositeBuilder(
            args.composite_dir, run_dir=args.run_dir, bodies_dir=args.bodies_dir,
            envelope_method=args.envelope_method,
        )
    if "instance_grains" in targets:
        builders["instance_grains"] = InstanceBuilder(
            args.instance_dir, run_dir=args.run_dir, bodies_dir=args.bodies_dir,
            rotation_seed=args.rotation_seed,
        )
    print(f"viz_preprocess_dump: {args.run_dir} -> {', '.join(targets)}")
    results = run_dump_preprocess(args.run_dir, args.bodies_dir, builders, max_frames=args.max_frames)
    ok = True
    for name, res in results.items():
        if isinstance(res, Exception):
            ok = False
            print(f"FAILED {name}: {type(res).__name__}: {res}")
        else:
            print(f"OK {name} -> {res}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
