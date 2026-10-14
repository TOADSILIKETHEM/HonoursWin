"""Headless DEM render (composite or instance) — not pasted into the Scripting tab.

Run with:
    blender.exe --background --python BlenderConvert/DEMHeadlessRender.py -- \\
        --output-dir PATH \\
        [--viz-path composite|instance] \\
        [--manifest PATH/manifest.json] \\
        [--resolution 1920x1080] [--samples 124] [--fps 24] \\
        [--max-frames N] [--camera-mode auto|grain_only|earth_fixed|earth_chase] [--camera-fov DEG] \\
        [--device gpu|cpu] [--encode-video] [--video-fps N]

Text-patches the chosen Blender script's config constants and exec()s it —
the same technique sobol/Analysis/run_demtocsv_batch.py uses on
DEMDumpConvert.py:
  composite  -> DEMBulkVizBlender.py         (VIZ_MANIFEST, CAMERA_MODE, CAMERA_FOV_DEG)
  instance   -> DEMBulkInstanceBlender.py    (VIZ_MANIFEST, CAMERA_MODE, CAMERA_FOV_DEG,
                                              SLOWMO_FACTOR=1, RENDER_RESOLUTION)
GRAIN_COLOUR_VARIATION stays True. The headless driver does not patch it.
DEMGrainsBlenderEarthCam.py is the GUI hero-shot script. patch_script_source
("per_sphere") still rewrites its constants so the parity test can build the
reference scene; the CLI does not run that path.
Then applies World "Deep Dark Space with Stars.001" (same HDRI as
Apophisonly.blend), sets Cycles to the first GPU backend found (OPTIX, CUDA,
HIP, ONEAPI, METAL; GPU only, no CPU hybrid) or, with --device cpu, the CPU,
and renders. --device defaults to cycles_device in Code/local_paths.json.

With --encode-video, the just-rendered frame_*.png sequence is combined
into an MP4 (H264) via Blender's own VSE-scripted ffmpeg (no separate
ffmpeg install needed/expected on this machine) — an optional final
stage, off by default so re-encoding isn't forced on every tuning pass.
"""
import argparse
import json
import os
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

VIZ_PATHS = ("composite", "instance")
# "per_sphere" is not a CLI path. The parity test patches DEMGrainsBlenderEarthCam.py
# through SCRIPT_FOR_VIZ_PATH / patch_script_source and renders with render_prepared_scene.
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

# .blend / HDRI assets are untracked; Code/honours_paths.py says where
# (HONOURS_BLENDER_ASSETS_DIR > Code/local_paths.json > Max's OneDrive folder).
# Blender (Windows) and pytest (WSL) see that folder under different roots,
# which host_path() handles.
_CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)
import honours_paths  # noqa: E402

ASSETS_DIR = Path(honours_paths.host_path(honours_paths.assets_dir()))

# All patterned constants sit at column 0 in their scripts, exactly once.
_GRAINS_DIR_RE = r"(?m)^GRAINS_DIR\s*=\s*\([^)]*\)"
_BODIES_CSV_DIR_RE = r"(?m)^BODIES_CSV_DIR\s*=\s*\([^)]*\)"
_VIZ_MANIFEST_RE = r"(?m)^VIZ_MANIFEST\s*=\s*\([^)]*\)"
_CAMERA_MODE_RE = r"(?m)^CAMERA_MODE\s*=\s*None\b"
_SLOWMO_FACTOR_RE = r"(?m)^SLOWMO_FACTOR\s*=\s*\d+"
_RENDER_RESOLUTION_RE = r"(?m)^RENDER_RESOLUTION\s*=\s*\([^)]*\)"
_MAX_FRAMES_RE = r"(?m)^MAX_FRAMES\s*=\s*None\b"
_CAMERA_FOV_RE = r"(?m)^CAMERA_FOV_DEG\s*=\s*None\b"

CAMERA_MODES = ("auto", "grain_only", "earth_fixed", "earth_chase")
DEFAULT_CAMERA_FOV_DEG = 70.0  # = DEMCinematicSetup.CAMERA_FOV_DEG


