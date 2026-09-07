"""
Bulk DEM visualisation — composite envelope + ejecta instancing (Objective 3).

Paste into Blender Scripting tab. Reads preprocessed assets from viz_preprocess.py
(``run_XXXX_viz/manifest.json``). Existing per-sphere importers are unchanged.
"""

import bpy
import csv
import json
import math
import os
import glob

import mathutils
import numpy as np
import pandas as pd
from mathutils import Matrix, Vector

# ── Configuration ─────────────────────────────────────────────────────────────
VIZ_MANIFEST = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/'
    '_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001_viz/manifest.json'
)
BODIES_CSV_DIR = None   # None = resolve from manifest bodies_csv_dir
IMPORT_SOLAR_SYSTEM = None
SETUP_CAMERA = True
CAMERA_MODE = None
USE_FRAME_CHANGE_HANDLER = True

GRAIN_COLOR = (0.35, 0.30, 0.25, 1.0)
ENVELOPE_COLOR = (0.38, 0.32, 0.27, 1.0)
EJECTA_ICO_SUBDIV = 1

# Earth / camera (same defaults as DEMGrainsBlenderEarthCam.py)
EARTH_MODEL_PATH = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/BlenderConvert/TheEarth1.blend'
)
EARTH_PART_NAMES = ['Surface', 'Atmosphere', 'Clouds']
EARTH_PHYSICAL_RADIUS_KM = 6371.0
EARTH_VIS_SCALE = 0.2
EARTH_SHELL_SCALE = {'Atmosphere': 1.004, 'Clouds': 1.002}
EARTH_SIDEREAL_DAY_S = 86164.0905
EARTH_SPIN_AXIS = (0.0, -0.3979, 0.9174)
EARTH_ROTATION_OFFSET_DEG = 0.0
EARTH_ROTATE_CLOUDS = True
EARTH_EMPTY_NAME = 'Earth'
MOON_PHYSICAL_RADIUS_KM = 1737.53
MOON_COLOR = (0.55, 0.55, 0.55, 1.0)
SUN_LAMP_ENERGY = 10.0
SUN_LAMP_ANGLE = 0.00931
SUN_VIS_SCALE = 0.003
SUN_BODY_RADIUS_BU = 10000.0
SUN_COLOR = (1.0, 1.0, 1.0, 1.0)
SUN_EMISSION_STRENGTH = 6000.0
APOPHIS_ONLY_SUN_DIRECTION = (1.0, 0.0, 0.0)
CAMERA_NAME = 'DEM_TrackCam'
CAMERA_FOV_DEG = 70.0
CAM_DIST_BU = 150.0
CAM_ANGLE_DEG = 30.0
CORE_GRAIN_FRACTION = 0.80
CAM_GRAIN_ONLY_AZIMUTH_DEG = 45.0
CAM_GRAIN_ONLY_ELEVATION_DEG = 20.0
CAM_CLIP_START = 0.01
CAM_CLIP_END = 20_000_000.0
# ─────────────────────────────────────────────────────────────────────────────

_viz_state = {
    'manifest': None,
    'viz_dir': None,
    'frame_ids': [],
    'max_fragments': 0,
    'fragment_objs': [],
    'ejecta_obj': None,
    'loaded_frame': -1,
}


def _load_manifest(path):
    with open(path, encoding='utf-8') as fh:
        manifest = json.load(fh)
    if manifest.get('viz_mode') != 'composite':
        print(f'WARNING: manifest viz_mode={manifest.get("viz_mode")!r} (expected "composite").')
    viz_dir = os.path.dirname(os.path.abspath(path))
    return manifest, viz_dir


def _resolve_bodies_dir(manifest, viz_dir):
    if BODIES_CSV_DIR:
        return BODIES_CSV_DIR
    rel = manifest.get('bodies_csv_dir', '')
    return os.path.normpath(os.path.join(viz_dir, rel))


def _resolve_grains_dir(manifest, viz_dir):
    rel = manifest.get('grains_csv_dir', '')
    return os.path.normpath(os.path.join(viz_dir, rel))


