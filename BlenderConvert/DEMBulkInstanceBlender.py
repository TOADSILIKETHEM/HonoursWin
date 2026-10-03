"""Bulk DEM visualisation -- pure point-cloud instancing (Option A, Objective 3).

Paste into Blender Scripting tab (or open the file directly). Reads a
``viz_mode: "instance"`` manifest from viz_preprocess_lite.py (static placeholder,
``static: true``), synthetic_flyby_test.py (per-frame rigid tumble test data,
``static: false``) or viz_preprocess_grains_instance.py (the real grains,
``static: false``, per-grain ``radius``). Existing per-sphere and composite
importers are unchanged.
"""

import json
import os
import sys
from collections import OrderedDict

import bpy
import numpy as np
from mathutils import Quaternion, Vector

_DEFAULT_BLENDER_CONVERT_DIR = (
    r'\\wsl.localhost\Ubuntu\home\mboyle\Honours\Code\BlenderConvert'
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

_CODE_DIR = os.path.dirname(BLENDER_CONVERT_DIR)
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

import DEMCinematicSetup as cinematic  # noqa: E402
import P0_InstancingSpike as p0  # noqa: E402
from viz.fcurve_handles import evaluate as bezier_evaluate  # noqa: E402

# -- Configuration ------------------------------------------------------------
VIZ_MANIFEST = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/torque_align_obj/run_0001_viz_instance_flyby_test/manifest.json'
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
# -- see _instance_frame_change_handler. Real-grain manifests with Bezier
# handles are interpolated on the same curve the per-sphere path keyframes;
# older manifests without handles hold each real frame (visible stepping).
SLOWMO_FACTOR = 4
TARGET_FPS = 60
# Shared instance mesh: the per-sphere path's 12x8 flat-shaded UV sphere
# (DEMGrainsBlenderEarthCam.py), so both paths render identical grains.
GRAIN_UV_SEGMENTS = 12
GRAIN_UV_RINGS = 8
PROCEDURAL_ROCK_MAT_NAME = 'Procedural rock'
INSTANCE_MAT_NAME = 'DEM_GrainInstance'
# Per-sphere camera settings (DEMGrainsBlenderEarthCam.py).
CORE_GRAIN_FRACTION = 0.80
CAMERA_ROTATION_INTERP = 'LINEAR'
SETUP_CAM_FILL_LIGHT = True
# -----------------------------------------------------------------------------

_viz_state = {
    'manifest': None,
    'viz_dir': None,
    'static': True,
    'point_obj_name': None,
    'loaded_frame': -1,
    'base_pos': None,  # frame-0 (unrotated) points, cached for analytic rigid_tumble interpolation
    'frames': None,  # grain_interp-style cache: frame index -> (pos, handle) for Bezier manifests
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
    for name in ('DEM_InstancePoints_mesh', 'DEM_InstanceGrainMesh'):
        mesh = bpy.data.meshes.get(name)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    group = bpy.data.node_groups.get('DEM_InstanceOnPoints')
    if group is not None and group.users == 0:
        bpy.data.node_groups.remove(group)
    mat = bpy.data.materials.get(INSTANCE_MAT_NAME)
    if mat is not None and mat.users == 0:
        bpy.data.materials.remove(mat)


def _make_grain_mesh():
    """Shared unit-radius instance mesh (GRAIN_UV_SEGMENTS x GRAIN_UV_RINGS UV sphere)."""
    import bmesh
    mesh = bpy.data.meshes.new('DEM_InstanceGrainMesh')
    bm = bmesh.new()
    try:
        # Same op and arguments bpy.ops.mesh.primitive_uv_sphere_add uses;
        # faces stay flat-shaded like the per-sphere path's primitives.
        bmesh.ops.create_uvsphere(
            bm, u_segments=GRAIN_UV_SEGMENTS, v_segments=GRAIN_UV_RINGS, radius=1.0,
        )
        bm.to_mesh(mesh)
    finally:
        bm.free()
    return mesh


def _instance_rock_material(src):
    """Copy of ``src`` whose Object texture coordinates are scaled by the instance radius.

    'Procedural rock' samples Object coordinates. A per-sphere grain's mesh is
    built at its own radius, so its Object coordinates span +/-radius; an
    instance is a unit mesh scaled by the GN Scale input, so its Object
    coordinates span +/-1. Multiplying by the instancer's ``radius`` attribute
    gives every instance the per-sphere texture scale.
    """
    old = bpy.data.materials.get(INSTANCE_MAT_NAME)
    if old is not None:
        bpy.data.materials.remove(old)
    mat = src.copy()
    mat.name = INSTANCE_MAT_NAME
    nt = mat.node_tree
    for tc in [n for n in nt.nodes if n.bl_idname == 'ShaderNodeTexCoord']:
        out = tc.outputs['Object']
        targets = [link.to_socket for link in out.links]
        if not targets:
            continue
        attr = nt.nodes.new('ShaderNodeAttribute')
        attr.attribute_type = 'INSTANCER'
        attr.attribute_name = p0.RADIUS_ATTR
        attr.location = (tc.location.x, tc.location.y - 220)
        scale = nt.nodes.new('ShaderNodeVectorMath')
        scale.operation = 'SCALE'
        scale.location = (tc.location.x + 180, tc.location.y)
        nt.links.new(out, scale.inputs[0])
        nt.links.new(attr.outputs['Fac'], scale.inputs['Scale'])
        for sock in targets:
            nt.links.new(scale.outputs['Vector'], sock)
    return mat


def _build_point_cloud(pos, grain_radius_vis, radii=None, rots=None, present=None):
    """Point-cloud mesh + shared grain mesh + GN 'Instance on Points', via P0_InstancingSpike.

    ``radii`` (float32, one per point) sets each instance's radius -- used by
    real-grain manifests (viz_preprocess_grains_instance.py) so polydisperse
    grains render at their own size. Without it every instance gets
    ``grain_radius_vis`` (static placeholder and synthetic manifests).
    ``rots`` (float32 Euler XYZ, one per point) fixes each instance's
    orientation to the per-sphere path's; without it GN draws random ones.
    ``present`` (bool, one per point) marks the grains in the current frame;
    when given it drives Instance on Points' Selection so absent grains are not
    drawn. Without it every point is drawn.
    """
    n_points = len(pos)
    mesh = bpy.data.meshes.new('DEM_InstancePoints_mesh')
    mesh.vertices.add(n_points)
    mesh.vertices.foreach_set('co', np.ascontiguousarray(pos, dtype=np.float32).ravel())
    mesh.update()

    attr = mesh.attributes.new(p0.RADIUS_ATTR, 'FLOAT', 'POINT')
    if radii is None:
        radius_values = np.full(n_points, grain_radius_vis, dtype=np.float32)
    else:
        radius_values = np.ascontiguousarray(radii, dtype=np.float32)
        if len(radius_values) != n_points:
            raise ValueError(f'radii has {len(radius_values)} entries, pos has {n_points}')
    attr.data.foreach_set('value', radius_values)
    if rots is not None:
        rot_values = np.ascontiguousarray(rots, dtype=np.float32)
        if rot_values.shape != (n_points, 3):
            raise ValueError(f'rots has shape {rot_values.shape}, expected ({n_points}, 3)')
        rot_attr = mesh.attributes.new(ROT_ATTR, 'FLOAT_VECTOR', 'POINT')
        rot_attr.data.foreach_set('vector', rot_values.ravel())
    if present is not None:
        present_values = np.ascontiguousarray(present, dtype=bool)
        if len(present_values) != n_points:
            raise ValueError(f'present has {len(present_values)} entries, pos has {n_points}')
        mesh.attributes.new(PRESENT_ATTR, 'BOOLEAN', 'POINT').data.foreach_set('value', present_values)

    point_obj = bpy.data.objects.new('DEM_InstancePoints', mesh)
    bpy.context.scene.collection.objects.link(point_obj)

    material = _instance_rock_material(_get_procedural_rock_material())
    grain_mesh = _make_grain_mesh()
    grain_mesh.materials.append(material)
    instance_obj = bpy.data.objects.new('DEM_InstanceMesh', grain_mesh)
    bpy.context.scene.collection.objects.link(instance_obj)
    instance_obj.hide_render = True
    instance_obj.hide_viewport = True

    group, _modifier = p0.build_geometry_nodes(point_obj, instance_obj)
    group.name = 'DEM_InstanceOnPoints'
    if rots is not None:
        _add_attribute_rotation(group)
    else:
        _add_random_rotation(group)
    if present is not None:
        _add_attribute_selection(group)
    return point_obj, group


ROT_ATTR = 'rot'


def _add_attribute_rotation(group):
    """Wire the per-point ``rot`` attribute (Euler XYZ) into Instance on Points."""
    n_iop = next(n for n in group.nodes if n.bl_idname == 'GeometryNodeInstanceOnPoints')
    n_rot = group.nodes.new('GeometryNodeInputNamedAttribute')
    n_rot.data_type = 'FLOAT_VECTOR'
    n_rot.inputs['Name'].default_value = ROT_ATTR
    n_rot.location = (n_iop.location.x - 300, n_iop.location.y + 200)
    group.links.new(n_rot.outputs['Attribute'], n_iop.inputs['Rotation'])


PRESENT_ATTR = 'present'


def _add_attribute_selection(group):
    """Wire the per-point ``present`` attribute into Instance on Points' Selection:
    grains absent from the current frame get no instance."""
    n_iop = next(n for n in group.nodes if n.bl_idname == 'GeometryNodeInstanceOnPoints')
    n_sel = group.nodes.new('GeometryNodeInputNamedAttribute')
    n_sel.data_type = 'BOOLEAN'
    n_sel.inputs['Name'].default_value = PRESENT_ATTR
    n_sel.location = (n_iop.location.x - 300, n_iop.location.y + 400)
    group.links.new(n_sel.outputs['Attribute'], n_iop.inputs['Selection'])


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


def _key_index(scene):
    """Fractional real-frame index for the scene's current (sub)frame.

    Uses the same remapped time Blender evaluates F-curves at (frame_map
    old/new, subframe included), so the points stay locked to the Earth,
    Sun and camera keyframes at any SLOWMO_FACTOR and under motion blur.
    """
    ctime = (scene.frame_current + scene.frame_subframe) * (
        scene.render.frame_map_old / scene.render.frame_map_new
    )
    return ctime - scene.frame_start


def _load_key(k):
    """(pos, handle, present) for real frame ``k`` (cached, 4 frames); present is None
    for points files written before it existed."""
    st = _viz_state
    cache = st['frames']
    if k in cache:
        cache.move_to_end(k)
        return cache[k]
    d = np.load(_points_path_for_frame(st['viz_dir'], st['manifest'], k))
    present = np.ascontiguousarray(d['present'], dtype=bool) if 'present' in d.files else None
    entry = (d['pos'].astype(np.float64), d['handle'].astype(np.float64), present)
    cache[k] = entry
    if len(cache) > 4:
        cache.popitem(last=False)
    return entry


def bezier_points(idx):
    """Grain positions at fractional real-frame index ``idx``: the per-sphere
    path's location F-curves (Bezier, AUTO_CLAMPED, continuous-acceleration
    handles precomputed by viz/fcurve_handles.py), constant outside the keys."""
    n = len(_viz_state['manifest']['frame_ids'])
    idx = min(max(float(idx), 0.0), float(n - 1))
    k = int(np.floor(idx))
    y0, h0, _ = _load_key(k)
    t = idx - k
    if k >= n - 1 or t == 0.0:
        return y0
    y1, h1, _ = _load_key(k + 1)
    return bezier_evaluate(y0, h0, y1, h1, t)


@bpy.app.handlers.persistent
def _instance_frame_change_handler(scene):
    """Re-upload the points for the current (sub)frame of a ``static: false`` manifest.

    Mirrors DEMBulkVizBlender.py's _update_ejecta_obj: only the vertex buffer
    changes (point count and radii are fixed for the whole run), so this is a
    foreach_set + mesh.update(), not a mesh rebuild. The real-frame index comes
    from _key_index(), i.e. the time Blender evaluates the Earth/camera F-curves at.

    Three paths:
    - Real-grain manifests with ``interpolation`` (viz_preprocess_grains_instance.py):
      Bezier between real frames, the exact curve the per-sphere path keyframes.
    - Synthetic rigid_tumble manifests carry ``angles_rad`` (exact rotation angle
      per real frame, about a fixed ``spin_axis``), evaluated at the fractional
      real-frame time.
    - Anything else (older real-grain manifests without handles): each real
      frame is held until the next one.
    """
    st = _viz_state
    manifest = st['manifest']
    if manifest is None or st['static']:
        return
    frame_ids = manifest['frame_ids']
    n = len(frame_ids)
    frac_idx = max(0.0, min(_key_index(scene), n - 1))
    obj = bpy.data.objects.get(st['point_obj_name'])
    if obj is None:
        return
    mesh = obj.data

    if st['frames'] is not None:
        if frac_idx == st['loaded_frame']:
            return
        pos = bezier_points(frac_idx).astype(np.float32)
        mesh.vertices.foreach_set('co', pos.ravel())
        # Visible iff present at the last real frame at or before this time,
        # like per-sphere's constant hide_render keys.
        present = _load_key(int(np.floor(frac_idx)))[2]
        if present is not None:
            mesh.attributes[PRESENT_ATTR].data.foreach_set('value', present)
        mesh.update()
        st['loaded_frame'] = frac_idx
        return

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
    first_points = np.load(first_points_path)
    pos = first_points['pos']
    if len(pos) != manifest['n_points']:
        raise ValueError(
            f"{os.path.basename(first_points_path)} has {len(pos)} points but manifest "
            f"says n_points={manifest['n_points']}"
        )
    # Real-grain manifests carry a per-grain radius; a grain's radius never
    # changes over a run, so setting it once here is enough -- the frame
    # handler keeps updating only 'co'.
    radii = first_points['radius'] if 'radius' in first_points.files else None
    rots = first_points['rot'] if 'rot' in first_points.files else None
    present = first_points['present'] if 'present' in first_points.files else None
    point_obj, _group = _build_point_cloud(
        pos, manifest['grain_radius_vis'], radii=radii, rots=rots, present=present
    )
    bezier = (
        not static
        and (manifest.get('interpolation') or {}).get('mode') == 'bezier'
        and 'handle' in first_points.files
    )
    if not static and not bezier and 'angles_rad' not in manifest:
        print('NOTE: manifest has no Bezier handles (older viz_preprocess_grains_instance.py '
              'output) -- each real frame is held; re-run the preprocess for smooth motion.')
    print(f'point cloud: {len(pos):,} points, grain_radius={manifest["grain_radius_vis"]:.4f} BU')

    _viz_state.update({
        'manifest': manifest,
        'viz_dir': viz_dir,
        'static': static,
        'point_obj_name': point_obj.name,
        'loaded_frame': 0,
        # frame 0 has angle_rad == 0 by construction (t0 == times[0] in
        # synthetic_flyby_test.py), so it doubles as the unrotated base shape.
        'base_pos': np.ascontiguousarray(pos, dtype=np.float32),
        'frames': OrderedDict() if bezier else None,
    })

    if _instance_frame_change_handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_instance_frame_change_handler)
    if not static:
        bpy.app.handlers.frame_change_pre.append(_instance_frame_change_handler)
        cinematic.register_self_as_auto_run_module()

    # Same lights and bodies as DEMGrainsBlenderEarthCam.py.
    cinematic.ensure_sun_lamp(has_solar, bodies_dir)
    earth_empty = cinematic.ensure_earth_placeholder(has_solar, bodies_dir)
    cinematic.ensure_moon(has_solar, bodies_dir)
    cinematic.ensure_sun_visual(has_solar, bodies_dir)
    cinematic.apply_viewport_clip()
    with cinematic.frame_handler_suspended(_instance_frame_change_handler):
        earth_empty = cinematic.keyframe_bodies_and_earth(
            bodies_dir, len(frame_ids), has_solar, earth_empty,
            start_index=int(manifest.get('bodies_start_index', 0)),
        )
        if SETUP_CAMERA:
            def _core_fn(i):
                if static:
                    return Vector((0.0, 0.0, 0.0))  # static placeholder, centred on Apophis CoM
                # Per-sphere camera: centroid of the innermost CORE_GRAIN_FRACTION of
                # the grains present in that frame (absent slots hold stale positions).
                d = np.load(_points_path_for_frame(viz_dir, manifest, i))
                pts = d['pos'][d['present']] if 'present' in d.files else d['pos']
                return cinematic.grain_core(pts.astype(np.float64), CORE_GRAIN_FRACTION)
            cam_obj = cinematic.setup_camera(
                len(frame_ids), _core_fn, earth_empty, has_solar, camera_mode=CAMERA_MODE,
                rotation_interp=CAMERA_ROTATION_INTERP,
            )
            if SETUP_CAM_FILL_LIGHT:
                cinematic.add_camera_fill_light(cam_obj)
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