# Blender's startup scene (loaded by `blender --background` with no .blend).
# The DEM scripts make their own camera (DEM_TrackCam) and lights, so these
# are never wanted; the default Light otherwise adds an unphysical point lamp.
_STARTUP_DEFAULTS = (("Cube", "MESH"), ("Camera", "CAMERA"), ("Light", "LIGHT"))


def remove_startup_defaults() -> list:
    """Delete the startup Cube/Camera/Light objects and their now-unused data. Returns names removed."""
    if bpy is None:
        raise RuntimeError("bpy is required to clear the startup scene")
    data_for_type = {"MESH": bpy.data.meshes, "CAMERA": bpy.data.cameras, "LIGHT": bpy.data.lights}
    removed = []
    for name, obj_type in _STARTUP_DEFAULTS:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != obj_type:
            continue
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            data_for_type[obj_type].remove(data)
        removed.append(name)
    return removed


def require_camera(scene) -> None:
    """The startup Camera is removed before the viz script runs (self-contained
    .blend), so a script that skipped its tracking camera leaves none."""
    if scene.camera is None:
        raise RuntimeError(
            "no scene camera: the viz script skipped its tracking camera "
            "(no grain .npz files in the manifest's grains_dir, or SETUP_CAMERA = False); "
            "see the WARNING above in this log")


def deep_dark_space_hdri_path(script_dir=None) -> Path:
    root = Path(script_dir) if script_dir is not None else ASSETS_DIR
    return root / _HDRI_RELATIVE


def _set_black_world() -> None:
    """Plain black World -- Blender's default grey one would light the scene like an overcast sky."""
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)


def setup_deep_dark_space_world(hdri_path=None) -> bool:
    """Assign scene World from the repo Deep Dark Space HDRI. False if missing."""
    path = Path(hdri_path) if hdri_path is not None else deep_dark_space_hdri_path()
    if not path.is_file():
        print(
            f"[DEMHeadlessRender] WARNING: HDRI not found at {path}; "
            "black sky instead"
        )
        if bpy is not None:
            _set_black_world()
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


# OPTIX/CUDA first (NVIDIA, Max's RTX 4050); HIP/ONEAPI/METAL let AMD/Intel/Apple
# GPUs render too.
GPU_BACKENDS = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")


def setup_cycles_gpu(scene=None) -> str:
    """Enable Cycles on the first GPU backend with devices (OPTIX, else CUDA, then
    HIP/ONEAPI/METAL). GPU only — no CPU hybrid. Raises if none."""
    if bpy is None:
        raise RuntimeError("bpy is required to enable Cycles GPU")

    scene = scene if scene is not None else bpy.context.scene
    scene.render.engine = "CYCLES"

    cycles_addon = bpy.context.preferences.addons.get("cycles")
    if cycles_addon is None:
        raise RuntimeError("Cycles add-on is not available")
    prefs = cycles_addon.preferences

    backend = None
    for compute in GPU_BACKENDS:
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
        raise RuntimeError(
            f"No GPU found for Cycles (tried {'/'.join(GPU_BACKENDS)}); use --device cpu"
        )

    for device in prefs.devices:
        device.use = device.type == backend
    scene.cycles.device = "GPU"
    enabled = [f"{d.name} ({d.type})" for d in prefs.devices if d.use]
    print(
        f"[DEMHeadlessRender] Cycles device=GPU backend={backend} enabled={enabled}"
    )
    return backend


def setup_cycles_cpu(scene=None) -> str:
    """Cycles on CPU only -- for machines without a supported GPU (slow; use low --samples)."""
    if bpy is None:
        raise RuntimeError("bpy is required to set the Cycles device")
    scene = scene if scene is not None else bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    print("[DEMHeadlessRender] Cycles device=CPU")
    return "CPU"


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


def render_banner(viz_path, frame_start, frame_end, res_x, res_y, samples, device, out_dir) -> str:
    return (f"[DEMHeadlessRender] Rendering {viz_path} frames {frame_start}-{frame_end} "
            f"at {res_x}x{res_y}, {samples} samples, {device.upper()}, to {out_dir}")


