"""
DEM rubble-pile import + Earth-tracking camera — single Blender script.

Equivalent to running DEMGrainsBlenderEarth.py, then DEMCamera.py.
Set SETUP_CAMERA = False to run the import only (same as Earth script alone).
"""

import bpy
import csv
import math
import mathutils
import pandas as pd
import glob
import os
from dataclasses import dataclass
from typing import Optional
from mathutils import Matrix, Vector

# ── Configuration ─────────────────────────────────────────────────────────────
# Path to the dem_grains_output/ folder produced by DEMtoCSV.py.
GRAINS_CSV_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/1000np Alinged/run_0001_grains_output/'

# Path to the bodies output folder — filenames match GRAINS_CSV_DIR.
# Used to read the Sun, Earth, and Apophis positions each frame.
# Set to '' or a nonexistent path to skip Sun lamp and Earth entirely.
BODIES_CSV_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/1000np Alinged/run_0001_bodies_output/'
# 1000np aligned run, 5 min dumps (~1297 frames).

# Run DEMCamera.py logic after import (requires Earth Empty + bodies CSVs).
SETUP_CAMERA = True

# Sun lamp settings.
SUN_LAMP_ENERGY = 10.0
SUN_LAMP_ANGLE  = 0.00931   # radians; 0.00931 ≈ 0.53° (Sun's angular radius at ~1 AU)

# Interpolation applied to all grain, Sun lamp, and Earth F-curves.
SMOOTH_INTERPOLATION = True
INTERPOLATION_MODE   = 'BEZIER'   # 'BEZIER' or 'LINEAR'
HANDLE_MODE          = 'AUTO_CLAMPED'

# Material colour for the rubble-pile grains (RGBA, 0-1).
GRAIN_COLOR = (0.35, 0.30, 0.25, 1.0)

# Name of the Blender collection that will hold all grain sphere objects.
GRAIN_COLLECTION_NAME = 'DEM_Grains'

# Earth 3-D model (Surface, Atmosphere, Clouds from TheEarth.blend).
EARTH_MODEL_PATH         = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/BlenderConvert/TheEarth1.blend'
EARTH_PART_NAMES         = ['Surface', 'Atmosphere', 'Clouds']
EARTH_PHYSICAL_RADIUS_KM = 6371.0

EARTH_SHELL_SCALE = {
    'Atmosphere': 1.004,
    'Clouds':     1.002,
}

EARTH_VIS_SCALE = 0.2   # BU per km → scale_factor ≈ 1.0 for TheEarth1.blend

EARTH_SIDEREAL_DAY_S      = 86164.0905
EARTH_SPIN_AXIS           = (0.0, -0.3979, 0.9174)
EARTH_ROTATION_OFFSET_DEG = 0.0
EARTH_ROTATE_CLOUDS       = True

MOON_PHYSICAL_RADIUS_KM = 1737.53
MOON_COLOR              = (0.55, 0.55, 0.55, 1.0)

SUN_VIS_SCALE         = 0.003
SUN_BODY_RADIUS_BU    = 10000.0
SUN_COLOR             = (1.0, 1.0, 1.0, 1.0)
SUN_EMISSION_STRENGTH = 6000.0

VIEWPORT_CLIP_START = 0.1
VIEWPORT_CLIP_END   = 2000000.0

VOLUMETRIC_START   = 0.1
VOLUMETRIC_END     = 50000.0
VOLUMETRIC_SAMPLES = 128
VOLUMETRIC_TILE_PX = '2'

# ── Camera (DEMCamera.py) ─────────────────────────────────────────────────────
CAMERA_NAME         = 'DEM_TrackCam'
CAMERA_FOV_DEG      = 70.0
CAM_DIST_BU         = 150.0
CAM_ANGLE_DEG       = 30.0
EARTH_EMPTY_NAME    = 'Earth'
CORE_GRAIN_FRACTION = 0.80
SMOOTH_CAMERA       = True
LOCATION_INTERP     = 'BEZIER'
LOCATION_HANDLE     = 'AUTO_CLAMPED'
ROTATION_INTERP     = 'LINEAR'
CAM_CLIP_START      = 0.01
CAM_CLIP_END        = 20_000_000.0

