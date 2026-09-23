"""Headless DEM render (per-sphere, composite, or instance) — not pasted into the Scripting tab.

Run with:
    blender.exe --background --python BlenderConvert/DEMHeadlessRender.py -- \\
        --output-dir PATH \\
        [--viz-path per_sphere|composite|instance] \\
        [--grains-dir PATH --bodies-dir PATH]      (per_sphere) \\
        [--manifest PATH/manifest.json]            (composite / instance) \\
        [--resolution 1920x1080] [--samples 500] [--fps 24] \\
        [--max-frames N] [--camera-mode auto|grain_only] \\
        [--encode-video] [--video-fps N]

Text-patches the chosen Blender script's config constants and exec()s it —
the same technique sobol/Analysis/run_demtocsv_batch.py uses on
DEMDumpConvert.py:
  per_sphere -> DEMGrainsBlenderEarthCam.py  (GRAINS_DIR, BODIES_CSV_DIR, CAMERA_MODE,
                                              MAX_FRAMES)
  composite  -> DEMBulkVizBlender.py         (VIZ_MANIFEST, CAMERA_MODE)
  instance   -> DEMBulkInstanceBlender.py    (VIZ_MANIFEST, CAMERA_MODE,
                                              SLOWMO_FACTOR=1, RENDER_RESOLUTION)
Then applies World "Deep Dark Space with Stars.001" (same HDRI as
Apophisonly.blend), sets Cycles to OPTIX (else CUDA) GPU-only, and renders.

With --encode-video, the just-rendered frame_*.png sequence is combined
into an MP4 (H264) via Blender's own VSE-scripted ffmpeg (no separate
ffmpeg install needed/expected on this machine) — an optional final
stage, off by default so re-encoding isn't forced on every tuning pass.
"""
import argparse
import json
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

VIZ_PATHS = ("per_sphere", "composite", "instance")
SCRIPT_FOR_VIZ_PATH = {
    "per_sphere": "DEMGrainsBlenderEarthCam.py",
    "composite": "DEMBulkVizBlender.py",
    "instance": "DEMBulkInstanceBlender.py",
}
# Same file and material name as DEMGrainsBlenderEarthCam.py's
# ROCK_MATERIAL_BLEND_PATH / ROCK_MATERIAL_NAME. DEMBulkInstanceBlender.py
# refuses to run without this material and deliberately never auto-appends
# it (several similarly named rock materials exist), so the headless wrapper
# appends it from this one known source before exec.
ROCK_MATERIAL_NAME = "Procedural rock"
_ROCK_MATERIAL_BLEND_RELATIVE = Path("Blenders/11.blend")

# All patterned constants sit at column 0 in their scripts, exactly once.
_GRAINS_DIR_RE = r"(?m)^GRAINS_DIR\s*=\s*\([^)]*\)"
_BODIES_CSV_DIR_RE = r"(?m)^BODIES_CSV_DIR\s*=\s*\([^)]*\)"
_VIZ_MANIFEST_RE = r"(?m)^VIZ_MANIFEST\s*=\s*\([^)]*\)"
_CAMERA_MODE_RE = r"(?m)^CAMERA_MODE\s*=\s*None\b"
_SLOWMO_FACTOR_RE = r"(?m)^SLOWMO_FACTOR\s*=\s*\d+"
_RENDER_RESOLUTION_RE = r"(?m)^RENDER_RESOLUTION\s*=\s*\([^)]*\)"
_MAX_FRAMES_RE = r"(?m)^MAX_FRAMES\s*=\s*None\b"


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


def validate_args(args) -> None:
    """Cross-flag rules argparse can't express. Raises ValueError."""
    if args.viz_path == "per_sphere":
        if not args.grains_dir or not args.bodies_dir:
            raise ValueError("--viz-path per_sphere requires --grains-dir and --bodies-dir")
        return
    if not args.manifest:
        raise ValueError(f"--viz-path {args.viz_path} requires --manifest")
    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        raise ValueError(f"--manifest not found: {manifest_path}")
    viz_mode = json.loads(manifest_path.read_text(encoding="utf-8")).get("viz_mode")
    if viz_mode != args.viz_path:
        raise ValueError(
            f"manifest viz_mode={viz_mode!r} does not match --viz-path {args.viz_path}"
        )


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--viz-path", choices=VIZ_PATHS, default="per_sphere")
    p.add_argument("--manifest", default=None)
    p.add_argument("--grains-dir", default=None)
    p.add_argument("--bodies-dir", default=None)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--resolution", default="1920x1080")
    p.add_argument("--samples", type=int, default=500)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--camera-mode", choices=("auto", "grain_only"), default="auto")
    p.add_argument("--encode-video", action="store_true", default=False)
    p.add_argument("--video-fps", type=int, default=None)
    args = p.parse_args(argv)
    validate_args(args)
    return args


def parse_resolution(text: str):
    m = re.match(r"^(\d+)x(\d+)$", text)
    if not m:
        raise ValueError(f"--resolution must be WxH (got {text!r})")
    return int(m.group(1)), int(m.group(2))


def _sub_exactly_once(pattern: str, replacement: str, src: str, label: str) -> str:
    n = len(re.findall(pattern, src))
    if n != 1:
        raise RuntimeError(f"{label} pattern matched {n} time(s), expected exactly 1")
    # A function replacement keeps backslashes in Windows paths literal.
    return re.sub(pattern, lambda _m: replacement, src)