def apply_slowmo_range(scene, slowmo) -> None:
    """With SLOWMO_FACTOR = N, timeline frame N*k shows dump k (frame_map 100 -> 100*N);
    frames 1..N-1 would only hold dump 1, so start the render on it."""
    if slowmo > 1:
        scene.frame_start = slowmo


def apply_resume(scene, resume) -> None:
    """Skip frames whose PNG is already in the output dir (carry on an interrupted render)."""
    if resume:
        scene.render.use_overwrite = False
        scene.render.use_placeholder = False


# Earth's textures (up to 21600x10800, ~3 GB) plus the volume atmosphere overflow a
# 6 GB laptop GPU; capped at 4K a frame of Mia's 40k flyby went 41 -> 20 s with
# identical pixels (Earth is ~130 px across at 1080p). Persistent data keeps the
# synced scene between frames (-> 16 s, max diff 1/255). Benchmarks 2026-10-13.
# The cap is per image (cap_image_textures) so the 8K clouds stay full size; resampling
# softens city lights/stars slightly vs the old global cap (frame 44 mean 0.72/255).
TEXTURE_MAX_PX = 4096
# Image names kept at full size (case-insensitive substring): the cloud layer, at Max's call.
TEXTURE_CAP_EXEMPT = ("clouds",)
# adaptive sampling + denoise are on, so 124 looks like 1000 (mean diff ~0.2/255, sample sweep 2026-10-13)
DEFAULT_SAMPLES = 124


# TheEarth1.blend's Surface/Clouds/Atmosphere dice at 1 px per edge (adaptive
# subdivision + true displacement), so triangle count and memory grow with Earth's
# on-screen area: on the 40k flyby approach 10 -> 20 GB and 15 -> 58 s/frame, then
# swapping. At 4 px a frame-44 close-up differs by 0.25/255 mean and memory stays flat.
ADAPTIVE_PIXEL_SIZE_MIN = 4.0


def _has_displacement(obj) -> bool:
    for slot in obj.material_slots:
        tree = getattr(slot.material, "node_tree", None) if slot.material else None
        for node in (tree.nodes if tree else ()):
            if node.type == "OUTPUT_MATERIAL" and any(
                    i.name == "Displacement" and i.is_linked for i in node.inputs):
                return True
    return False


def coarsen_adaptive_subdivision(scene) -> None:
    """Floor adaptive dicing at ADAPTIVE_PIXEL_SIZE_MIN px; off where no material displaces
    (a volume-only atmosphere gains nothing from dicing)."""
    for obj in scene.objects:
        for mod in getattr(obj, "modifiers", ()):
            if mod.type != "SUBSURF" or not getattr(mod, "use_adaptive_subdivision", False):
                continue
            if not _has_displacement(obj):
                mod.use_adaptive_subdivision = False
            elif mod.adaptive_space == "PIXEL" and mod.adaptive_pixel_size < ADAPTIVE_PIXEL_SIZE_MIN:
                mod.adaptive_pixel_size = ADAPTIVE_PIXEL_SIZE_MIN


def apply_gpu_denoise(scene) -> None:
    """Run OIDN on the GPU: on the CPU it was ~7 of 9.5 s per 1080p frame (40k flyby,
    RTX 4050); on the GPU 2.6 s with the same pixels (mean diff 0.01/255, 2026-10-13)."""
    scene.cycles.denoising_use_gpu = True


def cap_image_textures(images) -> None:
    """Shrink file images whose long side exceeds TEXTURE_MAX_PX, keeping aspect, except
    TEXTURE_CAP_EXEMPT. Per image rather than Cycles' global texture_limit_render (which can't
    exempt one), and it frees Blender's own copy too, not just the GPU's."""
    for img in images:
        w, h = img.size
        if img.source != "FILE" or max(w, h) <= TEXTURE_MAX_PX:
            continue
        if any(tag in img.name.lower() for tag in TEXTURE_CAP_EXEMPT):
            continue
        k = TEXTURE_MAX_PX / max(w, h)
        img.scale(max(1, round(w * k)), max(1, round(h * k)))


