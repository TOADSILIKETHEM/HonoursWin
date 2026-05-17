import bpy
import pandas as pd
import glob
import os
from dataclasses import dataclass
from typing import Optional

from mathutils import Matrix, Vector

# -- Configuration -------------------------------------------------------------
CSV_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/ShortCSVlist/'
SCALE = 1000.0   # 1 Blender unit = 1 au
RADIUS_COLUMN = 'h'  # set to your radius field, e.g. 'h', or 'hsoft'
RADIUS_UNIT = 'km'  # 'km' or 'au'
KM_PER_AU = 149_597_870.7
DEFAULT_RADIUS = 0.005   # used when radius data is missing/invalid

SMOOTH_INTERPOLATION = True
INTERPOLATION_MODE = 'BEZIER'  # 'BEZIER' or 'LINEAR'
HANDLE_MODE = 'AUTO_CLAMPED'

# -- Earth model config --------------------------------------------------------
EARTH_MODEL_PATH = r'C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code\BlenderConvert\TheEarth.blend'  # <-- update this
EARTH_MODEL_FORMAT = 'BLEND'   # 'BLEND', 'FBX', or 'OBJ'

# The exact object names inside your model file for each part (used when
# EARTH_COLLECTION_NAME is None). Check names in Blender's Outliner.
EARTH_PART_NAMES = ['Surface', 'Atmosphere', 'Clouds']  # <-- update these

# If set (e.g. 'The Earth'), append only this collection and parent all mesh
# objects under it to the trajectory empty. None = append by EARTH_PART_NAMES
# only (mutually exclusive with collection list).
EARTH_COLLECTION_NAME = None  # e.g. 'The Earth'

# Radius of the Earth surface mesh inside TheEarth.blend, in Blender units.
# Used only when EARTH_AUTO_REFERENCE_RADIUS is False, or when auto-measure
# fails (missing Surface mesh or invalid bounds).
EARTH_MODEL_REFERENCE_RADIUS_BU = 1.0
# If True, measure the imported Surface mesh world AABB and use half the
# largest edge as reference radius (see EARTH_CENTER_OBJECT_NAME).
EARTH_AUTO_REFERENCE_RADIUS = True
# Optional explicit target radius for imported Earth in Blender units.
# If None, the script uses get_body_radius(row) from the CSV.
EARTH_TARGET_RADIUS_BU = None
# Prefer this mesh as the centering reference when present, so clouds or
# atmosphere bounds do not skew the Earth's true center.
EARTH_CENTER_OBJECT_NAME = 'Surface'

EARTH_AUTO_CENTER = True   # Move combined bbox center onto the trajectory empty
EARTH_AUTO_SCALE = True    # Scale meshes to match CSV radius vs reference above

# -- Apophis model config (same workflow as Earth) ------------------------------
# Set APOPHIS_MODEL_PATH to your .blend (or use FBX/OBJ via APOPHIS_MODEL_FORMAT).
# APOPHIS_PART_NAMES should match mesh object names in the file's Outliner. If the
# mesh is still named e.g. 'Cube', either rename it or list that name here.
# APOPHIS_BLEND_APPEND_ALL_IF_UNMATCHED recovers when names don't match by loading
# every object in the file (only MESH objects are centered/scaled/parented).
APOPHIS_MODEL_PATH = (
    r'C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code\BlenderConvert\Apophis.blend'
)
APOPHIS_MODEL_FORMAT = 'BLEND'   # 'BLEND', 'FBX', or 'OBJ'
APOPHIS_PART_NAMES = ['Apophis']   # Use actual object names from Apophis.blend
APOPHIS_COLLECTION_NAME = None    # or e.g. 'Apophis' to append a collection
APOPHIS_BLEND_APPEND_ALL_IF_UNMATCHED = True
APOPHIS_MODEL_REFERENCE_RADIUS_BU = 1.0
APOPHIS_AUTO_REFERENCE_RADIUS = True
APOPHIS_TARGET_RADIUS_BU = .005  # None = use get_body_radius(row) from CSV
APOPHIS_CENTER_OBJECT_NAME = 'Apophis'
APOPHIS_AUTO_CENTER = True
APOPHIS_AUTO_SCALE = True
# -----------------------------------------------------------------------------
# Row order must match the multi-body PHANTOM CSV (one row per body, same order).
CSV_BODY_NAMES = [
    'Sun', 'Mercury', 'Venus', 'Earth', 'Moon',
    'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Apophis',
]
# Only create/keyframe these CSV row indices (Sun=0, Earth=3, Apophis=10).
IMPORT_CSV_INDICES = frozenset(
    {
        CSV_BODY_NAMES.index('Sun'),
        CSV_BODY_NAMES.index('Earth'),
        CSV_BODY_NAMES.index('Apophis'),
    }
)