# Fill light — parented to the camera so it co-moves each frame automatically.
# Illuminates the camera-facing side of Apophis without extra keyframes.
SETUP_CAM_FILL_LIGHT  = True
CAM_FILL_LIGHT_NAME   = 'DEM_CamFill'
CAM_FILL_LIGHT_TYPE   = 'POINT'   # POINT, SPOT, AREA, or SUN
CAM_FILL_LIGHT_ENERGY = 20000.0
# ─────────────────────────────────────────────────────────────────────────────
# COORDINATE NOTE
# Grains: x_vis = x_rel_km × GRAIN_VIS_SCALE (DEMtoCSV.py, default 50).
# Earth:  (earth_km - apophis_km) × EARTH_VIS_SCALE.
# Sun lamp: −Z aligned with light from Sun (−normalised sun_km − apo_km).
# Camera: tracks dense grain core; uses Earth Empty keyframes for framing.
# ─────────────────────────────────────────────────────────────────────────────

csv_files = sorted(glob.glob(os.path.join(GRAINS_CSV_DIR, '*.csv')))

if not csv_files:
    raise FileNotFoundError(
        f'No CSVs found in {GRAINS_CSV_DIR}\n'
        'Run CSVconvert/DEMtoCSV.py first to generate dem_grains_output/.'
    )

print(f'Found {len(csv_files)} grain CSV(s).')

_bodies_available = os.path.isdir(BODIES_CSV_DIR)
if not _bodies_available:
    print(
        f'WARNING: BODIES_CSV_DIR not found ({BODIES_CSV_DIR})\n'
        '  Sun lamp and Earth will be skipped.'
    )


def _bodies_csv_for(grains_path):
    """Return the matching bodies CSV path, or None if it does not exist."""
    if not _bodies_available:
        return None
    p = os.path.join(BODIES_CSV_DIR, os.path.basename(grains_path))
    return p if os.path.exists(p) else None


def _smooth_fcurves(obj, data_path):
    """Apply INTERPOLATION_MODE to all F-curves on obj matching data_path."""
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
            kp.interpolation = INTERPOLATION_MODE
            if INTERPOLATION_MODE == 'BEZIER':
                kp.handle_left_type  = HANDLE_MODE
                kp.handle_right_type = HANDLE_MODE


def _apply_fcurve_interp(obj, data_path, interp, handle=None):
    """Set interpolation on matching F-curves (camera uses per-path modes)."""
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


def _grain_core(csv_path, fraction):
    """Centroid of the closest `fraction` of grains to the CoM (origin)."""
    pts = []
    with open(csv_path, newline='') as f:
        for row in csv.DictReader(f):
            x, y, z = float(row['x_vis']), float(row['y_vis']), float(row['z_vis'])
            d = math.sqrt(x * x + y * y + z * z)
            pts.append((d, x, y, z))
    pts.sort()
    n = max(1, int(len(pts) * fraction))
    sub = pts[:n]
    cx = sum(r[1] for r in sub) / n
    cy = sum(r[2] for r in sub) / n
    cz = sum(r[3] for r in sub) / n
    return Vector((cx, cy, cz))


