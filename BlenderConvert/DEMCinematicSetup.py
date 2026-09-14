"""Shared cinematic scene-building for DEM bulk viz Blender scripts.

Earth/Moon/Sun placeholder, body-CSV keyframing, and a grain-core tracking
camera — extracted from DEMBulkVizBlender.py so DEMBulkInstanceBlender.py
(and any future bulk-viz path) can reuse it without duplicating cinematic
logic. DEMGrainsBlenderEarthCam.py is intentionally not built on this module
-- it keeps its own independent, proven implementation.
"""

import contextlib
import glob
import math
import os

import bpy
import mathutils
import numpy as np
import pandas as pd
from mathutils import Vector

# -- Configuration (same defaults DEMBulkVizBlender.py already used) --------
EARTH_MODEL_PATH = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/BlenderConvert/TheEarth1.blend'
)
EARTH_PART_NAMES = ['Surface', 'Atmosphere', 'Clouds']
EARTH_SHELL_SCALE = {'Atmosphere': 1.004, 'Clouds': 1.002}
EARTH_PHYSICAL_RADIUS_KM = 6371.0
EARTH_VIS_SCALE = 0.2
EARTH_SIDEREAL_DAY_S = 86164.0905
EARTH_SPIN_AXIS = (0.0, -0.3979, 0.9174)
EARTH_ROTATION_OFFSET_DEG = 0.0
EARTH_ROTATE_CLOUDS = True
EARTH_EMPTY_NAME = 'Earth'
SUN_LAMP_ENERGY = 10.0
SUN_LAMP_ANGLE = 0.00931
SUN_VIS_SCALE = 0.003
CAMERA_NAME = 'DEM_TrackCam'
CAMERA_FOV_DEG = 70.0
CAM_DIST_BU = 150.0
CAM_ANGLE_DEG = 30.0
CAM_GRAIN_ONLY_AZIMUTH_DEG = 45.0
CAM_GRAIN_ONLY_ELEVATION_DEG = 20.0
CAM_CLIP_START = 0.01
CAM_CLIP_END = 20_000_000.0
# -----------------------------------------------------------------------------


def detect_solar_system(bodies_dir):
    csvs = sorted(glob.glob(os.path.join(bodies_dir, '*.csv')))
    if not csvs:
        return False
    try:
        names = set(pd.read_csv(csvs[0], usecols=['name'])['name'].astype(str))
    except (ValueError, KeyError, OSError):
        return False
    return 'Earth' in names or 'Sun' in names


def grain_core(points_vis, fraction):
    """Centroid of the innermost ``fraction`` of points, by distance from origin."""
    if len(points_vis) == 0:
        return Vector((0.0, 0.0, 0.0))
    n = max(1, min(len(points_vis), int(len(points_vis) * fraction)))
    d2 = (points_vis * points_vis).sum(axis=1)
    inner = points_vis[np.argpartition(d2, n - 1)[:n]]
    return Vector(inner.mean(axis=0))


def _object_base_name(name):
    if '.' in name:
        head, tail = name.rsplit('.', 1)
        if tail.isdigit():
            return head
    return name


def _parent_part_to_empty(obj, empty_obj):
    mw = obj.matrix_world.copy()
    obj.parent = empty_obj
    obj.matrix_parent_inverse = empty_obj.matrix_world.inverted()
    obj.matrix_world = mw


def _mesh_world_aabb_half_max_extent(obj):
    m = obj.matrix_world
    min_co = Vector((1e30, 1e30, 1e30))
    max_co = Vector((-1e30, -1e30, -1e30))
    for corner in obj.bound_box:
        w = m @ Vector(corner)
        min_co.x, min_co.y, min_co.z = (min(min_co[i], w[i]) for i in range(3))
        max_co.x, max_co.y, max_co.z = (max(max_co[i], w[i]) for i in range(3))
    extent = max_co - min_co
    return max(extent.x, extent.y, extent.z) * 0.5