EARTH_INDEX = CSV_BODY_NAMES.index('Earth')
APOPHIS_INDEX = CSV_BODY_NAMES.index('Apophis')


@dataclass
class BodyModelConfig:
    """Settings for importing a detailed mesh (blend/FBX/OBJ) parented to a trajectory Empty."""
    body_label: str
    model_path: str
    model_format: str  # 'BLEND', 'FBX', 'OBJ'
    part_names: list
    collection_name: Optional[str]
    model_reference_radius_bu: float
    auto_reference_radius: bool
    target_radius_bu: Optional[float]
    center_object_name: str
    auto_center: bool
    auto_scale: bool
    # If no part_names match inside a .blend, append every object (meshes only are laid out/parented).
    blend_append_all_objects_if_unmatched: bool = False


EARTH_MODEL_CONFIG = BodyModelConfig(
    body_label='Earth',
    model_path=EARTH_MODEL_PATH,
    model_format=EARTH_MODEL_FORMAT,
    part_names=list(EARTH_PART_NAMES),
    collection_name=EARTH_COLLECTION_NAME,
    model_reference_radius_bu=EARTH_MODEL_REFERENCE_RADIUS_BU,
    auto_reference_radius=EARTH_AUTO_REFERENCE_RADIUS,
    target_radius_bu=EARTH_TARGET_RADIUS_BU,
    center_object_name=EARTH_CENTER_OBJECT_NAME,
    auto_center=EARTH_AUTO_CENTER,
    auto_scale=EARTH_AUTO_SCALE,
)

APOPHIS_MODEL_CONFIG = BodyModelConfig(
    body_label='Apophis',
    model_path=APOPHIS_MODEL_PATH,
    model_format=APOPHIS_MODEL_FORMAT,
    part_names=list(APOPHIS_PART_NAMES),
    collection_name=APOPHIS_COLLECTION_NAME,
    model_reference_radius_bu=APOPHIS_MODEL_REFERENCE_RADIUS_BU,
    auto_reference_radius=APOPHIS_AUTO_REFERENCE_RADIUS,
    target_radius_bu=APOPHIS_TARGET_RADIUS_BU,
    center_object_name=APOPHIS_CENTER_OBJECT_NAME,
    auto_center=APOPHIS_AUTO_CENTER,
    auto_scale=APOPHIS_AUTO_SCALE,
    blend_append_all_objects_if_unmatched=APOPHIS_BLEND_APPEND_ALL_IF_UNMATCHED,
)

MODEL_BODY_CONFIG_BY_INDEX = {
    EARTH_INDEX: EARTH_MODEL_CONFIG,
    APOPHIS_INDEX: APOPHIS_MODEL_CONFIG,
}

csv_files = sorted(glob.glob(os.path.join(CSV_DIR, '*.csv')))


def get_body_radius(row):
    """Return radius in AU-scaled Blender units with safe fallbacks."""
    for column in (RADIUS_COLUMN, 'Reff', 'h', 'hsoft'):
        if column in row and pd.notna(row[column]):
            try:
                radius = float(row[column])
                if radius > 0:
                    if RADIUS_UNIT.lower() == 'km':
                        radius = radius / KM_PER_AU
                    return radius * SCALE
            except (TypeError, ValueError):
                continue
    return DEFAULT_RADIUS