def setup_dem_track_camera(earth_empty, grain_files):
    """
    Create and keyframe DEM_TrackCam — same behaviour as DEMCamera.py.
    Call after import; earth_empty must be the animated Earth Empty.
    """
    if earth_empty is None:
        raise RuntimeError(
            f'Object "{EARTH_EMPTY_NAME}" not found. '
            'Earth import was skipped — camera needs the Earth Empty keyframes.'
        )

    scene   = bpy.context.scene
    f_start = scene.frame_start
    f_end   = scene.frame_end
    n_frames = f_end - f_start + 1
    n_csvs   = len(grain_files)
    if n_frames != n_csvs:
        print(
            f'WARNING: scene has {n_frames} frames but {n_csvs} grain CSVs. '
            'Using min of the two.'
        )

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

    prev_q  = None
    n_total = min(n_frames, n_csvs)

    for i in range(n_total):
        frame    = f_start + i
        csv_path = grain_files[i]
        scene.frame_set(frame)

        core_pos = _grain_core(csv_path, CORE_GRAIN_FRACTION)
        earth_pos = earth_empty.matrix_world.translation.copy()

        earth_vec = earth_pos - core_pos
        earth_dist_core = earth_vec.length
        if earth_dist_core > 1e-6:
            earth_from_core = earth_vec / earth_dist_core
        else:
            earth_from_core = _X.copy()

        offset_dir = earth_from_core.cross(_Z)
        if offset_dir.length < 1e-4:
            offset_dir = earth_from_core.cross(_X)
        if offset_dir.length < 1e-4:
            offset_dir = Vector((0.0, 1.0, 0.0))
        offset_dir.normalize()

        cam_pos = core_pos + (-earth_from_core * cos_a + offset_dir * sin_a) * CAM_DIST_BU
        look_vec = (core_pos - cam_pos).normalized()
        q = look_vec.to_track_quat('-Z', 'Y')

        if prev_q is not None and q.dot(prev_q) < 0.0:
            q.negate()
        prev_q = q.copy()

        cam_obj.location            = cam_pos
        cam_obj.rotation_quaternion = q
        cam_obj.keyframe_insert(data_path='location',            frame=frame)
        cam_obj.keyframe_insert(data_path='rotation_quaternion', frame=frame)

        if (i + 1) % 100 == 0:
            print(
                f'  {i + 1}/{n_total}  core=({core_pos.x:.1f}, {core_pos.y:.1f}, {core_pos.z:.1f}) BU'
            )

    if SMOOTH_CAMERA:
        print('Smoothing camera F-curves ...')
        _apply_fcurve_interp(cam_obj, 'location',            LOCATION_INTERP, LOCATION_HANDLE)
        _apply_fcurve_interp(cam_obj, 'rotation_quaternion', ROTATION_INTERP)

    print(
        f'\nCamera done. "{CAMERA_NAME}" is the active scene camera.\n'
        f'  Tracks grain core ({int(CORE_GRAIN_FRACTION * 100)}% closest grains).\n'
        f'  CAM_DIST_BU={CAM_DIST_BU}  CAM_ANGLE_DEG={CAM_ANGLE_DEG}  FOV={CAMERA_FOV_DEG}°\n'
        f'  Location: {LOCATION_INTERP}  Rotation: {ROTATION_INTERP} (SLERP, no roll)\n'
        f'  clip [{CAM_CLIP_START}, {CAM_CLIP_END}] BU'
    )


# ── Earth model import machinery ──────────────────────────────────────────────

@dataclass
class BodyModelConfig:
    body_label: str
    model_path: str
    model_format: str
    part_names: list
    collection_name: Optional[str]
    model_reference_radius_bu: float
    auto_reference_radius: bool
    target_radius_bu: Optional[float]
    center_object_name: str
    auto_center: bool
    auto_scale: bool
    blend_append_all_objects_if_unmatched: bool = False
    shell_scale: Optional[dict] = None


def _link_object_to_collection(obj, coll):
    try:
        coll.objects.link(obj)
    except RuntimeError:
        pass


def _parent_part_to_empty(obj, empty_obj):
    mw = obj.matrix_world.copy()
    obj.parent = empty_obj
    obj.matrix_parent_inverse = empty_obj.matrix_world.inverted()
    obj.matrix_world = mw


def _object_base_name(name):
    if '.' in name:
        head, tail = name.rsplit('.', 1)
        if tail.isdigit():
            return head
    return name


def _blend_object_names_for_append(library_object_names, cfg):
    names = list(library_object_names)
    if not names:
        print(f'  ERROR: {cfg.body_label}: .blend contains no object datablocks: {cfg.model_path}')
        return []
    part_set = set(cfg.part_names)
    chosen = [n for n in names if n in part_set]
    if chosen:
        return chosen
    part_lower = {p.lower() for p in cfg.part_names}
    chosen = [n for n in names if n.lower() in part_lower]
    if chosen:
        print(f'  NOTE: {cfg.body_label}: matched object names case-insensitively: {chosen!r}')
        return chosen
    base_parts = {_object_base_name(p) for p in cfg.part_names}
    chosen = [n for n in names if _object_base_name(n) in base_parts]
    if chosen:
        return chosen
    if cfg.blend_append_all_objects_if_unmatched:
        print(
            f'  WARNING: {cfg.body_label}: no object matched part_names={cfg.part_names!r}. '
            f'Appending all. Available: {sorted(names)}'
        )
        return list(names)
    print(
        f'  ERROR: {cfg.body_label}: no objects matched part_names={cfg.part_names!r}. '
        f'Available in blend: {sorted(names)}'
    )
    return []