def apply_render_speedups(scene) -> None:
    """Keep the scene on the GPU between frames, cap image textures at 4K and
    coarsen adaptive subdivision (see the constants above)."""
    scene.render.use_persistent_data = True
    scene.cycles.texture_limit_render = "OFF"  # cap_image_textures() caps per image instead
    coarsen_adaptive_subdivision(scene)


def validate_args(args) -> None:
    """Cross-flag rules argparse can't express. Raises ValueError."""
    if args.slowmo < 1:
        raise ValueError("--slowmo must be >= 1")
    if args.slowmo != 1 and args.viz_path != "instance":
        raise ValueError("--slowmo needs --viz-path instance (composite holds each dump)")
    if not 1.0 <= args.camera_fov <= 150.0:
        raise ValueError("--camera-fov must be between 1 and 150 degrees")
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
    p.add_argument("--viz-path", choices=VIZ_PATHS, default="instance")
    p.add_argument("--manifest", default=None)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--resolution", default="1920x1080")
    p.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--slowmo", type=int, default=1,
                   help="instance only: N timeline frames per dump (same sim time, N x the frames; "
                        "in-betweens interpolated on the grains' Bezier curves, not simulated)")
    p.add_argument("--camera-mode", choices=CAMERA_MODES, default="auto",
                   help="auto: track Apophis (Earth-side view when Earth is in the bodies CSV); "
                        "grain_only: track Apophis, no Earth framing; earth_fixed: camera still "
                        "relative to Earth, framed on the path near closest approach (Apophis is "
                        "a few pixels); earth_chase: behind Apophis, aimed at Earth's centre")
    p.add_argument("--camera-fov", type=float, default=DEFAULT_CAMERA_FOV_DEG,
                   help="field of view across the long side, degrees (earth_chase: narrower = "
                        "telephoto, same Apophis size, bigger Earth)")
    p.add_argument("--device", choices=("gpu", "cpu"), default=honours_paths.cycles_device(),
                   help="Cycles device: gpu (OPTIX/CUDA/HIP/ONEAPI/METAL) or cpu (no GPU); "
                        "default cycles_device from Code/local_paths.json, else gpu")
    p.add_argument("--encode-video", action="store_true", default=False)
    p.add_argument("--resume", action="store_true", default=False,
                   help="keep frame_*.png already in --output-dir and render only the missing ones")
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
                        manifest=None, camera_mode="auto", resolution=None, max_frames=None,
                        slowmo=1, camera_fov=DEFAULT_CAMERA_FOV_DEG):
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
        # (--slowmo N: N timeline frames per dump, in-betweens on the grains' Bezier curves)
        src = _sub_exactly_once(_SLOWMO_FACTOR_RE, f"SLOWMO_FACTOR = {int(slowmo)}", src, "SLOWMO_FACTOR")
        if resolution is not None:
            src = _sub_exactly_once(
                _RENDER_RESOLUTION_RE,
                f"RENDER_RESOLUTION = ({int(resolution[0])}, {int(resolution[1])})",
                src, "RENDER_RESOLUTION",
            )
    if camera_mode != "auto":
        # CAMERA_MODE is a separate switch from IMPORT_SOLAR_SYSTEM -- it
        # forces camera behavior, not whether solar-system bodies are imported.
        if camera_mode not in CAMERA_MODES:
            raise ValueError(f"camera_mode {camera_mode!r} not in {CAMERA_MODES}")
        src = _sub_exactly_once(_CAMERA_MODE_RE, f"CAMERA_MODE = {camera_mode!r}", src, "CAMERA_MODE")
    if viz_path != "per_sphere" and float(camera_fov) != DEFAULT_CAMERA_FOV_DEG:
        src = _sub_exactly_once(_CAMERA_FOV_RE, f"CAMERA_FOV_DEG = {float(camera_fov)!r}", src, "CAMERA_FOV_DEG")
    return src