def smooth_location_fcurves(obj):
    """Apply interpolation settings to an object's location F-curves."""
    if not obj.animation_data or not obj.animation_data.action:
        return

    action = obj.animation_data.action
    fcurves = []

    legacy_fcurves = getattr(action, 'fcurves', None)
    if legacy_fcurves is not None:
        fcurves.extend(list(legacy_fcurves))
    else:
        for layer in getattr(action, 'layers', []):
            for strip in getattr(layer, 'strips', []):
                for channelbag in getattr(strip, 'channelbags', []):
                    fcurves.extend(list(getattr(channelbag, 'fcurves', [])))

    for fcurve in fcurves:
        if fcurve.data_path != 'location':
            continue
        for key in fcurve.keyframe_points:
            key.interpolation = INTERPOLATION_MODE
            if INTERPOLATION_MODE == 'BEZIER':
                key.handle_left_type = HANDLE_MODE
                key.handle_right_type = HANDLE_MODE


def _link_object_to_collection(obj, coll):
    try:
        coll.objects.link(obj)
    except RuntimeError:
        pass


def _parent_part_to_empty(obj, empty_obj):
    """
    Parent obj to empty_obj while preserving the current world transform.

    This is important because we may have already centered/scaled obj in world
    space before parenting; zeroing location would destroy those transforms.
    """
    mw = obj.matrix_world.copy()

    obj.parent = empty_obj
    obj.matrix_parent_inverse = empty_obj.matrix_world.inverted()
    obj.matrix_world = mw


def _object_base_name(name):
    """Strip Blender's numeric suffix (.001) for comparing to expected names."""
    if '.' in name:
        head, tail = name.rsplit('.', 1)
        if tail.isdigit():
            return head
    return name


def _blend_object_names_for_append(library_object_names, cfg):
    """
    Pick which object datablock names to append from a .blend.
    Tries exact name, case-insensitive name, then base name (no .001) match.
    If still none and blend_append_all_objects_if_unmatched, append all names.
    """
    names = list(library_object_names)
    if not names:
        print(
            f'  ERROR: {cfg.body_label}: .blend contains no object datablocks: {cfg.model_path}'
        )
        return []
    part_set = set(cfg.part_names)
    chosen = [n for n in names if n in part_set]
    if chosen:
        return chosen
    part_lower = {p.lower() for p in cfg.part_names}
    chosen = [n for n in names if n.lower() in part_lower]
    if chosen:
        print(
            f'  NOTE: {cfg.body_label}: matched object names by case-insensitive part_names; '
            f'consider renaming in the .blend to match exactly: {chosen!r}'
        )
        return chosen
    base_parts = {_object_base_name(p) for p in cfg.part_names}
    chosen = [n for n in names if _object_base_name(n) in base_parts]
    if chosen:
        return chosen
    if cfg.blend_append_all_objects_if_unmatched:
        print(
            f'  WARNING: {cfg.body_label}: no object matched part_names={cfg.part_names!r}. '
            f'Appending all objects from blend (meshes only will be parented). '
            f'Available: {sorted(names)}'
        )
        return list(names)
    print(
        f'  ERROR: {cfg.body_label}: no objects matched part_names={cfg.part_names!r}. '
        f'Available in blend: {sorted(names)}'
    )
    return []


def _combined_mesh_bbox_center_world(mesh_objs):
    """World-space center of the axis-aligned bounding box union of mesh objects."""
    if not mesh_objs:
        return Vector((0.0, 0.0, 0.0))
    min_co = Vector((1e30, 1e30, 1e30))
    max_co = Vector((-1e30, -1e30, -1e30))
    for obj in mesh_objs:
        if obj.type != 'MESH':
            continue
        mat = obj.matrix_world
        for corner in obj.bound_box:
            w = mat @ Vector(corner)
            min_co.x = min(min_co.x, w.x)
            min_co.y = min(min_co.y, w.y)
            min_co.z = min(min_co.z, w.z)
            max_co.x = max(max_co.x, w.x)
            max_co.y = max(max_co.y, w.y)
            max_co.z = max(max_co.z, w.z)
    return (min_co + max_co) * 0.5


