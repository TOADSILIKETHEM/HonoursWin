"""Bulk DEM visualisation -- pure point-cloud instancing (Option A, Objective 3).

Paste into Blender Scripting tab (or open the file directly). Reads a
``viz_mode: "instance"`` manifest from viz_preprocess_lite.py (static placeholder,
``static: true``) or synthetic_flyby_test.py (per-frame rigid tumble test data,
``static: false``). Existing per-sphere and composite importers are unchanged.
"""

import json
import os
import sys

import bpy
import numpy as np
from mathutils import Quaternion, Vector

_DEFAULT_BLENDER_CONVERT_DIR = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/BlenderConvert'
)
try:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _script_dir = None
# Blender sometimes sets __file__ to a bare filename (e.g. "\DEMBulkInstanceBlender.py"),
# which makes dirname point at the drive root — verify the module is actually there.
if _script_dir and os.path.isfile(os.path.join(_script_dir, 'DEMCinematicSetup.py')):
    BLENDER_CONVERT_DIR = _script_dir
else:
    BLENDER_CONVERT_DIR = _DEFAULT_BLENDER_CONVERT_DIR
if BLENDER_CONVERT_DIR not in sys.path:
    sys.path.insert(0, BLENDER_CONVERT_DIR)

import DEMCinematicSetup as cinematic  # noqa: E402
import P0_InstancingSpike as p0  # noqa: E402

# -- Configuration ------------------------------------------------------------
VIZ_MANIFEST = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/torque_align_obj/run_0001_viz_instance/manifest.json'
)
BODIES_CSV_DIR = None
IMPORT_SOLAR_SYSTEM = None
SETUP_CAMERA = True
CAMERA_MODE = None
RENDER_RESOLUTION = (1920, 1080)
# Time remap: stretch the same n_frames of real data over
# n_frames * SLOWMO_FACTOR timeline frames (Blender's built-in frame_map_old/new),
# so Earth/body F-curve keyframes interpolate smoothly across more frames at a
# higher fps -- same simulated duration, slower/smoother playback. For a
# synthetic rigid_tumble manifest (has "angles_rad"), the point cloud is ALSO
# interpolated smoothly (exact analytic rotation at the fractional real frame)
# -- see _instance_frame_change_handler. Any other static:false manifest (real
# per-frame simulation data, once implemented) has no analytic model to
# interpolate, so each real points frame is held for SLOWMO_FACTOR consecutive
# timeline frames instead -- expect visible stepping there until an
# interpolation scheme for real data exists.
SLOWMO_FACTOR = 4
TARGET_FPS = 60
GRAIN_SUBDIV = 1
PROCEDURAL_ROCK_MAT_NAME = 'Procedural rock'
# -----------------------------------------------------------------------------

_viz_state = {
    'manifest': None,
    'viz_dir': None,
    'static': True,
    'point_obj_name': None,
    'loaded_frame': -1,
    'slowmo_factor': 1,
    'base_pos': None,  # frame-0 (unrotated) points, cached for analytic rigid_tumble interpolation
}


def _load_manifest(path):
    with open(path, encoding='utf-8') as fh:
        manifest = json.load(fh)
    if manifest.get('viz_mode') != 'instance':
        raise ValueError(
            f'manifest viz_mode={manifest.get("viz_mode")!r} (expected "instance"); '
            f'use DEMBulkVizBlender.py for "composite" manifests.'
        )
    if not bool(manifest.get('static', True)) and 'points_dir' not in manifest:
        raise ValueError('manifest static=false but has no "points_dir"')
    viz_dir = os.path.dirname(os.path.abspath(path))
    return manifest, viz_dir


def _points_path_for_frame(viz_dir, manifest, frame_idx):
    """Path to the points .npz for ``frame_idx``: the single static file, or
    ``points_dir/{frame_id}.npz`` for a per-frame (``static: false``) manifest."""
    if bool(manifest.get('static', True)):
        return os.path.join(viz_dir, manifest['points_path'])
    frame_ids = manifest['frame_ids']
    frame_idx = max(0, min(frame_idx, len(frame_ids) - 1))
    return os.path.join(viz_dir, manifest['points_dir'], f'{frame_ids[frame_idx]}.npz')