def patch_script_source(viz_path, src, *, grains_dir=None, bodies_dir=None,
                        manifest=None, camera_mode="auto", resolution=None, max_frames=None):
    """Return src with this path's config constants replaced. Pure — no bpy."""
    if viz_path == "per_sphere":
        src = _sub_exactly_once(_GRAINS_DIR_RE, f"GRAINS_DIR = {grains_dir!r}", src, "GRAINS_DIR")
        src = _sub_exactly_once(
            _BODIES_CSV_DIR_RE, f"BODIES_CSV_DIR = {bodies_dir!r}", src, "BODIES_CSV_DIR"
        )
        if max_frames is not None:
            # per_sphere keyframes every grain file up front, so the limit has
            # to reach the builder -- clamping scene.frame_end afterwards (as
            # main() also does) still pays for building every frame. Composite
            # and instance load each frame lazily in frame_change_pre, so they
            # need no equivalent.
            src = _sub_exactly_once(
                _MAX_FRAMES_RE, f"MAX_FRAMES = {int(max_frames)}", src, "MAX_FRAMES"
            )
    else:
        src = _sub_exactly_once(_VIZ_MANIFEST_RE, f"VIZ_MANIFEST = {manifest!r}", src, "VIZ_MANIFEST")
    if viz_path == "instance":
        # One timeline frame == one sim frame, so --max-frames and the TUI's
        # frame count stay correct.
        src = _sub_exactly_once(_SLOWMO_FACTOR_RE, "SLOWMO_FACTOR = 1", src, "SLOWMO_FACTOR")
        if resolution is not None:
            src = _sub_exactly_once(
                _RENDER_RESOLUTION_RE,
                f"RENDER_RESOLUTION = ({int(resolution[0])}, {int(resolution[1])})",
                src, "RENDER_RESOLUTION",
            )
    if camera_mode == "grain_only":
        # CAMERA_MODE is a separate switch from IMPORT_SOLAR_SYSTEM -- it
        # forces camera behavior, not whether solar-system bodies are imported.
        src = _sub_exactly_once(_CAMERA_MODE_RE, "CAMERA_MODE = 'grain_only'", src, "CAMERA_MODE")
    return src


def ensure_procedural_rock_material(blend_path=None) -> None:
    """Append "Procedural rock" from Blenders/11.blend unless already present."""
    if bpy is None:
        raise RuntimeError("bpy is required to append the Procedural rock material")
    if bpy.data.materials.get(ROCK_MATERIAL_NAME) is not None:
        return
    path = (
        Path(blend_path) if blend_path is not None
        else Path(__file__).resolve().parent / _ROCK_MATERIAL_BLEND_RELATIVE
    )
    if not path.is_file():
        raise RuntimeError(f"{path} not found -- needed for {ROCK_MATERIAL_NAME!r} (instance path)")
    found = False
    with bpy.data.libraries.load(str(path).replace("\\", "/"), link=False) as (data_from, data_to):
        if ROCK_MATERIAL_NAME in data_from.materials:
            data_to.materials = [ROCK_MATERIAL_NAME]
            found = True
    if not found or bpy.data.materials.get(ROCK_MATERIAL_NAME) is None:
        raise RuntimeError(f"material {ROCK_MATERIAL_NAME!r} not found in {path}")


def _line_buffer_std_streams() -> None:
    """Flush print() output per line. Blender's Python block-buffers stdout
    into a pipe (and ignores PYTHONUNBUFFERED), so the TUI's render.log and
    live status line would otherwise only see output when Blender exits."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(line_buffering=True)


def main() -> None:
    _line_buffer_std_streams()
    args = _parse_args()
    res_x, res_y = parse_resolution(args.resolution)
    script_dir = Path(__file__).resolve().parent
    script_path = script_dir / SCRIPT_FOR_VIZ_PATH[args.viz_path]

    # Resolve every path *before* exec'ing the DEM script: those scripts load
    # .blend libraries (TheEarth1.blend, 11.blend) via
    # bpy.data.libraries.load(..., link=False), which changes Blender's
    # process working directory. A relative path resolved after that silently
    # lands under the wrong directory -- confirmed live in v1: PNGs wrote to
    # "C:\DEMCSVs\..." until output-dir resolution was hoisted above exec.
    out_dir = Path(args.output_dir).resolve()
    patch_kwargs = {
        "camera_mode": args.camera_mode,
        "resolution": (res_x, res_y),
        "max_frames": args.max_frames,
    }
    if args.viz_path == "per_sphere":
        patch_kwargs["grains_dir"] = str(Path(args.grains_dir).resolve()).replace("\\", "/") + "/"
        patch_kwargs["bodies_dir"] = str(Path(args.bodies_dir).resolve()).replace("\\", "/") + "/"
    else:
        patch_kwargs["manifest"] = str(Path(args.manifest).resolve()).replace("\\", "/")

    if args.viz_path == "instance":
        ensure_procedural_rock_material()

    src = patch_script_source(
        args.viz_path, script_path.read_text(encoding="utf-8"), **patch_kwargs
    )
    exec(compile(src, str(script_path), "exec"), {"__name__": "__main__", "__file__": str(script_path)})
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
    if args.viz_path != "per_sphere":
        # The bulk scripts' frame_change_pre handlers rewrite mesh data between
        # frames during the animation render; lock the interface so the render
        # never reads half-updated geometry.
        scene.render.use_lock_interface = True

    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.image_settings.media_type = 'IMAGE'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(out_dir) + "/frame_"

    print(
        f"[DEMHeadlessRender] Rendering {args.viz_path} frames {scene.frame_start}-{scene.frame_end} "
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