def _body_center_reference_world(mesh_objs, cfg):
    """
    Prefer the mesh named cfg.center_object_name as the centering reference;
    fall back to the combined mesh bounds when that mesh is unavailable.
    """
    for obj in mesh_objs:
        if _object_base_name(obj.name) == cfg.center_object_name:
            return _combined_mesh_bbox_center_world([obj])
    return _combined_mesh_bbox_center_world(mesh_objs)


def _body_surface_mesh(mesh_objs, cfg):
    """Return the mesh object used as radius/center reference, or None."""
    for obj in mesh_objs:
        if obj.type == 'MESH' and _object_base_name(obj.name) == cfg.center_object_name:
            return obj
    mesh_only = [o for o in mesh_objs if o.type == 'MESH']
    if len(mesh_only) == 1:
        return mesh_only[0]
    return None


def _mesh_world_aabb_half_max_extent(obj):
    """
    Approximate "radius" from world-space AABB: half of the longest box edge.
    Uses evaluated depsgraph so modifiers affect bound_box when applicable.
    """
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(depsgraph)
    except RuntimeError:
        ev = obj
    mat = ev.matrix_world
    min_co = Vector((1e30, 1e30, 1e30))
    max_co = Vector((-1e30, -1e30, -1e30))
    for corner in ev.bound_box:
        w = mat @ Vector(corner)
        min_co.x = min(min_co.x, w.x)
        min_co.y = min(min_co.y, w.y)
        min_co.z = min(min_co.z, w.z)
        max_co.x = max(max_co.x, w.x)
        max_co.y = max(max_co.y, w.y)
        max_co.z = max(max_co.z, w.z)
    extent = max_co - min_co
    return max(extent.x, extent.y, extent.z) * 0.5


def _body_reference_radius_bu(mesh_objs, cfg):
    """
    Return (radius, source_string) for scaling denominator.
    source_string is 'measured', 'manual_constant', or 'constant_fallback'.
    """
    if not cfg.auto_reference_radius:
        return cfg.model_reference_radius_bu, 'manual_constant'

    surf = _body_surface_mesh(mesh_objs, cfg)
    if surf is not None:
        measured = _mesh_world_aabb_half_max_extent(surf)
        if measured > 0:
            return measured, 'measured'
        print(
            '  WARNING: Auto reference radius from center mesh AABB is invalid; '
            f'using model_reference_radius_bu={cfg.model_reference_radius_bu}.'
        )
    else:
        print(
            f'  WARNING: No mesh named "{cfg.center_object_name}" in import; '
            f'using model_reference_radius_bu={cfg.model_reference_radius_bu}.'
        )
    return cfg.model_reference_radius_bu, 'constant_fallback'


def _prepare_body_meshes_layout(mesh_objs, empty_obj, row, cfg):
    """
    Translate combined bbox center to the empty and uniformly scale about the
    empty to match get_body_radius(row). Call before parenting.
    """
    if not mesh_objs:
        return
    E = empty_obj.matrix_world.translation.copy()
    target_radius = (
        cfg.target_radius_bu
        if cfg.target_radius_bu is not None
        else get_body_radius(row)
    )
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
            scale_factor = target_radius / reference_radius
            # True uniform scale on X/Y/Z about the empty position.
            S = (
                Matrix.Translation(E)
                @ Matrix.Diagonal((scale_factor, scale_factor, scale_factor, 1.0))
                @ Matrix.Translation(-E)
            )
            for obj in mesh_objs:
                obj.matrix_world = S @ obj.matrix_world
        else:
            print(
                f'  WARNING: {cfg.body_label} reference radius must be > 0; '
                'skipping mesh scale.'
            )

    if scale_factor is not None:
        sf_str = f'{scale_factor:.6g}'
    elif cfg.auto_scale:
        sf_str = 'skipped (invalid reference)'
    else:
        sf_str = f'off (auto_scale=False)'

    ref_detail = (
        f'reference_radius={reference_radius:.6g} ({ref_source})'
        if reference_radius > 0
        else f'reference_radius=invalid ({ref_source})'
    )

    print(
        f'  {cfg.body_label} layout: target_radius={target_radius:.6g}, '
        f'{ref_detail}, '
        f'scale_factor={sf_str}, '
        f'center_reference_before_shift={tuple(C)}'
    )