def _resolve_bodies_dir(manifest, viz_dir):
    if BODIES_CSV_DIR:
        return BODIES_CSV_DIR
    rel = manifest.get('bodies_csv_dir', '')
    return os.path.normpath(os.path.join(viz_dir, rel))


def _get_procedural_rock_material():
    """Look up the 'Procedural rock' material already validated on Blenders/11.blend.

    Not auto-appended: several similarly-named rock materials exist under
    BlenderConvert/Blenders/assets/materials/, so guessing the source .blend
    would risk silently picking the wrong one. Append it manually (File >
    Append > Material, from BlenderConvert/Blenders/11.blend or
    P0_Apophis_1M.blend) before running this script if it is not already
    present.
    """
    mat = bpy.data.materials.get(PROCEDURAL_ROCK_MAT_NAME)
    if mat is None:
        raise RuntimeError(
            f'{PROCEDURAL_ROCK_MAT_NAME!r} material not found. Append it from '
            f'BlenderConvert/Blenders/11.blend or P0_Apophis_1M.blend '
            f'(File > Append > Material) before running this script.'
        )
    return mat


def _cleanup_previous():
    """Remove datablocks from a prior run so re-running this script is idempotent.

    bpy.data.meshes.new() / node_groups.new() always create a new datablock
    (never reuse by name), so without this a re-run leaks
    DEM_InstanceMesh.001, P0_InstanceOnPoints.001, ... on every click of
    Run Script -- the same class of bug DEMBulkVizBlender.py's GN node-group
    already had fixed.
    """
    for name in ('DEM_InstancePoints', 'DEM_InstanceMesh'):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    for name in ('DEM_InstancePoints_mesh', 'DEM_InstanceIco'):
        mesh = bpy.data.meshes.get(name)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    group = bpy.data.node_groups.get('DEM_InstanceOnPoints')
    if group is not None and group.users == 0:
        bpy.data.node_groups.remove(group)


def _build_point_cloud(pos, grain_radius_vis, subdiv):
    """Point-cloud mesh + shared icosphere + GN 'Instance on Points', via P0_InstancingSpike."""
    n_points = len(pos)
    mesh = bpy.data.meshes.new('DEM_InstancePoints_mesh')
    mesh.vertices.add(n_points)
    mesh.vertices.foreach_set('co', np.ascontiguousarray(pos).ravel())
    mesh.update()

    attr = mesh.attributes.new(p0.RADIUS_ATTR, 'FLOAT', 'POINT')
    attr.data.foreach_set('value', np.full(n_points, grain_radius_vis, dtype=np.float32))

    point_obj = bpy.data.objects.new('DEM_InstancePoints', mesh)
    bpy.context.scene.collection.objects.link(point_obj)

    material = _get_procedural_rock_material()
    ico_mesh = p0._make_icosphere(subdiv)
    ico_mesh.name = 'DEM_InstanceIco'
    ico_mesh.materials.append(material)
    instance_obj = bpy.data.objects.new('DEM_InstanceMesh', ico_mesh)
    bpy.context.scene.collection.objects.link(instance_obj)
    instance_obj.hide_render = True
    instance_obj.hide_viewport = True

    group, _modifier = p0.build_geometry_nodes(point_obj, instance_obj)
    group.name = 'DEM_InstanceOnPoints'
    _add_random_rotation(group)
    return point_obj, group


def _add_random_rotation(group):
    """Wire a per-point random rotation into the GN group's Instance on Points node.

    Avoids a clone-tiling look across shared-mesh instances (spec requirement).
    """
    import math
    n_iop = next(n for n in group.nodes if n.bl_idname == 'GeometryNodeInstanceOnPoints')
    n_id = group.nodes.new('GeometryNodeInputID')
    n_id.location = (n_iop.location.x - 300, n_iop.location.y + 200)
    n_rand = group.nodes.new('FunctionNodeRandomValue')
    n_rand.data_type = 'FLOAT_VECTOR'
    n_rand.location = (n_iop.location.x - 150, n_iop.location.y + 200)
    n_rand.inputs['Min'].default_value = (0.0, 0.0, 0.0)
    n_rand.inputs['Max'].default_value = (2 * math.pi, 2 * math.pi, 2 * math.pi)
    group.links.new(n_id.outputs['ID'], n_rand.inputs['ID'])
    rotation_output = next(
        s for s in n_rand.outputs if s.type == 'VECTOR'
    )
    group.links.new(rotation_output, n_iop.inputs['Rotation'])


