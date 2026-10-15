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
import sys

import bpy
import mathutils
import numpy as np
import pandas as pd
from mathutils import Vector

import earth_orientation

_CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)
import honours_paths  # noqa: E402
from viz import camera_framing  # noqa: E402

# -- Configuration (same defaults DEMBulkVizBlender.py already used) --------
# Asset folder from Code/honours_paths.py (default: Max's OneDrive BlenderConvert/).
EARTH_MODEL_PATH = honours_paths.host_path(honours_paths.assets_dir() + '/TheEarth1.blend')
EARTH_PART_NAMES = ['Surface', 'Atmosphere', 'Clouds']
EARTH_SHELL_SCALE = {'Atmosphere': 1.004, 'Clouds': 1.002}
EARTH_PHYSICAL_RADIUS_KM = 6371.0
EARTH_VIS_SCALE = 0.2
# TDB of sim time_s = 0 (the run's sobol.setup `epoch`); see earth_orientation.py.
EARTH_EPOCH_TDB = earth_orientation.DEFAULT_EPOCH_TDB
EARTH_ROTATE_CLOUDS = True
# TheEarth1.blend maps its land/ocean mask to roughness 1.0 (land) .. 0.1 (ocean),
# which mirrors the sun lamp as a sharp hotspot. Real sunglint (waves, haze) is a
# broad faint patch: ocean roughness and Specular IOR Level are overridden on append.
# None keeps the asset's value.
EARTH_OCEAN_ROUGHNESS = 0.45
EARTH_SPECULAR = 0.25
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
# camera_mode 'earth_fixed': camera parented to the Earth empty, one fixed pose
# framing Earth + the part of Apophis's path near Earth (viz/camera_framing.py):
# within EARTH_FIXED_WINDOW_KM of Earth's centre, or, when that is None, within
# EARTH_FIXED_WINDOW_CA_FACTOR x the closest-approach distance (None too = whole
# path). Apophis is simply out of shot outside the window.
EARTH_FIXED_WINDOW_KM = None
EARTH_FIXED_WINDOW_CA_FACTOR = 3.0
EARTH_FIXED_TILT_DEG = 20.0
EARTH_FIXED_MARGIN = 1.15
EARTH_FIXED_SUBSAMPLES = 8  # Earth positions sampled per key interval for the framing
# camera_mode 'earth_chase': over-the-shoulder -- camera behind Apophis on the
# Earth line, aimed at Earth's centre (Earth stays mid-frame), raised along the
# orbit normal so Apophis sits EARTH_CHASE_DROP of the half-height below the middle
# (1/3 = lower third). Distance = CAM_DIST_BU at CAMERA_FOV_DEG, scaled by
# 1/tan(fov/2), so a narrower fov keeps Apophis's size and magnifies Earth.
EARTH_CHASE_DROP = 1.0 / 3.0
EARTH_AIM_NAME = 'DEM_EarthAim'  # Empty on Earth whose Z is the chase camera's screen-up
CAMERA_MODES = ('earth_track', 'grain_only', 'earth_fixed', 'earth_chase')
# Below: per-sphere-only scene pieces (DEMGrainsBlenderEarthCam.py values),
# opt-in via ensure_sun_lamp / ensure_moon / ensure_sun_visual /
# add_camera_fill_light / apply_viewport_clip so the composite path is unchanged.
APOPHIS_ONLY_SUN_DIRECTION = (1.0, 0.0, 0.0)
MOON_PHYSICAL_RADIUS_KM = 1737.53
MOON_COLOR = (0.55, 0.55, 0.55, 1.0)
SUN_BODY_RADIUS_BU = 10000.0
SUN_COLOR = (1.0, 1.0, 1.0, 1.0)
SUN_EMISSION_STRENGTH = 6000.0
CAM_FILL_LIGHT_NAME = 'DEM_CamFill'
CAM_FILL_LIGHT_TYPE = 'POINT'
CAM_FILL_LIGHT_ENERGY = 20000.0
VIEWPORT_CLIP_START = 0.1
VIEWPORT_CLIP_END = 2000000.0
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


def bodies_row_names(bodies_dir):
    """Body names in the first bodies CSV ('Earth', 'Moon', ...); empty set if none."""
    csvs = sorted(glob.glob(os.path.join(bodies_dir, '*.csv'))) if bodies_dir else []
    if not csvs:
        return set()
    try:
        return set(pd.read_csv(csvs[0], usecols=['name'])['name'].astype(str))
    except (ValueError, KeyError, OSError):
        return set()


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