def _combined_mesh_bbox_center_world(mesh_objs):
    if not mesh_objs:
        return Vector((0.0, 0.0, 0.0))
    min_co = Vector((1e30, 1e30, 1e30))
    max_co = Vector((-1e30, -1e30, -1e30))
    for obj in mesh_objs:
        if obj.type != 'MESH':
            continue
        m = obj.matrix_world
        for corner in obj.bound_box:
            w = m @ Vector(corner)
            min_co.x = min(min_co.x, w.x)
            min_co.y = min(min_co.y, w.y)
            min_co.z = min(min_co.z, w.z)
            max_co.x = max(max_co.x, w.x)
            max_co.y = max(max_co.y, w.y)
            max_co.z = max(max_co.z, w.z)
    return (min_co + max_co) * 0.5


def _body_center_reference_world(mesh_objs, cfg):
    for obj in mesh_objs:
        if _object_base_name(obj.name) == cfg.center_object_name:
            return _combined_mesh_bbox_center_world([obj])
    return _combined_mesh_bbox_center_world(mesh_objs)


def _body_surface_mesh(mesh_objs, cfg):
    for obj in mesh_objs:
        if obj.type == 'MESH' and _object_base_name(obj.name) == cfg.center_object_name:
            return obj
    mesh_only = [o for o in mesh_objs if o.type == 'MESH']
    return mesh_only[0] if len(mesh_only) == 1 else None


def _mesh_world_aabb_half_max_extent(obj):
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(depsgraph)
    except RuntimeError:
        ev = obj
    m = ev.matrix_world
    min_co = Vector((1e30, 1e30, 1e30))
    max_co = Vector((-1e30, -1e30, -1e30))
    for corner in ev.bound_box:
        w = m @ Vector(corner)
        min_co.x = min(min_co.x, w.x)
        min_co.y = min(min_co.y, w.y)
        min_co.z = min(min_co.z, w.z)
        max_co.x = max(max_co.x, w.x)
        max_co.y = max(max_co.y, w.y)
        max_co.z = max(max_co.z, w.z)
    extent = max_co - min_co
    return max(extent.x, extent.y, extent.z) * 0.5


def _body_reference_radius_bu(mesh_objs, cfg):
    if not cfg.auto_reference_radius:
        return cfg.model_reference_radius_bu, 'manual_constant'
    surf = _body_surface_mesh(mesh_objs, cfg)
    if surf is not None:
        measured = _mesh_world_aabb_half_max_extent(surf)
        if measured > 0:
            return measured, 'measured'
        print(
            f'  WARNING: Auto reference radius invalid; '
            f'using model_reference_radius_bu={cfg.model_reference_radius_bu}.'
        )
    else:
        print(
            f'  WARNING: No mesh named "{cfg.center_object_name}" in import; '
            f'using model_reference_radius_bu={cfg.model_reference_radius_bu}.'
        )
    return cfg.model_reference_radius_bu, 'constant_fallback'


def _prepare_body_meshes_layout(mesh_objs, empty_obj, cfg, target_radius_bu):
    if not mesh_objs:
        return
    E = empty_obj.matrix_world.translation.copy()
    C = _body_center_reference_world(mesh_objs, cfg)

    if cfg.auto_center:
        delta = E - C
        T = Matrix.Translation(delta)
        for obj in mesh_objs:
            obj.matrix_world = T @ obj.matrix_world

    scale_factor = None
    reference_radius, ref_source = _body_reference_radius_bu(mesh_objs, cfg)
    if cfg.auto_scale:
        if reference_radius > 0:
            scale_factor = target_radius_bu / reference_radius
            S = (
                Matrix.Translation(E)
                @ Matrix.Diagonal((scale_factor, scale_factor, scale_factor, 1.0))
                @ Matrix.Translation(-E)
            )
            for obj in mesh_objs:
                obj.matrix_world = S @ obj.matrix_world
        else:
            print(f'  WARNING: {cfg.body_label} reference radius must be > 0; skipping scale.')

    shell_scale = cfg.shell_scale or {}
    for obj in mesh_objs:
        extra = shell_scale.get(_object_base_name(obj.name))
        if extra and extra != 1.0:
            Sx = (
                Matrix.Translation(E)
                @ Matrix.Diagonal((extra, extra, extra, 1.0))
                @ Matrix.Translation(-E)
            )
            obj.matrix_world = Sx @ obj.matrix_world
            print(f'  {cfg.body_label}: enlarged "{obj.name}" by ×{extra} (shell clearance).')

    sf_str = f'{scale_factor:.6g}' if scale_factor is not None else 'skipped'
    print(
        f'  {cfg.body_label} layout: measured reference_radius={reference_radius:.6g} BU ({ref_source}), '
        f'target_radius={target_radius_bu:.6g} BU, scale_factor={sf_str}'
    )