@bpy.app.handlers.persistent
def _instance_frame_change_handler(scene):
    """Reload and re-upload the current frame's points for a ``static: false`` manifest.

    Mirrors DEMBulkVizBlender.py's _update_ejecta_obj: only the vertex buffer
    changes (point count and grain_radius_vis are fixed for the whole run), so
    this is a foreach_set + mesh.update(), not a mesh rebuild.

    Two paths:
    - Synthetic rigid_tumble manifests carry ``angles_rad`` (exact rotation angle
      per real frame, about a fixed ``spin_axis``) -- with SLOWMO_FACTOR > 1 this
      lets the tumble be evaluated at the exact fractional real-frame time instead
      of holding each real frame for SLOWMO_FACTOR timeline frames, which reads as
      jittery/stepped motion once the camera/Earth (F-curve interpolated) move
      smoothly across the same stretched timeline.
    - Anything else (real per-frame simulation data, once implemented) has no
      analytic model to interpolate -- held-frame reload is the only option.
    """
    st = _viz_state
    manifest = st['manifest']
    if manifest is None or st['static']:
        return
    frame_ids = manifest['frame_ids']
    n = len(frame_ids)
    frac_idx = (scene.frame_current - scene.frame_start) / st['slowmo_factor']
    frac_idx = max(0.0, min(frac_idx, n - 1))
    obj = bpy.data.objects.get(st['point_obj_name'])
    if obj is None:
        return
    mesh = obj.data

    angles = manifest.get('angles_rad')
    base_pos = st.get('base_pos')
    if angles is not None and base_pos is not None:
        if frac_idx == st['loaded_frame']:
            return
        i0 = int(frac_idx)
        i1 = min(i0 + 1, n - 1)
        t = frac_idx - i0
        angle = angles[i0] * (1.0 - t) + angles[i1] * t
        axis = Vector(manifest['spin_axis']).normalized()
        rot = np.array(Quaternion(axis, angle).to_matrix(), dtype=np.float32)
        pos = (base_pos @ rot.T).astype(np.float32)
        mesh.vertices.foreach_set('co', pos.ravel())
        mesh.update()
        st['loaded_frame'] = frac_idx
        return

    idx = int(frac_idx)
    if idx == st['loaded_frame']:
        return
    path = _points_path_for_frame(st['viz_dir'], manifest, idx)
    if not os.path.isfile(path):
        print(f'WARNING: missing points file for frame {idx}: {path}')
        return
    pos = np.load(path)['pos']
    if len(mesh.vertices) != len(pos):
        print(f'WARNING: frame {idx} has {len(pos)} points, mesh has '
              f'{len(mesh.vertices)}; skipping update (point count must stay fixed).')
        return
    mesh.vertices.foreach_set('co', np.ascontiguousarray(pos, dtype=np.float32).ravel())
    mesh.update()
    st['loaded_frame'] = idx