def _world_aabb(obj, evaluated):
    """World-space AABB; per-sphere centres on the original object's box and
    measures the radius on the evaluated one."""
    ev = obj
    if evaluated:
        try:
            ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        except RuntimeError:
            pass
    m = ev.matrix_world
    min_co = Vector((1e30, 1e30, 1e30))
    max_co = Vector((-1e30, -1e30, -1e30))
    for corner in ev.bound_box:
        w = m @ Vector(corner)
        min_co.x, min_co.y, min_co.z = (min(min_co[i], w[i]) for i in range(3))
        max_co.x, max_co.y, max_co.z = (max(max_co[i], w[i]) for i in range(3))
    return min_co, max_co


def _world_aabb_center(obj):
    min_co, max_co = _world_aabb(obj, evaluated=False)
    return (min_co + max_co) * 0.5


def _mesh_world_aabb_half_max_extent(obj):
    min_co, max_co = _world_aabb(obj, evaluated=True)
    extent = max_co - min_co
    return max(extent.x, extent.y, extent.z) * 0.5


def _soften_ocean_glint(surf):
    """Apply EARTH_OCEAN_ROUGHNESS / EARTH_SPECULAR to Surface's Principled BSDF."""
    for slot in surf.material_slots:
        mat = slot.material
        if mat is None or mat.node_tree is None:
            continue
        for bsdf in (n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'):
            if EARTH_SPECULAR is not None:
                bsdf.inputs['Specular IOR Level'].default_value = EARTH_SPECULAR
            rough = bsdf.inputs['Roughness']
            if EARTH_OCEAN_ROUGHNESS is None:
                continue
            if not rough.is_linked:
                rough.default_value = EARTH_OCEAN_ROUGHNESS
                continue
            src = rough.links[0].from_node
            if src.type == 'MAP_RANGE':
                # Mask 1 = ocean -> 'To Max' (float socket; the vector twin shares the name).
                to_max = next(s for s in src.inputs if s.name == 'To Max' and s.type == 'VALUE')
                to_max.default_value = EARTH_OCEAN_ROUGHNESS
            else:
                print(f'WARNING: Earth roughness fed by {src.type}; ocean glint left as is.')


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
    _soften_ocean_glint(surf)
    E = earth_empty.matrix_world.translation.copy()
    # Centre the model on the Empty via Surface's bbox centre (per-sphere
    # import_body_model auto_center), so the Earth sits exactly where its
    # keyframes put it even if the source .blend has it off-origin.
    delta = E - _world_aabb_center(surf)
    for obj in mesh_objs:
        obj.matrix_world = mathutils.Matrix.Translation(delta) @ obj.matrix_world

    reference_radius = _mesh_world_aabb_half_max_extent(surf)
    if reference_radius <= 0:
        print('WARNING: measured Earth reference radius <= 0 — falling back to bare sphere.')
        return False

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
    if sun_lamp is None:
        sun_lamp = _new_sun_lamp()
    moon_empty = bpy.data.objects.get('Moon')
    sun_body = bpy.data.objects.get('Sun_Visual')

    all_bodies_csvs = sorted(glob.glob(os.path.join(bodies_dir, '*.csv')))
    bodies_csvs = all_bodies_csvs[start_index:]
    n = min(frame_count, len(bodies_csvs))
    if n == 0:
        return earth_empty

    spin_check = earth_orientation.SpinStepCheck()
    spin_logged = False

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
                if not spin_logged:
                    spin_logged = True
                    if 'Sun' in df['name'].values:
                        print(f'Earth time-of-day: epoch {EARTH_EPOCH_TDB} TDB + time_s.')
                    else:
                        print('Earth time-of-day: arbitrary (no Sun row, e.g. hyperbola); '
                              'spin rate still sidereal.')
                warning = spin_check.warning(t_s, frame)
                if warning:
                    print(warning)
                q = mathutils.Quaternion(earth_orientation.earth_quaternion(t_s, EARTH_EPOCH_TDB))
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


CAMERA_AIM_NAME = 'DEM_CameraAim'  # Empty the camera's Track To follows (see setup_camera)


def setup_camera(frame_count, core_fn, earth_empty, has_solar, camera_mode=None,
                 rotation_interp=None, fov_deg=None):
    """Keyframe a tracking camera. ``core_fn(i)`` returns the frame-``i`` aim point.

    ``fov_deg`` (None = CAMERA_FOV_DEG) is the field of view across the frame's long side.

    ``rotation_interp`` (e.g. 'LINEAR', what DEMGrainsBlenderEarthCam.py uses)
    overrides the rotation keys' interpolation; None keeps Blender's default.

    The rotation keys are only exact on key frames. Between them (motion blur, or
    a --slowmo stretch) Bezier location + LINEAR rotation aimed the camera off the
    core, by 2.5-4.5 deg on a 40k flyby approach, so the body swung side to side.
    A Track To constraint on an aim Empty (CAMERA_AIM_NAME, keyed at the core on the
    same Bezier curve as the camera) aims it on every frame; on key frames it gives
    the same orientation as the keys (-Z at the core, Y up).

    Same time-remap hazard as keyframe_bodies_and_earth() above: this reads
    earth_empty's current (possibly time-remap-sampled) position per frame to
    aim the camera. Call before enabling any frame_map stretch.
    """
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.get(CAMERA_NAME) or bpy.data.cameras.new(CAMERA_NAME)
    cam_data.lens_unit = 'FOV'
    cam_data.angle = math.radians(CAMERA_FOV_DEG if fov_deg is None else fov_deg)
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

    if camera_mode is not None and camera_mode not in CAMERA_MODES:
        raise ValueError(f'camera_mode={camera_mode!r}; expected None or one of {CAMERA_MODES}')
    if camera_mode == 'earth_fixed':
        return _setup_earth_fixed_camera(cam_obj, frame_count, earth_empty)
    if camera_mode == 'earth_chase':
        return _setup_earth_chase_camera(cam_obj, frame_count, core_fn, earth_empty)
    _clear_tracking(cam_obj)  # an earlier earth_fixed / earth_chase run in this scene

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

    aim = bpy.data.objects.get(CAMERA_AIM_NAME)
    if aim is None:
        aim = bpy.data.objects.new(CAMERA_AIM_NAME, None)
        scene.collection.objects.link(aim)
    if aim.animation_data is not None:
        aim.animation_data_clear()

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
        aim.location = core
        aim.keyframe_insert(data_path='location', frame=frame)
    if rotation_interp:
        for fc in _fcurves(cam_obj, 'rotation_quaternion'):
            for kp in fc.keyframe_points:
                kp.interpolation = rotation_interp
    track = cam_obj.constraints.get('DEM_AimAtCore') or cam_obj.constraints.new('TRACK_TO')
    track.name = 'DEM_AimAtCore'
    track.target = aim
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'
    return cam_obj


def _clear_tracking(cam_obj):
    """Drop a camera's keys, DEM_ Track To constraints and parent (a re-run in the same scene)."""
    if cam_obj.animation_data is not None:
        cam_obj.animation_data_clear()
    for con in [c for c in cam_obj.constraints if c.name.startswith('DEM_')]:
        cam_obj.constraints.remove(con)
    cam_obj.parent = None


def _need_earth(earth_empty, camera_mode):
    if earth_empty is None:
        raise ValueError(
            f"camera_mode {camera_mode!r} needs Earth, but the bodies CSV has no Earth row "
            "(apophis_only run?)"
        )


def _setup_earth_chase_camera(cam_obj, frame_count, core_fn, earth_empty):
    """Over-the-shoulder chase: keyed behind the core on the Earth line, Track To on Earth.

    The Track To targets an Empty parented to Earth (EARTH_AIM_NAME) with use_target_z,
    whose Z is the orbit normal, so Earth is centred on every frame (also between keys
    under --slowmo) and screen-up stays the orbit normal, which the Earth line never
    crosses. Call at 1:1 time (before any frame_map), like setup_camera.
    """
    _need_earth(earth_empty, 'earth_chase')
    scene = bpy.context.scene
    _clear_tracking(cam_obj)
    n = min(scene.frame_end - scene.frame_start + 1, frame_count)
    cores, earths = [], []
    for i in range(n):
        scene.frame_set(scene.frame_start + i)
        cores.append(tuple(core_fn(i)))
        earths.append(tuple(earth_empty.matrix_world.translation))
    aspect = scene.render.resolution_x / max(1, scene.render.resolution_y)
    offsets, up = camera_framing.earth_chase_offsets(
        cores, earths, cam_obj.data.angle, aspect, ref_fov_rad=math.radians(CAMERA_FOV_DEG),
        ref_dist_bu=CAM_DIST_BU, drop=EARTH_CHASE_DROP,
    )
    for i in range(n):
        cam_obj.location = Vector(cores[i]) + Vector(offsets[i])
        cam_obj.keyframe_insert(data_path='location', frame=scene.frame_start + i)

    aim = bpy.data.objects.get(EARTH_AIM_NAME)
    if aim is None:
        aim = bpy.data.objects.new(EARTH_AIM_NAME, None)
        scene.collection.objects.link(aim)
    aim.parent = earth_empty
    aim.matrix_parent_inverse = mathutils.Matrix.Identity(4)
    aim.location = (0.0, 0.0, 0.0)
    aim.rotation_mode = 'QUATERNION'
    aim.rotation_quaternion = Vector(up).to_track_quat('Z', 'Y')
    track = cam_obj.constraints.new('TRACK_TO')
    track.name = 'DEM_AimAtEarth'
    track.target = aim
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'
    track.use_target_z = True
    scene.frame_set(scene.frame_start)
    print(f'Camera mode: Earth chase ({n} frames, {Vector(offsets[0]).length:.0f} BU behind the core, '
          f'fov {math.degrees(cam_obj.data.angle):.0f} deg).')
    return cam_obj


def _setup_earth_fixed_camera(cam_obj, frame_count, earth_empty):
    """Parent the camera to the Earth empty at one pose that frames Earth + Apophis's path.

    The Earth empty only translates (its Surface/Clouds children carry the spin), so
    Earth stays still on screen and Apophis (at the scene origin) crosses the frame.
    Reads the empty's keyed positions, so call it at 1:1 time (before any frame_map).
    """
    _need_earth(earth_empty, 'earth_fixed')
    scene = bpy.context.scene
    _clear_tracking(cam_obj)
    n = min(scene.frame_end - scene.frame_start + 1, frame_count)
    # Sample between keys too: Earth's Bezier location curve bulges past the keyed
    # points, and a --slowmo or motion-blur frame shows those in-betweens.
    earth_pos = []
    for i in range(n):
        for k in range(EARTH_FIXED_SUBSAMPLES if i < n - 1 else 1):
            scene.frame_set(scene.frame_start + i, subframe=k / EARTH_FIXED_SUBSAMPLES)
            earth_pos.append(tuple(earth_empty.matrix_world.translation))
    aspect = scene.render.resolution_x / max(1, scene.render.resolution_y)
    window_bu = None if EARTH_FIXED_WINDOW_KM is None else EARTH_FIXED_WINDOW_KM * EARTH_VIS_SCALE
    offset, right, up = camera_framing.earth_fixed_pose(
        earth_pos, EARTH_PHYSICAL_RADIUS_KM * EARTH_VIS_SCALE, cam_obj.data.angle, aspect,
        tilt_deg=EARTH_FIXED_TILT_DEG, margin=EARTH_FIXED_MARGIN, window_bu=window_bu,
        window_ca_factor=EARTH_FIXED_WINDOW_CA_FACTOR,
    )
    right, up = Vector(right), Vector(up)
    rot = mathutils.Matrix((right, up, right.cross(up))).transposed()  # columns = local X, Y, Z
    cam_obj.parent = earth_empty
    cam_obj.matrix_parent_inverse = mathutils.Matrix.Identity(4)
    cam_obj.location = Vector(offset)
    cam_obj.rotation_quaternion = rot.to_quaternion()
    scene.frame_set(scene.frame_start)
    print(f'Camera mode: Earth-fixed ({n} frames framed, {Vector(offset).length:.0f} BU from Earth).')
    return cam_obj


def _fcurves(obj, data_path):
    """F-curves of ``obj`` for ``data_path`` (legacy action.fcurves or 4.4+ layered actions)."""
    ad = obj.animation_data
    action = ad.action if ad else None
    if action is None:
        return []
    fcurves = list(getattr(action, 'fcurves', None) or [])
    if not fcurves:
        for layer in getattr(action, 'layers', []):
            for strip in getattr(layer, 'strips', []):
                for bag in getattr(strip, 'channelbags', []):
                    fcurves.extend(bag.fcurves)
    return [fc for fc in fcurves if fc.data_path == data_path]


def _new_sun_lamp():
    lamp_data = bpy.data.lights.new('DEM_SunLight', 'SUN')
    lamp_data.energy = SUN_LAMP_ENERGY
    lamp_data.angle = SUN_LAMP_ANGLE
    lamp = bpy.data.objects.new('DEM_SunLight', lamp_data)
    bpy.context.scene.collection.objects.link(lamp)
    return lamp


def ensure_sun_lamp(has_solar, bodies_dir):
    """Sun lamp exactly as DEMGrainsBlenderEarthCam.py makes it.

    Solar-system run with a Sun row: plain lamp, keyframed later by
    keyframe_bodies_and_earth(). No Sun row (hyperbola) or apophis_only: fixed
    APOPHIS_ONLY_SUN_DIRECTION. Solar-system run without a bodies dir: none.
    """
    existing = bpy.data.objects.get('DEM_SunLight')
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)
    bodies_ok = bool(bodies_dir) and os.path.isdir(bodies_dir)
    if has_solar and not bodies_ok:
        return None
    lamp = _new_sun_lamp()
    if not has_solar or 'Sun' not in bodies_row_names(bodies_dir):
        sun_dir = Vector(APOPHIS_ONLY_SUN_DIRECTION).normalized()
        lamp.rotation_euler = (-sun_dir).to_track_quat('-Z', 'Y').to_euler()
    return lamp


