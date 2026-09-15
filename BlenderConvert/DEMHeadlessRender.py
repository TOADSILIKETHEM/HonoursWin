"""Headless per-sphere DEM render — not pasted into the Scripting tab.

Run with:
    blender.exe --background --python BlenderConvert/DEMHeadlessRender.py -- \\
        --grains-dir PATH --bodies-dir PATH --output-dir PATH \\
        [--resolution 1920x1080] [--samples 500] [--fps 24] \\
        [--max-frames N] [--camera-mode auto|grain_only] \\
        [--encode-video] [--video-fps N]

Text-patches BlenderConvert/DEMGrainsBlenderEarthCam.py's GRAINS_DIR /
BODIES_CSV_DIR / CAMERA_MODE constants and exec()s it — the same technique
sobol/Analysis/run_demtocsv_batch.py already uses on DEMDumpConvert.py —
so grains + Earth + camera are built exactly as the interactive
Scripting-tab path builds them. Then applies World
"Deep Dark Space with Stars.001" (same HDRI as Apophisonly.blend),
sets Cycles to OPTIX (else CUDA) GPU-only, and renders.

With --encode-video, the just-rendered frame_*.png sequence is combined
into an MP4 (H264) via Blender's own VSE-scripted ffmpeg (no separate
ffmpeg install needed/expected on this machine) — an optional final
stage, off by default so re-encoding isn't forced on every tuning pass.
"""
import argparse
import re
import sys
import traceback
from pathlib import Path

try:
    import bpy
except ImportError:
    bpy = None

WORLD_NAME = "Deep Dark Space with Stars.001"
_HDRI_RELATIVE = Path(
    "Blenders/assets/hdrs/"
    "deep-dark-space-_d677e3ac-6716-4282-8978-9896d7f86c26/"
    "deep-dark-space-with-stars_4K_56e0040f-4645-4b62-b685-637b0eb970ed.exr"
)


def deep_dark_space_hdri_path(script_dir=None) -> Path:
    root = Path(script_dir) if script_dir is not None else Path(__file__).resolve().parent
    return root / _HDRI_RELATIVE


def setup_deep_dark_space_world(hdri_path=None) -> bool:
    """Assign scene World from the repo Deep Dark Space HDRI. False if missing."""
    path = Path(hdri_path) if hdri_path is not None else deep_dark_space_hdri_path()
    if not path.is_file():
        print(
            f"[DEMHeadlessRender] WARNING: HDRI not found at {path}; "
            "leaving default World"
        )
        return False
    if bpy is None:
        raise RuntimeError("bpy is required to apply the World")

    world = bpy.data.worlds.get(WORLD_NAME)
    if world is None:
        world = bpy.data.worlds.new(WORLD_NAME)
    if hasattr(world, "use_nodes"):
        world.use_nodes = True
    nt = world.node_tree
    if nt is None:
        raise RuntimeError(f"World {WORLD_NAME!r} has no node tree")
    nt.nodes.clear()
    nt.links.clear()

    output = nt.nodes.new("ShaderNodeOutputWorld")
    background = nt.nodes.new("ShaderNodeBackground")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    mapping = nt.nodes.new("ShaderNodeMapping")
    texcoord = nt.nodes.new("ShaderNodeTexCoord")

    abs_path = str(path.resolve()).replace("\\", "/")
    env.image = bpy.data.images.load(abs_path, check_existing=True)
    env.projection = "EQUIRECTANGULAR"
    background.inputs["Strength"].default_value = 1.0

    nt.links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], background.inputs["Color"])
    nt.links.new(background.outputs["Background"], output.inputs["Surface"])

    bpy.context.scene.world = world
    bpy.context.scene.view_settings.view_transform = "AgX"
    print(f"[DEMHeadlessRender] World {WORLD_NAME!r} from {abs_path}")
    return True