def _detect_solar_system(bodies_dir):
    csvs = sorted(glob.glob(os.path.join(bodies_dir, '*.csv')))
    if not csvs:
        return False
    try:
        names = set(pd.read_csv(csvs[0], usecols=['name'])['name'].astype(str))
    except (ValueError, KeyError, OSError):
        return False
    return 'Earth' in names or 'Sun' in names


def _grain_core_from_csv(csv_path, fraction):
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


def _make_material(name, color, roughness=0.85):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Base Color'].default_value = color
        bsdf.inputs['Roughness'].default_value = roughness
    return mat


def _mesh_from_npz_verts_faces(name, verts, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _count_max_fragments(viz_dir, frame_ids):
    env_dir = os.path.join(viz_dir, 'envelopes')
    max_f = 0
    for fid in frame_ids:
        paths = glob.glob(os.path.join(env_dir, f'{fid}_f*.npz'))
        max_f = max(max_f, len(paths))
    return max_f


def _setup_envelope_objects(max_fragments):
    mat = _make_material('VizEnvelope', ENVELOPE_COLOR)
    objs = []
    for i in range(max_fragments):
        name = f'VizFragment_{i:02d}'
        existing = bpy.data.objects.get(name)
        if existing:
            objs.append(existing)
            continue
        mesh = bpy.data.meshes.new(name + '_mesh')
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        objs.append(obj)
    return objs


def _setup_ejecta_point_cloud(n_points):
    name = 'VizEjecta'
    obj = bpy.data.objects.get(name)
    if obj is not None:
        bpy.data.objects.remove(obj, do_unlink=True)
    mesh = bpy.data.meshes.new(name + '_mesh')
    mesh.from_pydata([(0.0, 0.0, 0.0)] * max(n_points, 1), [], [])
    if 'radius' not in mesh.attributes:
        mesh.attributes.new(name='radius', type='FLOAT', domain='POINT')
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    _make_material('VizEjectaMat', GRAIN_COLOR)
    if obj.data.materials:
        obj.data.materials[0] = bpy.data.materials['VizEjectaMat']
    else:
        obj.data.materials.append(bpy.data.materials['VizEjectaMat'])
    _add_instance_on_points_modifier(obj, subdiv=EJECTA_ICO_SUBDIV)
    return obj


def _add_instance_on_points_modifier(obj, subdiv=1, radius_attr='radius'):
    """Geometry Nodes: icosphere instanced on points, scaled by radius attribute."""
    mod = obj.modifiers.new(name='VizEjectaGN', type='NODES')
    tree = bpy.data.node_groups.new('VizEjectaInstances', 'GeometryNodeTree')
    if hasattr(tree, 'interface'):
        tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')

    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    n_in = nodes.new('NodeGroupInput')
    n_out = nodes.new('NodeGroupOutput')
    n_in.location = (-600, 0)
    n_out.location = (600, 0)

    ico = nodes.new('GeometryNodeMeshIcoSphere')
    ico.inputs['Radius'].default_value = 1.0
    ico.inputs['Subdivisions'].default_value = int(subdiv)
    ico.location = (-200, -200)

    attr = nodes.new('GeometryNodeInputNamedAttribute')
    attr.data_type = 'FLOAT'
    if 'Name' in attr.inputs:
        attr.inputs['Name'].default_value = radius_attr
    attr.location = (-200, 200)

    combine = nodes.new('ShaderNodeCombineXYZ')
    combine.location = (0, 200)

    scale_inst = nodes.new('GeometryNodeScaleInstances')
    scale_inst.location = (200, 0)

    iop = nodes.new('GeometryNodeInstanceOnPoints')
    iop.location = (0, 0)

    links.new(n_in.outputs[0], iop.inputs['Points'])
    links.new(ico.outputs['Mesh'], iop.inputs['Instance'])
    links.new(attr.outputs['Attribute'], combine.inputs['X'])
    links.new(attr.outputs['Attribute'], combine.inputs['Y'])
    links.new(attr.outputs['Attribute'], combine.inputs['Z'])
    links.new(iop.outputs['Instances'], scale_inst.inputs['Instances'])
    links.new(combine.outputs['Vector'], scale_inst.inputs['Scale'])
    links.new(scale_inst.outputs['Instances'], n_out.inputs[0])

    mod.node_group = tree


def _update_envelope_obj(obj, npz_path):
    if not os.path.isfile(npz_path):
        obj.hide_viewport = True
        obj.hide_render = True
        return
    data = np.load(npz_path)
    verts = data['verts']
    faces = data['faces']
    mesh = obj.data
    if len(mesh.vertices) != len(verts) or len(mesh.polygons) != len(faces):
        mesh.clear_geometry()
        mesh.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    else:
        mesh.vertices.foreach_set('co', verts.ravel())
    mesh.update()
    obj.hide_viewport = False
    obj.hide_render = False


def _update_ejecta_obj(obj, npz_path):
    if not os.path.isfile(npz_path):
        return
    data = np.load(npz_path)
    pos = data['pos']
    radius = data['radius']
    mesh = obj.data
    n = len(pos)
    if len(mesh.vertices) != n:
        mesh.clear_geometry()
        mesh.from_pydata([tuple(p) for p in pos], [], [])
        if 'radius' not in mesh.attributes:
            mesh.attributes.new(name='radius', type='FLOAT', domain='POINT')
    else:
        mesh.vertices.foreach_set('co', pos.ravel())
    attr = mesh.attributes.get('radius')
    if attr is None:
        attr = mesh.attributes.new(name='radius', type='FLOAT', domain='POINT')
    attr.data.foreach_set('value', radius.ravel())
    mesh.update()


@bpy.app.handlers.persistent
def _viz_frame_change_handler(scene):
    st = _viz_state
    if not st['frame_ids']:
        return
    idx = scene.frame_current - scene.frame_start
    if idx < 0 or idx >= len(st['frame_ids']):
        return
    if idx == st['loaded_frame']:
        return
    fid = st['frame_ids'][idx]
    viz_dir = st['viz_dir']
    env_dir = os.path.join(viz_dir, 'envelopes')
    ej_path = os.path.join(viz_dir, 'ejecta', f'{fid}.npz')

    for i, obj in enumerate(st['fragment_objs']):
        npz_path = os.path.join(env_dir, f'{fid}_f{i}.npz')
        _update_envelope_obj(obj, npz_path)

    if st['ejecta_obj'] is not None:
        _update_ejecta_obj(st['ejecta_obj'], ej_path)

    st['loaded_frame'] = idx


def _ensure_earth_placeholder(has_solar, bodies_dir):
    """Create a minimal Earth Empty + UV sphere if solar-system bodies are available."""
    if not has_solar or not os.path.isdir(bodies_dir):
        return None
    earth_empty = bpy.data.objects.get(EARTH_EMPTY_NAME)
    if earth_empty is not None:
        return earth_empty
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
    earth_empty = bpy.context.object
    earth_empty.name = EARTH_EMPTY_NAME
    radius_bu = EARTH_PHYSICAL_RADIUS_KM * EARTH_VIS_SCALE
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius_bu, segments=32, ring_count=16, location=(0.0, 0.0, 0.0)
    )
    surf = bpy.context.object
    surf.name = 'Surface'
    surf.parent = earth_empty
    print(f'Earth placeholder created (radius {radius_bu:.1f} BU).')
    return earth_empty