def _append_earth_model(earth_empty, target_radius_bu):
    """Append Surface/Atmosphere/Clouds from EARTH_MODEL_PATH, scaled to target_radius_bu.

    Ported from DEMGrainsBlenderEarthCam.py's import_body_model()/BodyModelConfig
    machinery, scoped to just Earth since this module has only one caller of it.
    """
    blend_path = os.path.abspath(os.path.normpath(EARTH_MODEL_PATH))
    if not os.path.isfile(blend_path):
        print(f'WARNING: EARTH_MODEL_PATH not found ({blend_path}) — falling back to bare sphere.')
        return False

    part_set = set(EARTH_PART_NAMES)
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        names = list(data_from.objects)
        chosen = [n for n in names if n in part_set]
        if not chosen:
            base_parts = {_object_base_name(p) for p in EARTH_PART_NAMES}
            chosen = [n for n in names if _object_base_name(n) in base_parts]
        if not chosen:
            print(f'WARNING: no objects in {blend_path} matched {EARTH_PART_NAMES!r} '
                  f'(available: {sorted(names)}) — falling back to bare sphere.')
            data_to.objects = []
            return False
        data_to.objects = chosen

    coll = bpy.context.scene.collection
    appended = [obj for obj in data_to.objects if obj is not None]
    for obj in appended:
        try:
            coll.objects.link(obj)
        except RuntimeError:
            pass
    mesh_objs = [o for o in appended if o.type == 'MESH']
    if not mesh_objs:
        print(f'WARNING: {blend_path} appended no mesh objects — falling back to bare sphere.')
        return False

    surf = next((o for o in mesh_objs if _object_base_name(o.name) == 'Surface'), mesh_objs[0])
    reference_radius = _mesh_world_aabb_half_max_extent(surf)
    if reference_radius <= 0:
        print('WARNING: measured Earth reference radius <= 0 — falling back to bare sphere.')
        return False

    E = earth_empty.matrix_world.translation.copy()
    scale_factor = target_radius_bu / reference_radius
    S = (
        mathutils.Matrix.Translation(E)
        @ mathutils.Matrix.Diagonal((scale_factor, scale_factor, scale_factor, 1.0))
        @ mathutils.Matrix.Translation(-E)
    )
    for obj in mesh_objs:
        obj.matrix_world = S @ obj.matrix_world

    for obj in mesh_objs:
        extra = EARTH_SHELL_SCALE.get(_object_base_name(obj.name))
        if extra and extra != 1.0:
            Sx = (
                mathutils.Matrix.Translation(E)
                @ mathutils.Matrix.Diagonal((extra, extra, extra, 1.0))
                @ mathutils.Matrix.Translation(-E)
            )
            obj.matrix_world = Sx @ obj.matrix_world

    for obj in mesh_objs:
        _parent_part_to_empty(obj, earth_empty)
        base = _object_base_name(obj.name)
        if base == 'Surface' or (base == 'Clouds' and EARTH_ROTATE_CLOUDS):
            obj.rotation_mode = 'QUATERNION'

    print(f'Earth imported from {os.path.basename(blend_path)}: '
          f'{sorted(_object_base_name(o.name) for o in mesh_objs)}, '
          f'scale_factor={scale_factor:.6g}.')
    return True


def ensure_earth_placeholder(has_solar, bodies_dir):
    """Create Earth: append Surface/Atmosphere/Clouds from EARTH_MODEL_PATH, or a
    bare UV sphere named 'Surface' if that model is unavailable."""
    if not has_solar or not os.path.isdir(bodies_dir):
        return None
    earth_empty = bpy.data.objects.get(EARTH_EMPTY_NAME)
    if earth_empty is not None:
        return earth_empty
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
    earth_empty = bpy.context.object
    earth_empty.name = EARTH_EMPTY_NAME
    radius_bu = EARTH_PHYSICAL_RADIUS_KM * EARTH_VIS_SCALE

    if _append_earth_model(earth_empty, radius_bu):
        return earth_empty

    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius_bu, segments=32, ring_count=16, location=(0.0, 0.0, 0.0)
    )
    surf = bpy.context.object
    surf.name = 'Surface'
    surf.rotation_mode = 'QUATERNION'
    _parent_part_to_empty(surf, earth_empty)
    print(f'Earth placeholder created (radius {radius_bu:.1f} BU).')
    return earth_empty