def import_body_model(empty_obj, row, cfg):
    """
    Import a body model file (blend / FBX / OBJ) and parent mesh parts to empty_obj.
    row: first-frame CSV row for this body (used for radius / layout when target is None).
    """
    before = set(bpy.data.objects.keys())
    parented_count = 0
    blend_appended = []

    if cfg.model_format == 'BLEND':
        blend_path = os.path.abspath(os.path.normpath(cfg.model_path))
        if not os.path.isfile(blend_path):
            print(
                f'  ERROR: {cfg.body_label}: blend file not found (check APOPHIS_MODEL_PATH / '
                f'EARTH_MODEL_PATH): {blend_path}'
            )
            print(
                f'Parented {parented_count} {cfg.body_label} model part(s) '
                f'to "{empty_obj.name}".'
            )
        else:
            use_collection = bool(cfg.collection_name)
            with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
                if use_collection:
                    if cfg.collection_name in data_from.collections:
                        data_to.collections = [cfg.collection_name]
                    else:
                        print(
                            f'  WARNING: Collection "{cfg.collection_name}" '
                            f'not found in {blend_path}'
                        )
                        print(
                            f'  Available collections: {sorted(data_from.collections)}'
                        )
                        data_to.collections = []
                    data_to.objects = []
                else:
                    to_load = _blend_object_names_for_append(data_from.objects, cfg)
                    data_to.objects = to_load
                    data_to.collections = []

            coll = bpy.context.collection
            body_col = next(
                (c for c in data_to.collections if c is not None),
                None,
            )
            if use_collection and body_col is not None:
                coll.children.link(body_col)
                for obj in list(body_col.all_objects):
                    if obj.type == 'MESH':
                        blend_appended.append(obj)
                _prepare_body_meshes_layout(blend_appended, empty_obj, row, cfg)
                for obj in blend_appended:
                    _parent_part_to_empty(obj, empty_obj)
                    parented_count += 1
            elif use_collection and body_col is None:
                print(
                    f'  ERROR: {cfg.body_label}: collection append failed; no meshes linked.'
                )
            elif not use_collection:
                appended = [obj for obj in data_to.objects if obj is not None]
                for obj in appended:
                    _link_object_to_collection(obj, coll)
                mesh_objs = [o for o in appended if o.type == 'MESH']
                if not mesh_objs and appended:
                    print(
                        f'  WARNING: {cfg.body_label}: appended objects include no MESH '
                        f'(types: {[o.type for o in appended]}). Nothing to parent.'
                    )
                blend_appended = mesh_objs
                _prepare_body_meshes_layout(blend_appended, empty_obj, row, cfg)
                for obj in blend_appended:
                    _parent_part_to_empty(obj, empty_obj)
                    parented_count += 1

            print(
                f'Parented {parented_count} {cfg.body_label} model part(s) '
                f'to "{empty_obj.name}".'
            )
            if use_collection:
                if parented_count == 0:
                    print('  WARNING: No mesh objects were parented from the collection.')
            else:
                imported_bases = {_object_base_name(o.name) for o in blend_appended}
                expected = set(cfg.part_names)
                if parented_count < len(cfg.part_names) or imported_bases != expected:
                    if blend_appended:
                        print(
                            '  NOTE: Imported mesh base names differ from part_names '
                            '(expected when using fallback append); '
                            f'got {sorted(imported_bases)}.'
                        )
                    elif cfg.blend_append_all_objects_if_unmatched:
                        pass
                    else:
                        print('  WARNING: Some expected part names were not imported or were renamed.')
                        print(f'  Expected (base names): {sorted(expected)}')
                        print(f'  Got (base names):      {sorted(imported_bases)}')

    elif cfg.model_format == 'FBX':
        bpy.ops.import_scene.fbx(filepath=cfg.model_path)
        after = set(bpy.data.objects.keys())
        new_objects = after - before
        body_meshes = []
        for obj_name in new_objects:
            if obj_name not in cfg.part_names:
                continue
            obj = bpy.data.objects.get(obj_name)
            if obj is None or obj.type != 'MESH':
                continue
            body_meshes.append(obj)
        _prepare_body_meshes_layout(body_meshes, empty_obj, row, cfg)
        for obj in body_meshes:
            _parent_part_to_empty(obj, empty_obj)
            parented_count += 1
        print(
            f'Parented {parented_count} {cfg.body_label} model part(s) '
            f'to "{empty_obj.name}".'
        )
        if parented_count < len(cfg.part_names):
            print('  WARNING: Some expected part names were not found in the import.')
            print(f'  Expected: {cfg.part_names}')
            print(f'  Got:      {list(new_objects)}')

    elif cfg.model_format == 'OBJ':
        bpy.ops.wm.obj_import(filepath=cfg.model_path)
        after = set(bpy.data.objects.keys())
        new_objects = after - before
        body_meshes = []
        for obj_name in new_objects:
            if obj_name not in cfg.part_names:
                continue
            obj = bpy.data.objects.get(obj_name)
            if obj is None or obj.type != 'MESH':
                continue
            body_meshes.append(obj)
        _prepare_body_meshes_layout(body_meshes, empty_obj, row, cfg)
        for obj in body_meshes:
            _parent_part_to_empty(obj, empty_obj)
            parented_count += 1
        print(
            f'Parented {parented_count} {cfg.body_label} model part(s) '
            f'to "{empty_obj.name}".'
        )
        if parented_count < len(cfg.part_names):
            print('  WARNING: Some expected part names were not found in the import.')
            print(f'  Expected: {cfg.part_names}')
            print(f'  Got:      {list(new_objects)}')


