"""
Bulk DEM visualisation — composite envelope + ejecta instancing (Objective 3).

Paste into Blender Scripting tab. Reads preprocessed assets from viz_preprocess.py
(``run_XXXX_viz/manifest.json``). Existing per-sphere importers are unchanged.
"""

import bpy
import hashlib
import json
import os
import glob
import sys

import numpy as np

_DEFAULT_BLENDER_CONVERT_DIR = (
    r'\\wsl.localhost\Ubuntu\home\mboyle\Honours\Code\BlenderConvert'
)
# Another machine: set HONOURS_CODE_DIR (Windows form) before starting Blender.
if os.environ.get('HONOURS_CODE_DIR'):
    _DEFAULT_BLENDER_CONVERT_DIR = os.path.join(os.environ['HONOURS_CODE_DIR'], 'BlenderConvert')
try:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _script_dir = None
# Blender sometimes sets __file__ to a bare filename (e.g. "\DEMBulkVizBlender.py"),
# which makes dirname point at the drive root — verify the module is actually there.
if _script_dir and os.path.isfile(os.path.join(_script_dir, 'DEMCinematicSetup.py')):
    BLENDER_CONVERT_DIR = _script_dir
else:
    BLENDER_CONVERT_DIR = _DEFAULT_BLENDER_CONVERT_DIR
if BLENDER_CONVERT_DIR not in sys.path:
    sys.path.insert(0, BLENDER_CONVERT_DIR)
import DEMCinematicSetup as cinematic  # noqa: E402

# ── Configuration ─────────────────────────────────────────────────────────────
VIZ_MANIFEST = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/torque_align_obj/run_0001_viz/manifest.json'
)
BODIES_CSV_DIR = None   # None = resolve from manifest bodies_csv_dir
IMPORT_SOLAR_SYSTEM = None
SETUP_CAMERA = True
CAMERA_MODE = None
CAMERA_FOV_DEG = None  # None = DEMCinematicSetup.CAMERA_FOV_DEG (70); across the frame's long side
USE_FRAME_CHANGE_HANDLER = True

GRAIN_COLOR = (0.35, 0.30, 0.25, 1.0)
ENVELOPE_COLOR = (0.38, 0.32, 0.27, 1.0)
EJECTA_ICO_SUBDIV = 3

CORE_GRAIN_FRACTION = 0.80
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
        raise ValueError(
            f'manifest viz_mode={manifest.get("viz_mode")!r} (expected "composite"); '
            f'use DEMBulkInstanceBlender.py for "instance" manifests.'
        )
    viz_dir = os.path.dirname(os.path.abspath(path))
    return manifest, viz_dir


def _resolve_bodies_dir(manifest, viz_dir):
    if BODIES_CSV_DIR:
        return BODIES_CSV_DIR
    rel = manifest.get('bodies_csv_dir', '')
    return os.path.normpath(os.path.join(viz_dir, rel))


def _resolve_grains_dir(manifest, viz_dir):
    rel = manifest.get('grains_dir', '')
    return os.path.normpath(os.path.join(viz_dir, rel))


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
    # Reuse the group by name: node_groups.new() always makes a new datablock,
    # so re-running the script would leave VizEjectaInstances.001, .002, ...
    tree = bpy.data.node_groups.get('VizEjectaInstances')
    if tree is None:
        tree = bpy.data.node_groups.new('VizEjectaInstances', 'GeometryNodeTree')
    if hasattr(tree, 'interface'):
        tree.interface.clear()
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
    # A convex hull always has F = 2V - 4, so comparing counts alone cannot tell
    # two frames apart: any two hulls with the same vertex count also have the
    # same face count, and reusing the buffer would keep the previous frame's
    # topology *and* vertex ordering. Key on the face data itself.
    topo_key = hashlib.blake2b(np.ascontiguousarray(faces).tobytes(), digest_size=16).hexdigest()
    if mesh.get('viz_topo_key') != topo_key or len(mesh.vertices) != len(verts):
        mesh.clear_geometry()
        mesh.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
        # from_pydata accepts out-of-range indices silently; validate() is the
        # only thing that reports them, and repairs what it can.
        if mesh.validate(verbose=False):
            print(f'WARNING: invalid geometry in {os.path.basename(npz_path)} '
                  f'(verts={len(verts)}, faces={len(faces)}) — repaired by validate().')
        mesh['viz_topo_key'] = topo_key
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


def main():
    manifest_path = os.path.abspath(VIZ_MANIFEST)
    manifest, viz_dir = _load_manifest(manifest_path)
    frame_ids = manifest['frame_ids']
    bodies_dir = _resolve_bodies_dir(manifest, viz_dir)
    grains_dir = _resolve_grains_dir(manifest, viz_dir)
    grain_files = sorted(glob.glob(os.path.join(grains_dir, '*.npz')))
    if SETUP_CAMERA and not grain_files:
        print(f'WARNING: no grain npz files in {grains_dir}; tracking camera skipped '
              '(CSV-era folder? re-run DEMDumpConvert.py).')

    has_solar = (
        bool(IMPORT_SOLAR_SYSTEM)
        if IMPORT_SOLAR_SYSTEM is not None
        else cinematic.detect_solar_system(bodies_dir)
    )
    print(f'DEMBulkViz: {manifest["sim_name"]}/{manifest["run_name"]} '
          f'({len(frame_ids)} frames, mode={manifest.get("viz_mode")})')

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
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
        cinematic.register_self_as_auto_run_module()
        scene.frame_set(scene.frame_start)
        _viz_frame_change_handler(scene)

    cinematic.ensure_sun_lamp(has_solar, bodies_dir)
    earth_empty = cinematic.ensure_earth_placeholder(has_solar, bodies_dir)
    cinematic.ensure_sun_visual(has_solar, bodies_dir)
    with cinematic.frame_handler_suspended(_viz_frame_change_handler):
        earth_empty = cinematic.keyframe_bodies_and_earth(
            bodies_dir, len(frame_ids), has_solar, earth_empty
        )
        if SETUP_CAMERA and grain_files:
            def _core_fn(i, _files=grain_files):
                d = np.load(_files[i])
                pts = np.column_stack([d['x_vis'], d['y_vis'], d['z_vis']]).astype(np.float64)
                return cinematic.grain_core(pts, CORE_GRAIN_FRACTION)
            cinematic.setup_camera(
                len(grain_files), _core_fn, earth_empty, has_solar, camera_mode=CAMERA_MODE,
                fov_deg=CAMERA_FOV_DEG,
            )
        scene.frame_set(scene.frame_start)

    print(
        f'Done. {len(fragment_objs)} envelope slot(s), ejecta GN on "{ejecta_obj.name}".\n'
        f'Scrub timeline or render — frame handler updates meshes from {viz_dir}.\n'
        f'Saved this .blend and reopening it later needs "Auto Run Python Scripts" '
        f'enabled (Edit > Preferences > Save & Load) — otherwise the envelope/ejecta '
        f'stay frozen at whatever frame was showing on save.'
    )


if __name__ == '__main__':
    main()
