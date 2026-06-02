import bpy
import mathutils
import pandas as pd
import glob
import os
from dataclasses import dataclass
from typing import Optional
from mathutils import Matrix, Vector

# ── Configuration ─────────────────────────────────────────────────────────────
# Path to the dem_grains_output/ folder produced by DEMtoCSV.py.
GRAINS_CSV_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/torque_align_obj_fine_dt/run_0001_grains_output/'

# Path to the bodies output folder — filenames match GRAINS_CSV_DIR.
# Used to read the Sun, Earth, and Apophis positions each frame.
# Set to '' or a nonexistent path to skip Sun lamp and Earth entirely.
BODIES_CSV_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/torque_align_obj_fine_dt/run_0001_bodies_output/'
# OBJ-cropped opposite_near_h breakup, 5 min dumps (~1297 frames): fine_dt batch.

# Sun lamp settings.
SUN_LAMP_ENERGY = 10.0
SUN_LAMP_ANGLE  = 0.00931   # radians; 0.00931 ≈ 0.53° (Sun's angular radius at ~1 AU)

# Interpolation applied to all grain, Sun lamp, and Earth F-curves.
SMOOTH_INTERPOLATION = True
INTERPOLATION_MODE   = 'BEZIER'   # 'BEZIER' or 'LINEAR'
HANDLE_MODE          = 'AUTO_CLAMPED'

# Material colour for the rubble-pile grains (RGBA, 0-1).
GRAIN_COLOR = (0.35, 0.30, 0.25, 1.0)

# Earth 3-D model (Surface, Atmosphere, Clouds from TheEarth.blend).
EARTH_MODEL_PATH         = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/BlenderConvert/TheEarth.blend'
EARTH_PART_NAMES         = ['Surface', 'Atmosphere', 'Clouds']
EARTH_PHYSICAL_RADIUS_KM = 6371.0

# Scale for Earth's position and radius relative to the Apophis body frame.
# 1 BU = 1 / EARTH_VIS_SCALE km.
# Default 0.005 → Earth at ~190 BU at closest approach (~38 000 km); radius ~32 BU.
# Increase to push Earth further away; decrease to bring it closer.
EARTH_VIS_SCALE = 0.005   # BU per km
# ─────────────────────────────────────────────────────────────────────────────
# COORDINATE NOTE
# ───────────────
# Grains: x_vis = x_rel_km × GRAIN_VIS_SCALE (set in DEMtoCSV.py, default 50).
#   Apophis CoM sits at the world origin; grains are within ±25 BU.
# Earth:  (earth_km - apophis_km) × EARTH_VIS_SCALE.
#   Same Apophis-at-origin frame; EARTH_VIS_SCALE is independent of GRAIN_VIS_SCALE.
# Sun lamp: rotation only (from normalised Sun–Apophis km vector).
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


# ── Earth model import machinery (adapted from OnlyEarth_ApophisTrueSize.py) ──

@dataclass
class BodyModelConfig:
    """Settings for importing a detailed mesh parented to a trajectory Empty."""
    body_label: str
    model_path: str
    model_format: str              # 'BLEND', 'FBX', or 'OBJ'
    part_names: list
    collection_name: Optional[str]
    model_reference_radius_bu: float
    auto_reference_radius: bool
    target_radius_bu: Optional[float]
    center_object_name: str
    auto_center: bool
    auto_scale: bool
    blend_append_all_objects_if_unmatched: bool = False


def _get_fallback_radius():
    """Fallback radius used when target_radius_bu is None (not needed for Earth)."""
    return 0.01


def _link_object_to_collection(obj, coll):
    try:
        coll.objects.link(obj)
    except RuntimeError:
        pass


def _parent_part_to_empty(obj, empty_obj):
    """Parent obj to empty_obj while preserving current world transform."""
    mw = obj.matrix_world.copy()
    obj.parent = empty_obj
    obj.matrix_parent_inverse = empty_obj.matrix_world.inverted()
    obj.matrix_world = mw


def _object_base_name(name):
    """Strip Blender's numeric suffix (.001) for name comparison."""
    if '.' in name:
        head, tail = name.rsplit('.', 1)
        if tail.isdigit():
            return head
    return name


def _blend_object_names_for_append(library_object_names, cfg):
    """Pick which object datablock names to append from a .blend."""
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
    """World-space center of the AABB union of mesh objects."""
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
    """Approximate radius from world-space AABB (half longest edge)."""
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
    """Translate bbox center to Empty and scale to target_radius_bu."""
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

    sf_str = f'{scale_factor:.6g}' if scale_factor is not None else 'skipped'
    print(
        f'  {cfg.body_label} layout: target_radius={target_radius_bu:.6g}, '
        f'reference_radius={reference_radius:.6g} ({ref_source}), scale_factor={sf_str}'
    )