def import_body_model(empty_obj, cfg, target_radius_bu):
    parented_count = 0

    if cfg.model_format != 'BLEND':
        print(f'  ERROR: {cfg.body_label}: only BLEND format supported in this script.')
        return

    blend_path = os.path.abspath(os.path.normpath(cfg.model_path))
    if not os.path.isfile(blend_path):
        print(f'  ERROR: {cfg.body_label}: blend file not found: {blend_path}')
        return

    use_collection = bool(cfg.collection_name)
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        if use_collection:
            if cfg.collection_name in data_from.collections:
                data_to.collections = [cfg.collection_name]
            else:
                print(f'  WARNING: Collection "{cfg.collection_name}" not found in {blend_path}')
                data_to.collections = []
            data_to.objects = []
        else:
            to_load = _blend_object_names_for_append(data_from.objects, cfg)
            data_to.objects = to_load
            data_to.collections = []

    coll = bpy.context.collection
    body_col = next((c for c in data_to.collections if c is not None), None)
    blend_appended = []

    if use_collection and body_col is not None:
        coll.children.link(body_col)
        blend_appended = [obj for obj in body_col.all_objects if obj.type == 'MESH']
        _prepare_body_meshes_layout(blend_appended, empty_obj, cfg, target_radius_bu)
        for obj in blend_appended:
            _parent_part_to_empty(obj, empty_obj)
            parented_count += 1
    elif not use_collection:
        appended = [obj for obj in data_to.objects if obj is not None]
        for obj in appended:
            _link_object_to_collection(obj, coll)
        blend_appended = [o for o in appended if o.type == 'MESH']
        _prepare_body_meshes_layout(blend_appended, empty_obj, cfg, target_radius_bu)
        for obj in blend_appended:
            _parent_part_to_empty(obj, empty_obj)
            parented_count += 1

    print(f'Parented {parented_count} {cfg.body_label} model part(s) to "{empty_obj.name}".')
    imported_bases = {_object_base_name(o.name) for o in blend_appended}
    expected = set(cfg.part_names)
    if imported_bases and imported_bases != expected:
        print(f'  NOTE: got base names {sorted(imported_bases)} (expected {sorted(expected)})')


# ── Create Sun lamp ───────────────────────────────────────────────────────────
sun_lamp_obj = None
if _bodies_available:
    existing = bpy.data.objects.get('DEM_SunLight')
    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)
    lamp_data        = bpy.data.lights.new('DEM_SunLight', 'SUN')
    lamp_data.energy = SUN_LAMP_ENERGY
    lamp_data.angle  = SUN_LAMP_ANGLE
    sun_lamp_obj     = bpy.data.objects.new('DEM_SunLight', lamp_data)
    bpy.context.scene.collection.objects.link(sun_lamp_obj)
    print('Sun lamp "DEM_SunLight" created.')


# ── Import Earth model ────────────────────────────────────────────────────────
earth_empty = None
if _bodies_available and EARTH_MODEL_PATH and os.path.exists(EARTH_MODEL_PATH):
    earth_cfg = BodyModelConfig(
        body_label='Earth',
        model_path=EARTH_MODEL_PATH,
        model_format='BLEND',
        part_names=list(EARTH_PART_NAMES),
        collection_name=None,
        model_reference_radius_bu=1.0,
        auto_reference_radius=True,
        target_radius_bu=EARTH_PHYSICAL_RADIUS_KM * EARTH_VIS_SCALE,
        center_object_name='Surface',
        auto_center=True,
        auto_scale=True,
        shell_scale=EARTH_SHELL_SCALE,
    )
    print(f'Importing Earth from {os.path.basename(EARTH_MODEL_PATH)} ...')
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
    earth_empty      = bpy.context.object
    earth_empty.name = EARTH_EMPTY_NAME
    import_body_model(earth_empty, earth_cfg, EARTH_PHYSICAL_RADIUS_KM * EARTH_VIS_SCALE)
elif EARTH_MODEL_PATH and not os.path.exists(EARTH_MODEL_PATH):
    print(f'WARNING: EARTH_MODEL_PATH not found ({EARTH_MODEL_PATH}) — Earth skipped.')

