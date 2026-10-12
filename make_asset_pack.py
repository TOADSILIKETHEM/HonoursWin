#!/usr/bin/env python3
"""Build honours_viz_pack(.zip) for someone setting the viz pipeline up on
another machine (Code/README.md): one example PHANTOM run + the public Apophis
shape model. No .blend materials/textures and no HDRI (left out on purpose,
2026-10-10): renders fall back to a bare-sphere Earth, plain grains, black sky.

    python3 Code/make_asset_pack.py [--out DIR]     # default <data_dir>/share
"""
import argparse
import shutil
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))
import honours_paths as hp  # noqa: E402

# 97 dumps, 391 grains, hyperbola flyby (Earth + Apophis), 31 MB
EXAMPLE_RUN = (CODE.parent / "sobol_mass_runs"
               / "sobol_20261006_221234_np300_tmx48_dtmx0.5_hyp_settled_bldnone_sig10" / "run_0001")
EXAMPLE_FILES = ("sobol.setup", "encounter.json")
# JPL radar shape model (PDS, public); tui_sim_render.DEFAULT_PLACEHOLDER_OBJ
SHAPE = Path("Shapes/gbo.ast-apophis.jpl.radar.shape_model_v1.0/gbo.ast-apophis.jpl.radar.shape_model_v1.0"
             "/data/apophis_v233s7.obj")

PACK_README = """\
honours_viz_pack -- example data for the Apophis DEM viz pipeline (Code/README.md)

example_run/run_0001/   PHANTOM particle-DEM dumps (sobol_00000..) + sobol.setup + encounter.json
                        391 grains, hyperbola flyby past Earth, 97 frames
data/                   point data_dir here; renders land in data/DEMCSVs/
data/BlenderConvert/Shapes/...apophis_v233s7.obj   placeholder shape (instance_static path, TUI only)

Configure (from the folder holding sobol/ and Code/):
  python3 sobol/setup_paths.py --data-dir <this folder>/data --blender <blender 5.2> --python <python>
  python3 sobol/setup_paths.py --check
First render:
  python3 sobol/render_dumps.py <this folder>/example_run/run_0001 --name example \\
      --samples 32 --max-frames 10 --resolution 960x540

No Blender materials, textures or HDRI are included: Earth renders as a plain
sphere, grains in a plain rock colour, and the sky is black.
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=Path(hp.data_dir()) / "share")
    a = p.parse_args(argv)
    if not EXAMPLE_RUN.is_dir():
        sys.exit(f"example run not found: {EXAMPLE_RUN}")
    root = a.out / "honours_viz_pack"
    if root.exists():
        shutil.rmtree(root)
    ex = root / "example_run" / "run_0001"
    ex.mkdir(parents=True)
    dumps = sorted(EXAMPLE_RUN.glob("sobol_[0-9]*"))
    for f in dumps + [EXAMPLE_RUN / n for n in EXAMPLE_FILES]:
        shutil.copy2(f, ex / f.name)
    shape_dst = root / "data" / "BlenderConvert" / SHAPE
    shape_dst.parent.mkdir(parents=True)
    shutil.copy2(Path(hp.assets_dir()) / SHAPE, shape_dst)
    (root / "PACK_README.txt").write_text(PACK_README, encoding="utf-8")
    zip_path = Path(shutil.make_archive(str(a.out / "honours_viz_pack"), "zip", a.out, "honours_viz_pack"))
    print(f"wrote {zip_path} ({zip_path.stat().st_size / 1e6:.0f} MB; {len(dumps)} dumps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