def _keyframe_bodies_and_earth(bodies_dir, grain_files, has_solar, earth_empty=None):
    """Minimal bodies keyframing for Earth / Sun (subset of DEMGrainsBlenderEarthCam)."""
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

    bodies_csvs = sorted(glob.glob(os.path.join(bodies_dir, '*.csv')))
    n = min(len(grain_files), len(bodies_csvs))
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


def _setup_simple_camera(grain_files, earth_empty, has_solar):
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
        CAMERA_MODE == 'earth_track'
        if CAMERA_MODE in ('earth_track', 'grain_only')
        else (earth_empty is not None and has_solar)
    )
    n = min(scene.frame_end - scene.frame_start + 1, len(grain_files))
    _Z = Vector((0.0, 0.0, 1.0))
    _X = Vector((1.0, 0.0, 0.0))
    angle_rad = math.radians(CAM_ANGLE_DEG)
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)

    for i in range(n):
        frame = scene.frame_start + i
        scene.frame_set(frame)
        core = _grain_core_from_csv(grain_files[i], CORE_GRAIN_FRACTION)
        if use_earth and earth_empty is not None:
            earth_pos = earth_empty.matrix_world.translation.copy()
            earth_vec = earth_pos - core
            dist = earth_vec.length
            earth_from_core = earth_vec / dist if dist > 1e-6 else _X.copy()
            offset_dir = earth_from_core.cross(_Z)
            if offset_dir.length < 1e-4:
                offset_dir = earth_from_core.cross(_X)
            offset_dir.normalize()
            cam_pos = core + offset_dir * (CAM_DIST_BU * cos_a) + _Z * (CAM_DIST_BU * sin_a)
            look = (core - cam_pos).normalized()
            q = look.to_track_quat('-Z', 'Y')
        else:
            az = math.radians(CAM_GRAIN_ONLY_AZIMUTH_DEG)
            el = math.radians(CAM_GRAIN_ONLY_ELEVATION_DEG)
            offset = Vector((
                math.cos(el) * math.cos(az),
                math.cos(el) * math.sin(az),
                math.sin(el),
            )).normalized()
            cam_pos = core + offset * CAM_DIST_BU
            look = (core - cam_pos).normalized()
            q = look.to_track_quat('-Z', 'Y')
        cam_obj.location = cam_pos
        cam_obj.rotation_quaternion = q
        cam_obj.keyframe_insert(data_path='location', frame=frame)
        cam_obj.keyframe_insert(data_path='rotation_quaternion', frame=frame)