def keyframe_bodies_and_earth(bodies_dir, frame_count, has_solar, earth_empty=None, start_index=0):
    """Minimal bodies keyframing for Earth / Moon / Sun (subset of DEMGrainsBlenderEarthCam).

    ``start_index`` selects which sorted bodies CSV maps to scene frame_start --
    e.g. a manifest covering only the tail of a run (a close-approach window)
    needs this to be the real CSV index of its first frame, not 0.

    Calls ``scene.frame_set()`` per frame while keyframing -- if a caller has
    already enabled Blender's time remap (``render.frame_map_old/new``, e.g. for
    a slow-motion stretch), those calls sample at the *remapped* time, not the
    raw frame number, silently keyframing against the wrong slice of motion.
    Keyframe everything at 1:1 time first, then apply remap afterward.
    """
    if not has_solar or not os.path.isdir(bodies_dir):
        return earth_empty

    if earth_empty is None:
        earth_empty = bpy.data.objects.get(EARTH_EMPTY_NAME)
    sun_lamp = bpy.data.objects.get('DEM_SunLight')
    if sun_lamp is None and has_solar:
        lamp_data = bpy.data.lights.new('DEM_SunLight', 'SUN')
        lamp_data.energy = SUN_LAMP_ENERGY
        lamp_data.angle = SUN_LAMP_ANGLE
        sun_lamp = bpy.data.objects.new('DEM_SunLight', lamp_data)
        bpy.context.scene.collection.objects.link(sun_lamp)
    moon_empty = bpy.data.objects.get('Moon')
    sun_body = bpy.data.objects.get('Sun_Visual')

    all_bodies_csvs = sorted(glob.glob(os.path.join(bodies_dir, '*.csv')))
    bodies_csvs = all_bodies_csvs[start_index:]
    n = min(frame_count, len(bodies_csvs))
    if n == 0:
        return earth_empty

    spin_axis = Vector(EARTH_SPIN_AXIS).normalized()
    offset_rad = math.radians(EARTH_ROTATION_OFFSET_DEG)

    for i in range(n):
        frame = bpy.context.scene.frame_start + i
        bpy.context.scene.frame_set(frame)
        df = pd.read_csv(bodies_csvs[i])
        apo = df[df['name'] == 'Apophis']
        if apo.empty:
            continue
        apo = apo.iloc[0]

        if earth_empty is not None and 'Earth' in df['name'].values:
            earth = df[df['name'] == 'Earth'].iloc[0]
            ex = (float(earth['x_km']) - float(apo['x_km'])) * EARTH_VIS_SCALE
            ey = (float(earth['y_km']) - float(apo['y_km'])) * EARTH_VIS_SCALE
            ez = (float(earth['z_km']) - float(apo['z_km'])) * EARTH_VIS_SCALE
            earth_empty.location = (ex, ey, ez)
            earth_empty.keyframe_insert(data_path='location', frame=frame)
            if 'time_s' in earth.index and pd.notna(earth['time_s']):
                t_s = float(earth['time_s'])
                angle = (t_s / EARTH_SIDEREAL_DAY_S) * 2.0 * math.pi + offset_rad
                q = mathutils.Quaternion(spin_axis, angle)
                for child in earth_empty.children_recursive:
                    if child.name.startswith('Surface') or child.name.startswith('Clouds'):
                        child.rotation_quaternion = q
                        child.keyframe_insert(data_path='rotation_quaternion', frame=frame)

        if sun_lamp is not None and 'Sun' in df['name'].values:
            sun = df[df['name'] == 'Sun'].iloc[0]
            sx = float(sun['x_km']) - float(apo['x_km'])
            sy = float(sun['y_km']) - float(apo['y_km'])
            sz = float(sun['z_km']) - float(apo['z_km'])
            direction = Vector((sx, sy, sz))
            if direction.length > 1e-6:
                direction.normalize()
                sun_lamp.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()
                sun_lamp.keyframe_insert(data_path='rotation_euler', frame=frame)

        if moon_empty is not None and 'Moon' in df['name'].values:
            moon = df[df['name'] == 'Moon'].iloc[0]
            mx = (float(moon['x_km']) - float(apo['x_km'])) * EARTH_VIS_SCALE
            my = (float(moon['y_km']) - float(apo['y_km'])) * EARTH_VIS_SCALE
            mz = (float(moon['z_km']) - float(apo['z_km'])) * EARTH_VIS_SCALE
            moon_empty.location = (mx, my, mz)
            moon_empty.keyframe_insert(data_path='location', frame=frame)

        if sun_body is not None and 'Sun' in df['name'].values:
            sun = df[df['name'] == 'Sun'].iloc[0]
            sx = (float(sun['x_km']) - float(apo['x_km'])) * SUN_VIS_SCALE
            sy = (float(sun['y_km']) - float(apo['y_km'])) * SUN_VIS_SCALE
            sz = (float(sun['z_km']) - float(apo['z_km'])) * SUN_VIS_SCALE
            sun_body.location = (sx, sy, sz)
            sun_body.keyframe_insert(data_path='location', frame=frame)

    return earth_empty


