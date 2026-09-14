"""Headless per-sphere DEM render — not pasted into the Scripting tab.

Run with:
    blender.exe --background --python BlenderConvert/DEMHeadlessRender.py -- \\
        --grains-dir PATH --bodies-dir PATH --output-dir PATH \\
        [--resolution 1920x1080] [--samples 128] [--fps 24] \\
        [--max-frames N] [--camera-mode auto|grain_only]

Text-patches BlenderConvert/DEMGrainsBlenderEarthCam.py's GRAINS_DIR /
BODIES_CSV_DIR / CAMERA_MODE constants and exec()s it — the same technique
sobol/Analysis/run_demtocsv_batch.py already uses on DEMDumpConvert.py —
so grains + Earth + camera are built exactly as the interactive
Scripting-tab path builds them. Only render settings and the render call
are new here.
"""
import argparse
import re
import sys
import traceback
from pathlib import Path

import bpy


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--grains-dir", required=True)
    p.add_argument("--bodies-dir", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--resolution", default="1920x1080")
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--camera-mode", choices=("auto", "grain_only"), default="auto")
    return p.parse_args(argv)


def _patch_and_exec(script_path: Path, grains_dir: str, bodies_dir: str, camera_mode: str) -> None:
    src = script_path.read_text(encoding="utf-8")

    # GRAINS_DIR / BODIES_CSV_DIR are multi-line parenthesized string
    # literals (DEMGrainsBlenderEarthCam.py:21-28) -- replace the whole
    # "NAME = ( ... )" block. Safe because neither literal contains ")".
    src, n = re.subn(r"GRAINS_DIR\s*=\s*\([^)]*\)", f"GRAINS_DIR = {grains_dir!r}", src, count=1)
    if n != 1:
        raise RuntimeError(f"GRAINS_DIR pattern not found in {script_path}")
    src, n = re.subn(r"BODIES_CSV_DIR\s*=\s*\([^)]*\)", f"BODIES_CSV_DIR = {bodies_dir!r}", src, count=1)
    if n != 1:
        raise RuntimeError(f"BODIES_CSV_DIR pattern not found in {script_path}")

    if camera_mode == "grain_only":
        # CAMERA_MODE (line ~97) is a separate single-line switch from
        # IMPORT_SOLAR_SYSTEM -- it forces camera behavior, not whether
        # solar-system bodies are imported.
        src, n = re.subn(r"CAMERA_MODE\s*=\s*None", "CAMERA_MODE = 'grain_only'", src, count=1)
        if n != 1:
            raise RuntimeError(f"CAMERA_MODE pattern not found in {script_path}")

    exec(compile(src, str(script_path), "exec"), {"__name__": "__main__"})


def main() -> None:
    args = _parse_args()
    m = re.match(r"^(\d+)x(\d+)$", args.resolution)
    if not m:
        raise ValueError(f"--resolution must be WxH (got {args.resolution!r})")
    res_x, res_y = int(m.group(1)), int(m.group(2))

    script_path = Path(__file__).parent / "DEMGrainsBlenderEarthCam.py"
    grains_dir = str(Path(args.grains_dir).resolve()).replace("\\", "/") + "/"
    bodies_dir = str(Path(args.bodies_dir).resolve()).replace("\\", "/") + "/"
    # Resolve output-dir to an absolute path *before* exec'ing the DEM
    # script below -- DEMGrainsBlenderEarthCam.py loads TheEarth1.blend via
    # bpy.data.libraries.load(blend_path, link=False) (its line 558), which
    # as a side effect changes Blender's process working directory to that
    # .blend's folder. A relative output-dir
    # resolved (or mkdir'd) after that point silently lands under the wrong
    # directory instead of the caller's cwd -- confirmed live: PNGs wrote to
    # "C:\DEMCSVs\..." instead of the repo's "DEMCSVs\..." until this was
    # hoisted above the exec call.
    out_dir = Path(args.output_dir).resolve()
    _patch_and_exec(script_path, grains_dir, bodies_dir, args.camera_mode)

    scene = bpy.context.scene
    if args.max_frames is not None:
        scene.frame_end = min(scene.frame_end, scene.frame_start + args.max_frames - 1)

    scene.render.engine = 'CYCLES'
    scene.cycles.samples = args.samples
    scene.cycles.device = 'GPU'
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.fps = args.fps

    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.image_settings.media_type = 'IMAGE'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(out_dir) + "/frame_"

    print(
        f"[DEMHeadlessRender] Rendering frames {scene.frame_start}-{scene.frame_end} "
        f"at {res_x}x{res_y}, {args.samples} samples, to {out_dir}"
    )
    bpy.ops.render.render(animation=True)
    n_frames = scene.frame_end - scene.frame_start + 1
    print(f"[DEMHeadlessRender] Done — {n_frames} frame(s) written to {out_dir}")


if __name__ == "__main__":
    # Under `--background --python`, Blender exits 0 even when this script
    # raises an uncaught exception (verified live: a bare `raise` here still
    # produced a "Blender quit" / exit code 0 process, unless
    # --python-exit-code is passed by the caller). The CLI contract promises
    # "Exit code 0 on success, non-zero on failure" regardless of what flags
    # the caller passes, so failure must be turned into a nonzero exit
    # explicitly rather than relying on Blender's own uncaught-exception
    # handling. sys.exit(1) was verified live to set the process's exit code
    # correctly in 5.2.1 (a plain `sys.exit(1)` --python script returned
    # exit code 1), so no os._exit() fallback is needed here.
    try:
        main()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        sys.exit(1)
