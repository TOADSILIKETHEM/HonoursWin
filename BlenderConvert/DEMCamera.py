import bpy
import math
import os
import glob
import numpy as np
from mathutils import Vector

# ── Configuration ──────────────────────────────────────────────────────────────
CAMERA_NAME        = 'DEM_TrackCam'

# Horizontal field of view (degrees).  35° half-FOV horizontal, ~21.5° vertical
# on a 16:9 render.  Earth is offset horizontally, so it uses the wide direction.
CAMERA_FOV_DEG     = 70.0

# Distance from the GRAIN CORE to the camera in Blender Units.
# 50 BU = 1 km at GRAIN_VIS_SCALE=50.  The core (dense cluster) stays centred
# and prominent at this distance throughout the run.
CAM_DIST_BU        = 150.0

# Degrees the camera is nudged from the anti-Earth axis toward the ecliptic
# perpendicular.  This makes Earth appear this many degrees off to the side of
# the grain core.  22° keeps Earth well inside the 35° horizontal half-FOV at
# closest approach while leaving a clear gap next to the grain body.
CAM_ANGLE_DEG      = 30.0

# Name of the Earth Empty created by DEMGrainsBlenderEarth.py.
EARTH_EMPTY_NAME   = 'Earth'

# Path to the grain npz folder — MUST match GRAINS_DIR in DEMGrainsBlenderEarth.py.
GRAIN_DIR = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/'
    'sobol_20260705_131545_baseline_58deg/run_0001_grains_output/'
)

# None = auto: Earth-tracking if Earth Empty exists, else grain-only orbit.
# 'earth_track' | 'grain_only' force a mode.
CAMERA_MODE = None

# Grain-only camera (apophis_only runs): fixed offset from dense core, no Earth framing.
CAM_GRAIN_ONLY_AZIMUTH_DEG   = 45.0
CAM_GRAIN_ONLY_ELEVATION_DEG = 20.0

# Fraction of grains (closest to the CoM) used to estimate the dense core.
# 0.80 = use the 80% of grains nearest the mass-weighted CoM (origin).  This
# trims away highly-scattered breakup ejecta so the camera tracks the compact
# nucleus, not empty space between fragments.
CORE_GRAIN_FRACTION = 0.80

# Smooth all camera F-curves after keyframing.
SMOOTH_CAMERA      = True
LOCATION_INTERP    = 'BEZIER'
LOCATION_HANDLE    = 'AUTO_CLAMPED'
ROTATION_INTERP    = 'LINEAR'   # LINEAR = SLERP between keyframes; eliminates
                                # Bézier component-wise roll artifacts during
                                # the large pan at closest approach.

CAM_CLIP_START     = 0.01
CAM_CLIP_END       = 20_000_000.0

# Fill light — parented to the camera so it co-moves each frame automatically.
# Illuminates the camera-facing side of Apophis without extra keyframes.
SETUP_CAM_FILL_LIGHT  = True
CAM_FILL_LIGHT_NAME   = 'DEM_CamFill'
CAM_FILL_LIGHT_TYPE   = 'POINT'   # POINT, SPOT, AREA, or SUN
CAM_FILL_LIGHT_ENERGY = 20000.0
# ─────────────────────────────────────────────────────────────────────────────
# WHY THE CAMERA TRACKS THE GRAIN CORE, NOT THE ORIGIN
# ─────────────────────────────────────────────────────────────────────────────
# During Apophis's tidal breakup, the dense grain nucleus physically migrates
# away from the mathematical mass-weighted CoM (origin).  By frame ~200 the
# core has already drifted ~20 BU; by closest approach (~frame 1125) it sits
# ~95 BU from the origin — meaning NO grain is within 88 BU of the origin.
# Aiming the camera at the origin therefore shows empty space while the grain
# cluster appears off to the side.
#
# Fix: each frame, load the grain npz file, sort grains by distance from the CoM,
# take the closest CORE_GRAIN_FRACTION of them, and use their centroid as both
# the camera aim point and the centre for distance computation.  This guarantees
# the dense nucleus is always locked to the centre of the frame.
#
# BARREL ROLL NOTE
# ─────────────────
# The camera pans ~102° from frame 0 (Earth far, ~100° from closest-approach
# direction) to frame 1125 (closest approach).  Each keyframe's orientation is
# computed independently with to_track_quat('-Z', 'Y') — local -Z toward the
# grain core, local +Y toward world +Z — giving a correct upright frame at
# every keyframe.  Quaternion continuity enforcement (negate if dot < 0 with
# previous frame) ensures consecutive keyframes are in the same hemisphere.
# ROTATION_INTERP='LINEAR' gives pure SLERP between keyframes, avoiding the
# component-wise Bézier artifacts that produced the earlier barrel roll.
# ─────────────────────────────────────────────────────────────────────────────