def import_body_model(empty_obj, cfg, target_radius_bu):
    """Import a .blend file and parent mesh parts to empty_obj."""
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
    imported_bases = {_object_base_name(o.name) for o in blend_appended} if 'blend_appended' in dir() else set()
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
    )
    print(f'Importing Earth from {os.path.basename(EARTH_MODEL_PATH)} ...')
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
    earth_empty      = bpy.context.object
    earth_empty.name = 'Earth'
    import_body_model(earth_empty, earth_cfg, EARTH_PHYSICAL_RADIUS_KM * EARTH_VIS_SCALE)
elif EARTH_MODEL_PATH and not os.path.exists(EARTH_MODEL_PATH):
    print(f'WARNING: EARTH_MODEL_PATH not found ({EARTH_MODEL_PATH}) — Earth skipped.')


# ── First pass: read frame 1 and create one sphere per grain ──────────────────
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

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

print('Spheres created.')

# ── Second pass: keyframe grain positions, Sun lamp rotation, Earth position ──
print(f'Keyframing {len(csv_files)} frames ...')

bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end   = len(csv_files)

for frame_num, csv_file in enumerate(csv_files, start=1):
    df = pd.read_csv(csv_file)
    bpy.context.scene.frame_set(frame_num)

    # Grain positions.
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

    # Sun lamp and Earth both need the bodies CSV — read once per frame.
    if sun_lamp_obj is not None or earth_empty is not None:
        bodies_path = _bodies_csv_for(csv_file)
        if bodies_path:
            bdf     = pd.read_csv(bodies_path)
            sun_row = bdf.loc[bdf['name'] == 'Sun']
            apo_row = bdf.loc[bdf['name'] == 'Apophis']

            # Sun lamp orientation.
            if sun_lamp_obj is not None and not sun_row.empty and not apo_row.empty:
                sun_km  = sun_row[['x_km', 'y_km', 'z_km']].values[0]
                apo_km  = apo_row[['x_km', 'y_km', 'z_km']].values[0]
                sun_rel = sun_km - apo_km
                sun_dir = mathutils.Vector(sun_rel.tolist()).normalized()
                rot = sun_dir.to_track_quat('-Z', 'Y').to_euler()
                sun_lamp_obj.rotation_euler = rot
                sun_lamp_obj.keyframe_insert(data_path='rotation_euler', frame=frame_num)

            # Earth position relative to Apophis CoM.
            earth_row = bdf.loc[bdf['name'] == 'Earth']
            if earth_empty is not None and not earth_row.empty and not apo_row.empty:
                earth_km = earth_row[['x_km', 'y_km', 'z_km']].values[0]
                apo_km   = apo_row[['x_km',  'y_km',  'z_km']].values[0]
                rel_km   = earth_km - apo_km
                earth_empty.location = (
                    float(rel_km[0] * EARTH_VIS_SCALE),
                    float(rel_km[1] * EARTH_VIS_SCALE),
                    float(rel_km[2] * EARTH_VIS_SCALE),
                )
                earth_empty.keyframe_insert(data_path='location', frame=frame_num)

# ── Third pass: smooth F-curves ───────────────────────────────────────────────
if SMOOTH_INTERPOLATION:
    print('Smoothing F-curves ...')
    for gid in range(n_grains):
        obj = bpy.data.objects.get(f'DEM_Grain_{gid:03d}')
        if obj:
            _smooth_fcurves(obj, 'location')
    if sun_lamp_obj is not None:
        _smooth_fcurves(sun_lamp_obj, 'rotation_euler')
    if earth_empty is not None:
        _smooth_fcurves(earth_empty, 'location')

print(
    f'Done — {n_grains} DEM grains animated over {len(csv_files)} frame(s).\n'
    'Positions are in Apophis body frame (Apophis at world origin).\n'
    f'Earth Empty "Earth" is at (earth_km - apophis_km) × EARTH_VIS_SCALE={EARTH_VIS_SCALE} BU/km.\n'
    'Sun lamp "DEM_SunLight" direction is keyframed from physical PHANTOM positions.\n'
    'Tune EARTH_VIS_SCALE, SUN_LAMP_ENERGY / SUN_LAMP_ANGLE at the top as needed.'
)