def main():
    manifest_path = os.path.abspath(VIZ_MANIFEST)
    manifest, viz_dir = _load_manifest(manifest_path)
    frame_ids = manifest['frame_ids']
    bodies_dir = _resolve_bodies_dir(manifest, viz_dir)
    grains_dir = _resolve_grains_dir(manifest, viz_dir)
    grain_files = sorted(glob.glob(os.path.join(grains_dir, '*.csv')))

    has_solar = (
        bool(IMPORT_SOLAR_SYSTEM)
        if IMPORT_SOLAR_SYSTEM is not None
        else _detect_solar_system(bodies_dir)
    )
    print(f'DEMBulkViz: {manifest["sim_name"]}/{manifest["run_name"]} '
          f'({len(frame_ids)} frames, mode={manifest.get("viz_mode")})')

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(1, len(frame_ids))
    scene.render.fps = 24

    max_frag = _count_max_fragments(viz_dir, frame_ids)
    fragment_objs = _setup_envelope_objects(max_frag)

    ej0 = os.path.join(viz_dir, 'ejecta', f'{frame_ids[0]}.npz')
    n_ejecta = len(np.load(ej0)['pos']) if os.path.isfile(ej0) else 1
    ejecta_obj = _setup_ejecta_point_cloud(n_ejecta)

    _viz_state.update({
        'manifest': manifest,
        'viz_dir': viz_dir,
        'frame_ids': frame_ids,
        'max_fragments': max_frag,
        'fragment_objs': fragment_objs,
        'ejecta_obj': ejecta_obj,
        'loaded_frame': -1,
    })

    if _viz_frame_change_handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_viz_frame_change_handler)
    if USE_FRAME_CHANGE_HANDLER:
        bpy.app.handlers.frame_change_pre.append(_viz_frame_change_handler)
        scene.frame_set(scene.frame_start)
        _viz_frame_change_handler(scene)

    earth_empty = _ensure_earth_placeholder(has_solar, bodies_dir)
    earth_empty = _keyframe_bodies_and_earth(bodies_dir, grain_files, has_solar, earth_empty)
    if SETUP_CAMERA and grain_files:
        _setup_simple_camera(grain_files, earth_empty, has_solar)

    print(
        f'Done. {len(fragment_objs)} envelope slot(s), ejecta GN on "{ejecta_obj.name}".\n'
        f'Scrub timeline or render — frame handler updates meshes from {viz_dir}.'
    )


main()