earth_empty = bpy.data.objects.get(EARTH_EMPTY_NAME)
_use_earth_track = (
    CAMERA_MODE == 'earth_track'
    if CAMERA_MODE in ('earth_track', 'grain_only')
    else earth_empty is not None
)
if CAMERA_MODE == 'earth_track' and earth_empty is None:
    raise RuntimeError(
        f'CAMERA_MODE="earth_track" but "{EARTH_EMPTY_NAME}" not found. '
        'Run DEMGrainsBlenderEarth.py on a full solar-system batch first.'
    )
if _use_earth_track:
    print(f'Camera mode: Earth-tracking (using "{EARTH_EMPTY_NAME}" keyframes).')
else:
    print(
        'Camera mode: grain-only orbit '
        f'(az={CAM_GRAIN_ONLY_AZIMUTH_DEG}°, el={CAM_GRAIN_ONLY_ELEVATION_DEG}°).'
    )

# ── Load grain npz files (sorted, same order as DEMGrainsBlenderEarth.py) ────
grain_files = sorted(glob.glob(os.path.join(GRAIN_DIR, '*.npz')))
if not grain_files:
    raise RuntimeError(
        f'No grain npz files found in {GRAIN_DIR}\n'
        'Set GRAIN_DIR to match GRAINS_DIR in DEMGrainsBlenderEarth.py '
        '(CSV-era grain folders must be reconverted with DEMDumpConvert.py).'
    )
print(f'Found {len(grain_files)} grain npz file(s) in {GRAIN_DIR}')


def _grain_core(grain_path, fraction):
    """Return the centroid of the closest `fraction` of grains to the CoM."""
    d = np.load(grain_path)
    pts = np.column_stack([d['x_vis'], d['y_vis'], d['z_vis']])
    order = np.argsort(np.sqrt((pts * pts).sum(axis=1)), kind='stable')
    n = max(1, int(len(pts) * fraction))
    return Vector(pts[order[:n]].mean(axis=0).tolist())


scene   = bpy.context.scene
f_start = scene.frame_start
f_end   = scene.frame_end

n_frames   = f_end - f_start + 1
n_csvs     = len(grain_files)
if n_frames != n_csvs:
    print(
        f'WARNING: scene has {n_frames} frames but {n_csvs} grain files. '
        'Using min of the two.'
    )

# ── Create / reuse camera ────────────────────────────────────────────────────
cam_data = bpy.data.cameras.get(CAMERA_NAME)
if cam_data is None:
    cam_data = bpy.data.cameras.new(CAMERA_NAME)
cam_data.lens_unit  = 'FOV'
cam_data.angle      = math.radians(CAMERA_FOV_DEG)
cam_data.clip_start = CAM_CLIP_START
cam_data.clip_end   = CAM_CLIP_END

cam_obj = bpy.data.objects.get(CAMERA_NAME)
if cam_obj is None:
    cam_obj = bpy.data.objects.new(CAMERA_NAME, cam_data)
    scene.collection.objects.link(cam_obj)
else:
    cam_obj.data = cam_data

cam_obj.rotation_mode = 'QUATERNION'
scene.camera = cam_obj

print(f'Camera "{CAMERA_NAME}" ready — keyframing {min(n_frames, n_csvs)} frames ...')

angle_rad = math.radians(CAM_ANGLE_DEG)
cos_a     = math.cos(angle_rad)
sin_a     = math.sin(angle_rad)
_Z        = Vector((0.0, 0.0, 1.0))
_X        = Vector((1.0, 0.0, 0.0))

if not _use_earth_track:
    az_rad = math.radians(CAM_GRAIN_ONLY_AZIMUTH_DEG)
    el_rad = math.radians(CAM_GRAIN_ONLY_ELEVATION_DEG)
    _grain_only_offset = Vector((
        math.cos(el_rad) * math.cos(az_rad),
        math.cos(el_rad) * math.sin(az_rad),
        math.sin(el_rad),
    )).normalized()


def _apply_interp(obj, data_path, interp, handle=None):
    if not obj.animation_data or not obj.animation_data.action:
        return
    action  = obj.animation_data.action
    fcurves = []
    legacy  = getattr(action, 'fcurves', None)
    if legacy is not None:
        fcurves.extend(list(legacy))
    else:
        for layer in getattr(action, 'layers', []):
            for strip in getattr(layer, 'strips', []):
                for bag in getattr(strip, 'channelbags', []):
                    fcurves.extend(list(getattr(bag, 'fcurves', [])))
    for fc in fcurves:
        if fc.data_path != data_path:
            continue
        for kp in fc.keyframe_points:
            kp.interpolation = interp
            if interp == 'BEZIER' and handle:
                kp.handle_left_type  = handle
                kp.handle_right_type = handle