_earth_spin_objs = []
if earth_empty is not None:
    for _obj in earth_empty.children_recursive:
        _base = _object_base_name(_obj.name)
        if _base == 'Surface':
            _obj.rotation_mode = 'QUATERNION'
            _earth_spin_objs.append(_obj)
        elif _base == 'Clouds' and EARTH_ROTATE_CLOUDS:
            _obj.rotation_mode = 'QUATERNION'
            _earth_spin_objs.append(_obj)
    print(f'Earth rotation objects ({len(_earth_spin_objs)}): {[o.name for o in _earth_spin_objs]}')


# ── Create Moon ───────────────────────────────────────────────────────────────
moon_empty = None
if _bodies_available:
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
    moon_empty      = bpy.context.object
    moon_empty.name = 'Moon'
    moon_radius_bu  = MOON_PHYSICAL_RADIUS_KM * EARTH_VIS_SCALE
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=moon_radius_bu, segments=32, ring_count=16, location=(0.0, 0.0, 0.0)
    )
    moon_sphere      = bpy.context.object
    moon_sphere.name = 'Moon_Body'
    moon_mat = bpy.data.materials.get('Moon_Surface')
    if moon_mat is None:
        moon_mat = bpy.data.materials.new('Moon_Surface')
        moon_mat.use_nodes = True
        _bsdf = moon_mat.node_tree.nodes.get('Principled BSDF')
        if _bsdf:
            _bsdf.inputs['Base Color'].default_value = MOON_COLOR
            _bsdf.inputs['Roughness'].default_value  = 0.95
    if moon_sphere.data.materials:
        moon_sphere.data.materials[0] = moon_mat
    else:
        moon_sphere.data.materials.append(moon_mat)
    _parent_part_to_empty(moon_sphere, moon_empty)
    print(f'Moon UV sphere created — radius {moon_radius_bu:.1f} BU')


# ── Create Sun visual body ────────────────────────────────────────────────────
sun_body_empty = None
if _bodies_available:
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
    sun_body_empty      = bpy.context.object
    sun_body_empty.name = 'Sun_Visual'
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=SUN_BODY_RADIUS_BU, segments=32, ring_count=16, location=(0.0, 0.0, 0.0)
    )
    sun_sphere      = bpy.context.object
    sun_sphere.name = 'Sun_Body'
    sun_mat = bpy.data.materials.get('Sun_Surface')
    if sun_mat is None:
        sun_mat = bpy.data.materials.new('Sun_Surface')
        sun_mat.use_nodes = True
        _bsdf = sun_mat.node_tree.nodes.get('Principled BSDF')
        if _bsdf:
            _bsdf.inputs['Base Color'].default_value = SUN_COLOR
            for _inp_name, _inp_val in (
                ('Emission Color',    SUN_COLOR),
                ('Emission',          SUN_COLOR),
                ('Emission Strength', SUN_EMISSION_STRENGTH),
            ):
                if _inp_name in _bsdf.inputs:
                    _bsdf.inputs[_inp_name].default_value = _inp_val
    if sun_sphere.data.materials:
        sun_sphere.data.materials[0] = sun_mat
    else:
        sun_sphere.data.materials.append(sun_mat)
    _parent_part_to_empty(sun_sphere, sun_body_empty)
    print(
        f'Sun visual body created — radius {SUN_BODY_RADIUS_BU} BU, '
        f'position scale {SUN_VIS_SCALE} BU/km'
    )


# ── Shared grain material ─────────────────────────────────────────────────────
mat = bpy.data.materials.get('DEM_Grain')
if mat is None:
    mat = bpy.data.materials.new('DEM_Grain')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Base Color'].default_value = GRAIN_COLOR
        bsdf.inputs['Roughness'].default_value  = 0.85
        bsdf.inputs['Metallic'].default_value   = 0.0


# ── Create grain collection ───────────────────────────────────────────────────
grain_col = bpy.data.collections.get(GRAIN_COLLECTION_NAME)
if grain_col is None:
    grain_col = bpy.data.collections.new(GRAIN_COLLECTION_NAME)
    bpy.context.scene.collection.children.link(grain_col)

# ── First pass: create grain spheres ──────────────────────────────────────────
first_df = pd.read_csv(csv_files[0])
n_grains = len(first_df)
print(f'Creating {n_grains} grain spheres from {os.path.basename(csv_files[0])} ...')

for _, row in first_df.iterrows():
    gid    = int(row['grain_id'])
    name   = f'DEM_Grain_{gid:03d}'
    radius = float(row['Reff_vis'])
    loc    = (float(row['x_vis']), float(row['y_vis']), float(row['z_vis']))

    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius, segments=12, ring_count=8, location=loc
    )
    obj      = bpy.context.object
    obj.name = name

    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    grain_col.objects.link(obj)

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