def main():
    manifest_path = os.path.abspath(VIZ_MANIFEST)
    manifest, viz_dir = _load_manifest(manifest_path)
    static = bool(manifest.get('static', True))
    if manifest.get('synthetic'):
        print(f'NOTE: synthetic test manifest (motion_model='
              f'{manifest.get("motion_model")!r}) -- not real simulation data.')
    frame_ids = manifest['frame_ids']
    bodies_dir = _resolve_bodies_dir(manifest, viz_dir)

    has_solar = (
        bool(IMPORT_SOLAR_SYSTEM)
        if IMPORT_SOLAR_SYSTEM is not None
        else cinematic.detect_solar_system(bodies_dir)
    )
    print(f'DEMBulkInstanceBlender: {manifest["sim_name"]}/{manifest["run_name"]} '
          f'({len(frame_ids)} frames, mode={manifest.get("viz_mode")}, '
          f'static={manifest.get("static")})')
    if SLOWMO_FACTOR != 1:
        print(f'NOTE: SLOWMO_FACTOR={SLOWMO_FACTOR} -- timeline frame N shows real '
              f'frame N/{SLOWMO_FACTOR}. Real frame R is now at timeline frame '
              f'R*{SLOWMO_FACTOR}.')

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    # Author at 1:1 time (no remap yet) -- keyframe_bodies_and_earth/setup_camera
    # call scene.frame_set() internally to sample Earth's just-created position
    # while building the camera track; if frame_map were active here, that
    # sampling would read Earth's position at the wrong (remapped) time and
    # the camera would be aimed using the wrong slice of its motion.
    scene.frame_start = 1
    scene.frame_end = max(1, len(frame_ids))
    scene.render.frame_map_old = 100
    scene.render.frame_map_new = 100
    scene.render.resolution_x, scene.render.resolution_y = RENDER_RESOLUTION
    scene.render.resolution_percentage = 100

    _cleanup_previous()

    first_points_path = _points_path_for_frame(viz_dir, manifest, 0)
    pos = np.load(first_points_path)['pos']
    if len(pos) != manifest['n_points']:
        raise ValueError(
            f"{os.path.basename(first_points_path)} has {len(pos)} points but manifest "
            f"says n_points={manifest['n_points']}"
        )
    point_obj, _group = _build_point_cloud(pos, manifest['grain_radius_vis'], GRAIN_SUBDIV)
    print(f'point cloud: {len(pos):,} points, grain_radius={manifest["grain_radius_vis"]:.4f} BU')

    _viz_state.update({
        'manifest': manifest,
        'viz_dir': viz_dir,
        'static': static,
        'point_obj_name': point_obj.name,
        'loaded_frame': 0,
        'slowmo_factor': SLOWMO_FACTOR,
        # frame 0 has angle_rad == 0 by construction (t0 == times[0] in
        # synthetic_flyby_test.py), so it doubles as the unrotated base shape.
        'base_pos': np.ascontiguousarray(pos, dtype=np.float32),
    })

    if _instance_frame_change_handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_instance_frame_change_handler)
    if not static:
        bpy.app.handlers.frame_change_pre.append(_instance_frame_change_handler)
        cinematic.register_self_as_auto_run_module()

    earth_empty = cinematic.ensure_earth_placeholder(has_solar, bodies_dir)
    with cinematic.frame_handler_suspended(_instance_frame_change_handler):
        earth_empty = cinematic.keyframe_bodies_and_earth(
            bodies_dir, len(frame_ids), has_solar, earth_empty,
            start_index=int(manifest.get('bodies_start_index', 0)),
        )
        if SETUP_CAMERA:
            def _core_fn(_i):
                return Vector((0.0, 0.0, 0.0))  # static rigid body, centered on Apophis CoM
            cinematic.setup_camera(
                len(frame_ids), _core_fn, earth_empty, has_solar, camera_mode=CAMERA_MODE
            )
        scene.frame_set(scene.frame_start)

    # Apply time-stretch for playback only, now that all keyframes are authored
    # at their correct 1:1 times.
    if SLOWMO_FACTOR != 1:
        scene.frame_end = max(1, len(frame_ids)) * SLOWMO_FACTOR
        scene.render.frame_map_old = 100
        scene.render.frame_map_new = 100 * SLOWMO_FACTOR
    scene.render.fps = TARGET_FPS if TARGET_FPS else 24
    scene.frame_set(scene.frame_start)

    print(f'Done. "{point_obj.name}" GN-instanced, {len(pos):,} points.')
    if not static:
        print(
            'Saved this .blend and reopening it later needs "Auto Run Python Scripts" '
            'enabled (Edit > Preferences > Save & Load) — otherwise the per-frame '
            'point-cloud reload stays frozen at whatever frame was showing on save.'
        )


if __name__ == '__main__':
    main()