# Stand-in grain colour when 11.blend is absent: DEMGrainsBlenderEarthCam.py's
# GRAIN_COLOR fallback, so both paths degrade to the same look.
_ROCK_STANDIN_RGBA = (0.35, 0.30, 0.25, 1.0)


def _make_rock_standin_material():
    mat = bpy.data.materials.new(ROCK_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = _ROCK_STANDIN_RGBA
    bsdf.inputs["Roughness"].default_value = 0.9
    return mat


def ensure_procedural_rock_material(blend_path=None) -> None:
    """Append "Procedural rock" from Blenders/11.blend unless already present.

    No 11.blend (e.g. the shared asset pack, which leaves materials out): build a
    plain stand-in under the same name so the instance path still renders."""
    if bpy is None:
        raise RuntimeError("bpy is required to append the Procedural rock material")
    if bpy.data.materials.get(ROCK_MATERIAL_NAME) is not None:
        return
    path = (
        Path(blend_path) if blend_path is not None
        else ASSETS_DIR / _ROCK_MATERIAL_BLEND_RELATIVE
    )
    if not path.is_file():
        print(f"[DEMHeadlessRender] WARNING: {path} not found -- plain stand-in "
              f"{ROCK_MATERIAL_NAME!r} material (no procedural rock texture)")
        _make_rock_standin_material()
        return
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


def render_prepared_scene(scene, *, viz_path, out_dir, res_x, res_y, samples, fps, device,
                          max_frames=None, slowmo=1, resume=False, encode=False, video_fps=None):
    """Cycles settings and the PNG render, after a viz script has built the scene.

    The parity test calls this for the hero script (viz_path "per_sphere"), which
    the CLI does not run. Bulk paths lock the interface because their
    frame_change_pre handlers rewrite meshes during the animation render.
    """
    require_camera(scene)
    if viz_path == "instance":
        apply_slowmo_range(scene, slowmo)
    if max_frames is not None:
        scene.frame_end = min(scene.frame_end, scene.frame_start + max_frames - 1)

    if device == "cpu":
        setup_cycles_cpu(scene)
    else:
        setup_cycles_gpu(scene)
        apply_gpu_denoise(scene)
    scene.cycles.samples = samples
    apply_render_speedups(scene)
    cap_image_textures(bpy.data.images)
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    if viz_path != "per_sphere":
        scene.render.use_lock_interface = True

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.image_settings.media_type = 'IMAGE'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(out_dir) + "/frame_"
    apply_resume(scene, resume)

    print(render_banner(viz_path, scene.frame_start, scene.frame_end, res_x, res_y,
                        samples, device, out_dir))
    bpy.ops.render.render(animation=True)
    n_frames = scene.frame_end - scene.frame_start + 1
    print(f"[DEMHeadlessRender] Done — {n_frames} frame(s) written to {out_dir}")

    if encode:
        encode_video(out_dir, n_frames, video_fps if video_fps is not None else fps)


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
        "camera_fov": args.camera_fov,
        "resolution": (res_x, res_y),
        "max_frames": args.max_frames,
        "manifest": str(Path(args.manifest).resolve()).replace("\\", "/"),
    }
    if args.viz_path == "instance":
        patch_kwargs["slowmo"] = args.slowmo

    removed = remove_startup_defaults()
    if removed:
        print(f"[DEMHeadlessRender] removed startup objects: {', '.join(removed)}")

    if args.viz_path == "instance":
        ensure_procedural_rock_material()

    src = patch_script_source(
        args.viz_path, script_path.read_text(encoding="utf-8"), **patch_kwargs
    )
    exec(compile(src, str(script_path), "exec"), {"__name__": "__main__", "__file__": str(script_path)})
    setup_deep_dark_space_world()
    render_prepared_scene(
        bpy.context.scene, viz_path=args.viz_path, out_dir=out_dir, res_x=res_x, res_y=res_y,
        samples=args.samples, fps=args.fps, device=args.device, max_frames=args.max_frames,
        slowmo=args.slowmo, resume=args.resume, encode=args.encode_video, video_fps=args.video_fps,
    )


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