print('Spheres created.')

# ── Second pass: keyframe animation ───────────────────────────────────────────
print(f'Keyframing {len(csv_files)} frames ...')

bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end   = len(csv_files)

for frame_num, csv_file in enumerate(csv_files, start=1):
    df = pd.read_csv(csv_file)
    bpy.context.scene.frame_set(frame_num)

    for _, row in df.iterrows():
        gid  = int(row['grain_id'])
        name = f'DEM_Grain_{gid:03d}'
        obj  = bpy.data.objects.get(name)
        if obj is None:
            continue
        obj.location = (
            float(row['x_vis']),
            float(row['y_vis']),
            float(row['z_vis']),
        )
        obj.keyframe_insert(data_path='location', frame=frame_num)

    if sun_lamp_obj is not None or earth_empty is not None:
        bodies_path = _bodies_csv_for(csv_file)
        if bodies_path:
            bdf     = pd.read_csv(bodies_path)
            sun_row = bdf.loc[bdf['name'] == 'Sun']
            apo_row = bdf.loc[bdf['name'] == 'Apophis']

            if sun_lamp_obj is not None and not sun_row.empty and not apo_row.empty:
                sun_km  = sun_row[['x_km', 'y_km', 'z_km']].values[0]
                apo_km  = apo_row[['x_km', 'y_km', 'z_km']].values[0]
                sun_rel = sun_km - apo_km
                sun_dir = mathutils.Vector(sun_rel.tolist()).normalized()
                rot = (-sun_dir).to_track_quat('-Z', 'Y').to_euler()
                sun_lamp_obj.rotation_euler = rot
                sun_lamp_obj.keyframe_insert(data_path='rotation_euler', frame=frame_num)

            earth_row = bdf.loc[bdf['name'] == 'Earth']
            if earth_empty is not None and not earth_row.empty and not apo_row.empty:
                earth_km = earth_row[['x_km', 'y_km', 'z_km']].values[0]
                apo_km   = apo_row[['x_km', 'y_km', 'z_km']].values[0]
                rel_km   = earth_km - apo_km
                earth_empty.location = (
                    float(rel_km[0] * EARTH_VIS_SCALE),
                    float(rel_km[1] * EARTH_VIS_SCALE),
                    float(rel_km[2] * EARTH_VIS_SCALE),
                )
                earth_empty.keyframe_insert(data_path='location', frame=frame_num)

            if _earth_spin_objs:
                time_s_val = float(bdf['time_s'].iloc[0]) if 'time_s' in bdf.columns else 0.0
                spin_deg   = (time_s_val / EARTH_SIDEREAL_DAY_S) * 360.0 + EARTH_ROTATION_OFFSET_DEG
                spin_axis  = mathutils.Vector(EARTH_SPIN_AXIS).normalized()
                q = mathutils.Quaternion(spin_axis, math.radians(spin_deg))
                for _obj in _earth_spin_objs:
                    _obj.rotation_quaternion = q
                    _obj.keyframe_insert(data_path='rotation_quaternion', frame=frame_num)

            moon_row = bdf.loc[bdf['name'] == 'Moon']
            if moon_empty is not None and not moon_row.empty and not apo_row.empty:
                moon_km = moon_row[['x_km', 'y_km', 'z_km']].values[0]
                rel_km  = moon_km - apo_km
                moon_empty.location = (
                    float(rel_km[0] * EARTH_VIS_SCALE),
                    float(rel_km[1] * EARTH_VIS_SCALE),
                    float(rel_km[2] * EARTH_VIS_SCALE),
                )
                moon_empty.keyframe_insert(data_path='location', frame=frame_num)

            if sun_body_empty is not None and not sun_row.empty and not apo_row.empty:
                sun_km_vis = sun_row[['x_km', 'y_km', 'z_km']].values[0]
                rel_km     = sun_km_vis - apo_km
                sun_body_empty.location = (
                    float(rel_km[0] * SUN_VIS_SCALE),
                    float(rel_km[1] * SUN_VIS_SCALE),
                    float(rel_km[2] * SUN_VIS_SCALE),
                )
                sun_body_empty.keyframe_insert(data_path='location', frame=frame_num)