def _body_sphere(empty_name, body_name, radius_bu, material):
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
    empty = bpy.context.object
    empty.name = empty_name
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius_bu, segments=32, ring_count=16, location=(0.0, 0.0, 0.0)
    )
    sphere = bpy.context.object
    sphere.name = body_name
    if sphere.data.materials:
        sphere.data.materials[0] = material
    else:
        sphere.data.materials.append(material)
    _parent_part_to_empty(sphere, empty)
    return empty


def ensure_moon(has_solar, bodies_dir):
    """Grey Moon sphere under a 'Moon' Empty, only when the bodies CSV has a Moon row."""
    if not has_solar or 'Moon' not in bodies_row_names(bodies_dir):
        return None
    if bpy.data.objects.get('Moon') is not None:
        return bpy.data.objects['Moon']
    mat = bpy.data.materials.get('Moon_Surface')
    if mat is None:
        mat = bpy.data.materials.new('Moon_Surface')
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Base Color'].default_value = MOON_COLOR
            bsdf.inputs['Roughness'].default_value = 0.95
    return _body_sphere('Moon', 'Moon_Body', MOON_PHYSICAL_RADIUS_KM * EARTH_VIS_SCALE, mat)


def ensure_sun_visual(has_solar, bodies_dir):
    """Emissive Sun sphere under a 'Sun_Visual' Empty, only when the bodies CSV has a Sun row."""
    if not has_solar or 'Sun' not in bodies_row_names(bodies_dir):
        return None
    if bpy.data.objects.get('Sun_Visual') is not None:
        return bpy.data.objects['Sun_Visual']
    mat = bpy.data.materials.get('Sun_Surface')
    if mat is None:
        mat = bpy.data.materials.new('Sun_Surface')
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Base Color'].default_value = SUN_COLOR
            for name, val in (('Emission Color', SUN_COLOR), ('Emission', SUN_COLOR),
                              ('Emission Strength', SUN_EMISSION_STRENGTH)):
                if name in bsdf.inputs:
                    bsdf.inputs[name].default_value = val
    return _body_sphere('Sun_Visual', 'Sun_Body', SUN_BODY_RADIUS_BU, mat)


def add_camera_fill_light(cam_obj):
    """Point light parented to the camera (lights the camera-facing side of Apophis)."""
    existing = bpy.data.objects.get(CAM_FILL_LIGHT_NAME)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)
    fill_data = bpy.data.lights.new(CAM_FILL_LIGHT_NAME, CAM_FILL_LIGHT_TYPE)
    fill_data.energy = CAM_FILL_LIGHT_ENERGY
    fill = bpy.data.objects.new(CAM_FILL_LIGHT_NAME, fill_data)
    bpy.context.scene.collection.objects.link(fill)
    fill.parent = cam_obj
    return fill


def apply_viewport_clip():
    """Viewport clip range for km-to-BU scenes (GUI only; renders use the camera's own clip)."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.clip_start = VIEWPORT_CLIP_START
                    space.clip_end = VIEWPORT_CLIP_END


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