def setup_cycles_gpu(scene=None) -> str:
    """Enable Cycles on OPTIX, else CUDA. GPU only — no CPU hybrid. Raises if none."""
    if bpy is None:
        raise RuntimeError("bpy is required to enable Cycles GPU")

    scene = scene if scene is not None else bpy.context.scene
    scene.render.engine = "CYCLES"

    cycles_addon = bpy.context.preferences.addons.get("cycles")
    if cycles_addon is None:
        raise RuntimeError("Cycles add-on is not available")
    prefs = cycles_addon.preferences

    backend = None
    for compute in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = compute
        except Exception:
            continue
        if hasattr(prefs, "get_devices"):
            try:
                prefs.get_devices()
            except Exception:
                pass
        if hasattr(prefs, "refresh_devices"):
            try:
                prefs.refresh_devices()
            except Exception:
                pass
        gpu_devices = [d for d in prefs.devices if d.type == compute]
        if gpu_devices:
            backend = compute
            break

    if backend is None:
        scene.cycles.device = "CPU"
        raise RuntimeError("No OPTIX/CUDA GPU found for Cycles")

    for device in prefs.devices:
        device.use = device.type == backend
    scene.cycles.device = "GPU"
    enabled = [f"{d.name} ({d.type})" for d in prefs.devices if d.use]
    print(
        f"[DEMHeadlessRender] Cycles device=GPU backend={backend} enabled={enabled}"
    )
    return backend


def encode_video(out_dir: Path, n_frames: int, fps: int, video_name: str = "animation.mp4") -> Path:
    """Combine out_dir's frame_*.png sequence into an MP4 via Blender's VSE.

    No separate ffmpeg install needed/expected on this machine -- Blender
    ships its own and writes video directly through the sequencer, the
    same technique documented in Code/CLAUDE.md's "Combining a rendered
    image sequence into a video". Raises if the frame count on disk
    doesn't match n_frames -- a silent partial encode would be worse than
    a loud failure here.
    """
    if bpy is None:
        raise RuntimeError("bpy is required to encode video")

    frame_files = sorted(out_dir.glob("frame_*.png"))
    if not frame_files:
        raise RuntimeError(f"no frame_*.png files found in {out_dir} to encode")
    if len(frame_files) != n_frames:
        raise RuntimeError(
            f"expected {n_frames} rendered frame(s) in {out_dir}, found {len(frame_files)}"
        )

    scene = bpy.context.scene
    seq_ed = scene.sequence_editor or scene.sequence_editor_create()
    strip = seq_ed.strips.new_image(
        name="seq", filepath=str(frame_files[0]), channel=1, frame_start=1,
    )
    for f in frame_files[1:]:
        strip.elements.append(f.name)
    strip.frame_final_duration = len(frame_files)

    scene.frame_start, scene.frame_end = 1, len(frame_files)
    scene.render.use_sequencer = True
    # media_type must be set to 'VIDEO' before file_format='FFMPEG' is a
    # valid enum value (Blender 5.2.1: assigning file_format while
    # media_type is still 'IMAGE' raises "enum ... not found").
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.fps = fps

    video_path = out_dir / video_name
    scene.render.filepath = str(video_path)

    print(
        f"[DEMHeadlessRender] Encoding {len(frame_files)} frame(s) to "
        f"{video_path} at {fps} fps"
    )
    bpy.ops.render.render(animation=True)
    print(f"[DEMHeadlessRender] Video written to {video_path}")
    return video_path


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--grains-dir", required=True)
    p.add_argument("--bodies-dir", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--resolution", default="1920x1080")
    p.add_argument("--samples", type=int, default=500)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--camera-mode", choices=("auto", "grain_only"), default="auto")
    p.add_argument("--encode-video", action="store_true", default=False)
    p.add_argument("--video-fps", type=int, default=None)
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
    setup_deep_dark_space_world()

    scene = bpy.context.scene
    if args.max_frames is not None:
        scene.frame_end = min(scene.frame_end, scene.frame_start + args.max_frames - 1)

    setup_cycles_gpu(scene)
    scene.cycles.samples = args.samples
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
        f"at {res_x}x{res_y}, {args.samples} samples, GPU, to {out_dir}"
    )
    bpy.ops.render.render(animation=True)
    n_frames = scene.frame_end - scene.frame_start + 1
    print(f"[DEMHeadlessRender] Done — {n_frames} frame(s) written to {out_dir}")

    if args.encode_video:
        video_fps = args.video_fps if args.video_fps is not None else args.fps
        encode_video(out_dir, n_frames, video_fps)


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