def import_earth_model(empty_obj, earth_row):
    """Backward-compatible alias: Earth model via EARTH_MODEL_CONFIG."""
    import_body_model(empty_obj, earth_row, EARTH_MODEL_CONFIG)


# -- First pass: create one object per body ------------------------------------
first_df = pd.read_csv(csv_files[0])

for i, row in first_df.iterrows():
    if i not in IMPORT_CSV_INDICES:
        continue
    name = CSV_BODY_NAMES[i] if i < len(CSV_BODY_NAMES) else f'Body_{i}'
    start_loc = (
        row['x_au'] * SCALE,
        row['y_au'] * SCALE,
        row['z_au'] * SCALE,
    )

    model_cfg = MODEL_BODY_CONFIG_BY_INDEX.get(i)
    if model_cfg is not None:
        # Empty drives trajectory; imported meshes are parented (Earth, Apophis, ...)
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=start_loc)
        obj = bpy.context.object
        obj.name = name
        import_body_model(obj, row, model_cfg)
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=get_body_radius(row), location=start_loc
        )
        obj = bpy.context.object
        obj.name = name

# -- Second pass: keyframe positions across all timesteps ----------------------
for frame_num, csv_file in enumerate(csv_files, start=1):
    df = pd.read_csv(csv_file)
    bpy.context.scene.frame_set(frame_num)

    for i, row in df.iterrows():
        if i not in IMPORT_CSV_INDICES:
            continue
        name = CSV_BODY_NAMES[i] if i < len(CSV_BODY_NAMES) else f'Body_{i}'
        obj = bpy.data.objects.get(name)
        if obj:
            obj.location = (
                row['x_au'] * SCALE,
                row['y_au'] * SCALE,
                row['z_au'] * SCALE,
            )
            obj.keyframe_insert(data_path='location', frame=frame_num)

# -- Third pass: smooth all F-curves -------------------------------------------
if SMOOTH_INTERPOLATION:
    for i in sorted(IMPORT_CSV_INDICES):
        if i >= len(first_df):
            continue
        name = CSV_BODY_NAMES[i] if i < len(CSV_BODY_NAMES) else f'Body_{i}'
        obj = bpy.data.objects.get(name)
        if obj:
            smooth_location_fcurves(obj)

print('Done - press Space to play the animation.')