# ── Keyframe loop ─────────────────────────────────────────────────────────────
prev_q  = None
n_total = min(n_frames, n_csvs)

for i in range(n_total):
    frame      = f_start + i
    grain_path = grain_files[i]

    scene.frame_set(frame)

    # Dense grain core for this frame.
    core_pos   = _grain_core(grain_path, CORE_GRAIN_FRACTION)

    if _use_earth_track:
        # Earth position relative to Apophis CoM (from the Earth Empty's keyframe).
        earth_pos  = earth_empty.matrix_world.translation.copy()

        # Direction from grain core to Earth.
        earth_vec        = earth_pos - core_pos
        earth_dist_core  = earth_vec.length
        if earth_dist_core > 1e-6:
            earth_from_core = earth_vec / earth_dist_core
        else:
            earth_from_core = _X.copy()

        # Perpendicular offset direction in the ecliptic plane (cross with world Z).
        offset_dir = earth_from_core.cross(_Z)
        if offset_dir.length < 1e-4:
            offset_dir = earth_from_core.cross(_X)
        if offset_dir.length < 1e-4:
            offset_dir = Vector((0.0, 1.0, 0.0))
        offset_dir.normalize()

        cam_pos  = core_pos + (-earth_from_core * cos_a + offset_dir * sin_a) * CAM_DIST_BU
    else:
        cam_pos = core_pos + _grain_only_offset * CAM_DIST_BU

    # Aim at the grain core — dense nucleus always centred in frame.
    look_vec = (core_pos - cam_pos).normalized()

    # Upright orientation: local -Z → look_vec, local +Y → world +Z.
    # 'Y' here is the LOCAL axis aligned toward world up (world +Z).
    # look_vec stays near the ecliptic (small Z component) so no singularity.
    q = look_vec.to_track_quat('-Z', 'Y')

    # Quaternion continuity: stay in same hemisphere as previous frame so SLERP
    # (LINEAR interp) always takes the short arc between adjacent keyframes.
    if prev_q is not None and q.dot(prev_q) < 0.0:
        q.negate()
    prev_q = q.copy()

    cam_obj.location            = cam_pos
    cam_obj.rotation_quaternion = q
    cam_obj.keyframe_insert(data_path='location',            frame=frame)
    cam_obj.keyframe_insert(data_path='rotation_quaternion', frame=frame)

    if (i + 1) % 100 == 0:
        print(f'  {i+1}/{n_total}  core=({core_pos.x:.1f}, {core_pos.y:.1f}, {core_pos.z:.1f}) BU')

# ── Smooth F-curves ───────────────────────────────────────────────────────────
if SMOOTH_CAMERA:
    print('Smoothing F-curves ...')
    _apply_interp(cam_obj, 'location',            LOCATION_INTERP, LOCATION_HANDLE)
    _apply_interp(cam_obj, 'rotation_quaternion', ROTATION_INTERP)

if SETUP_CAM_FILL_LIGHT:
    existing_fill = bpy.data.objects.get(CAM_FILL_LIGHT_NAME)
    if existing_fill:
        bpy.data.objects.remove(existing_fill, do_unlink=True)
    fill_data        = bpy.data.lights.new(CAM_FILL_LIGHT_NAME, CAM_FILL_LIGHT_TYPE)
    fill_data.energy = CAM_FILL_LIGHT_ENERGY
    fill_obj         = bpy.data.objects.new(CAM_FILL_LIGHT_NAME, fill_data)
    scene.collection.objects.link(fill_obj)
    fill_obj.parent = cam_obj
    print(
        f'Fill light "{CAM_FILL_LIGHT_NAME}" ({CAM_FILL_LIGHT_TYPE}, '
        f'{CAM_FILL_LIGHT_ENERGY} W) parented to "{CAMERA_NAME}".'
    )

print(
    f'\nDone. "{CAMERA_NAME}" is now the active scene camera.\n'
    f'  Mode: {"Earth-tracking" if _use_earth_track else "grain-only orbit"}.\n'
    f'  Tracks grain core ({int(CORE_GRAIN_FRACTION * 100)}% closest grains) — nucleus always centred.\n'
    f'  CAM_DIST_BU={CAM_DIST_BU}  '
    + (f'CAM_ANGLE_DEG={CAM_ANGLE_DEG}  ' if _use_earth_track else
       f'az={CAM_GRAIN_ONLY_AZIMUTH_DEG}° el={CAM_GRAIN_ONLY_ELEVATION_DEG}°  ')
    + f'FOV={CAMERA_FOV_DEG}°\n'
    f'  Location: {LOCATION_INTERP}  Rotation: {ROTATION_INTERP} (SLERP, no roll)\n'
    f'  clip [{CAM_CLIP_START}, {CAM_CLIP_END}] BU'
)