def setup_camera(frame_count, core_fn, earth_empty, has_solar, camera_mode=None):
    """Keyframe a tracking camera. ``core_fn(i)`` returns the frame-``i`` aim point.

    Same time-remap hazard as keyframe_bodies_and_earth() above: this reads
    earth_empty's current (possibly time-remap-sampled) position per frame to
    aim the camera. Call before enabling any frame_map stretch.
    """
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.get(CAMERA_NAME) or bpy.data.cameras.new(CAMERA_NAME)
    cam_data.lens_unit = 'FOV'
    cam_data.angle = math.radians(CAMERA_FOV_DEG)
    cam_data.clip_start = CAM_CLIP_START
    cam_data.clip_end = CAM_CLIP_END
    cam_obj = bpy.data.objects.get(CAMERA_NAME)
    if cam_obj is None:
        cam_obj = bpy.data.objects.new(CAMERA_NAME, cam_data)
        scene.collection.objects.link(cam_obj)
    else:
        cam_obj.data = cam_data
    cam_obj.rotation_mode = 'QUATERNION'
    scene.camera = cam_obj

    use_earth = (
        camera_mode == 'earth_track'
        if camera_mode in ('earth_track', 'grain_only')
        else (earth_empty is not None and has_solar)
    )
    n = min(scene.frame_end - scene.frame_start + 1, frame_count)
    _Z = Vector((0.0, 0.0, 1.0))
    _X = Vector((1.0, 0.0, 0.0))
    angle_rad = math.radians(CAM_ANGLE_DEG)
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
    if not use_earth:
        az = math.radians(CAM_GRAIN_ONLY_AZIMUTH_DEG)
        el = math.radians(CAM_GRAIN_ONLY_ELEVATION_DEG)
        grain_only_offset = Vector((
            math.cos(el) * math.cos(az),
            math.cos(el) * math.sin(az),
            math.sin(el),
        )).normalized()

    prev_q = None
    for i in range(n):
        frame = scene.frame_start + i
        scene.frame_set(frame)
        core = core_fn(i)
        if use_earth and earth_empty is not None:
            earth_pos = earth_empty.matrix_world.translation.copy()
            earth_vec = earth_pos - core
            dist = earth_vec.length
            earth_from_core = earth_vec / dist if dist > 1e-6 else _X.copy()
            offset_dir = earth_from_core.cross(_Z)
            if offset_dir.length < 1e-4:
                offset_dir = earth_from_core.cross(_X)
            if offset_dir.length < 1e-4:
                offset_dir = Vector((0.0, 1.0, 0.0))
            offset_dir.normalize()
            # Pull back away from Earth (-earth_from_core) and tilt sideways
            # (offset_dir) so Earth stays in frame beyond the tracked core.
            cam_pos = core + (-earth_from_core * cos_a + offset_dir * sin_a) * CAM_DIST_BU
        else:
            cam_pos = core + grain_only_offset * CAM_DIST_BU
        look = (core - cam_pos).normalized()
        q = look.to_track_quat('-Z', 'Y')
        if prev_q is not None and q.dot(prev_q) < 0.0:
            q.negate()
        prev_q = q.copy()
        cam_obj.location = cam_pos
        cam_obj.rotation_quaternion = q
        cam_obj.keyframe_insert(data_path='location', frame=frame)
        cam_obj.keyframe_insert(data_path='rotation_quaternion', frame=frame)


def register_self_as_auto_run_module():
    """Flag the currently-running Text block so it re-executes when the .blend reopens.

    DEMBulkVizBlender.py and DEMBulkInstanceBlender.py drive their per-frame
    animation with a bpy.app.handlers.frame_change_pre callback plus a
    module-level Python dict. Neither is saved in the .blend file -- closing
    Blender ends the process that held them, so reopening the file leaves the
    envelope/point-cloud frozen at whatever frame it last showed (no handler
    left to update it). @bpy.app.handlers.persistent only keeps a handler alive
    across File > Open calls within one running Blender process; it does not
    survive quitting and relaunching Blender.exe.

    Setting the running script's own Text.use_module = True asks Blender to
    re-execute this text block on file load (as if Run Script were clicked
    again), which rebuilds state and re-registers the handler -- but only if
    the "Auto Run Python Scripts" preference (Edit > Preferences > Save & Load)
    is enabled, or the file/folder is a trusted source. If that preference is
    off, this flag is silently inert and the original symptom returns.

    No-op outside the Text Editor's Run Script context (e.g. `blender
    --background --python script.py`, where bpy.context.space_data is None) --
    main() there is already a fresh call per process, so there is nothing to
    restore.
    """
    space = getattr(bpy.context, 'space_data', None)
    text = getattr(space, 'text', None) if space is not None else None
    if text is not None:
        text.use_module = True


@contextlib.contextmanager
def frame_handler_suspended(handler):
    """Detach ``handler`` around setup loops that call scene.frame_set().

    Keyframing and camera setup step every frame; with a per-frame handler
    attached, each step would reload that frame's data from disk for nothing.
    """
    handlers = bpy.app.handlers.frame_change_pre
    attached = handler in handlers
    if attached:
        handlers.remove(handler)
    try:
        yield
    finally:
        if attached and handler not in handlers:
            handlers.append(handler)