# ── Third pass: smooth import F-curves ────────────────────────────────────────
if SMOOTH_INTERPOLATION:
    print('Smoothing import F-curves ...')
    for gid in range(n_grains):
        obj = bpy.data.objects.get(f'DEM_Grain_{gid:03d}')
        if obj:
            _smooth_fcurves(obj, 'location')
    if sun_lamp_obj is not None:
        _smooth_fcurves(sun_lamp_obj, 'rotation_euler')
    if earth_empty is not None:
        _smooth_fcurves(earth_empty, 'location')
    for _obj in _earth_spin_objs:
        _smooth_fcurves(_obj, 'rotation_quaternion')
    if moon_empty is not None:
        _smooth_fcurves(moon_empty, 'location')
    if sun_body_empty is not None:
        _smooth_fcurves(sun_body_empty, 'location')

# ── Viewport clip + EEVEE volumetrics (import stage) ───────────────────────────
_clip_targets = 0
for _area in (a for _s in bpy.data.screens for a in _s.areas if a.type == 'VIEW_3D'):
    for _space in (sp for sp in _area.spaces if sp.type == 'VIEW_3D'):
        _space.clip_start = VIEWPORT_CLIP_START
        _space.clip_end   = VIEWPORT_CLIP_END
        _clip_targets += 1
for _cam in (c for c in bpy.data.cameras):
    _cam.clip_start = VIEWPORT_CLIP_START
    _cam.clip_end   = VIEWPORT_CLIP_END
    _clip_targets += 1
print(
    f'Clip range set to [{VIEWPORT_CLIP_START}, {VIEWPORT_CLIP_END}] BU '
    f'on {_clip_targets} viewport/camera target(s).'
)

_ee = getattr(bpy.context.scene, 'eevee', None)
if _ee is not None:
    _applied = []
    for _attr, _val in (
        ('volumetric_start',     VOLUMETRIC_START),
        ('volumetric_end',       VOLUMETRIC_END),
        ('volumetric_samples',   VOLUMETRIC_SAMPLES),
        ('volumetric_tile_size', VOLUMETRIC_TILE_PX),
    ):
        if hasattr(_ee, _attr):
            try:
                setattr(_ee, _attr, _val)
                _applied.append(_attr)
            except (TypeError, ValueError) as _e:
                print(f'  NOTE: could not set scene.eevee.{_attr}: {_e}')
    print(
        f'EEVEE volumetric settings applied ({len(_applied)}): '
        f'{", ".join(_applied) if _applied else "none"}.'
    )

print(
    f'Import done — {n_grains} DEM grains over {len(csv_files)} frame(s).\n'
    f'Earth at (earth_km - apophis_km) × {EARTH_VIS_SCALE} BU/km.\n'
    'Sun lamp + Sun_Visual keyframed from bodies CSV.'
)

# ── Camera setup (DEMCamera.py) ───────────────────────────────────────────────
if SETUP_CAMERA:
    print('\n── Setting up tracking camera ──')
    setup_dem_track_camera(earth_empty, csv_files)

    if SETUP_CAM_FILL_LIGHT:
        cam_obj = bpy.data.objects.get(CAMERA_NAME)
        if cam_obj is not None:
            existing_fill = bpy.data.objects.get(CAM_FILL_LIGHT_NAME)
            if existing_fill:
                bpy.data.objects.remove(existing_fill, do_unlink=True)
            fill_data        = bpy.data.lights.new(CAM_FILL_LIGHT_NAME, CAM_FILL_LIGHT_TYPE)
            fill_data.energy = CAM_FILL_LIGHT_ENERGY
            fill_obj         = bpy.data.objects.new(CAM_FILL_LIGHT_NAME, fill_data)
            bpy.context.scene.collection.objects.link(fill_obj)
            fill_obj.parent = cam_obj
            print(
                f'Fill light "{CAM_FILL_LIGHT_NAME}" ({CAM_FILL_LIGHT_TYPE}, '
                f'{CAM_FILL_LIGHT_ENERGY} W) parented to "{CAMERA_NAME}".'
            )
        else:
            print(f'WARNING: camera "{CAMERA_NAME}" not found — fill light skipped.')
else:
    print('\nSETUP_CAMERA is False — skipping camera (run DEMCamera.py separately if needed).')

print(
    '\nAll done. Do NOT run Viewport.py (tuned for point-mass scale).\n'
    'Tune paths at top: GRAINS_CSV_DIR, BODIES_CSV_DIR, camera block, SETUP_CAMERA.'
)
