import bpy
import mathutils
import pandas as pd
import glob
import os

# ── Configuration ─────────────────────────────────────────────────────────────
# Path to the dem_grains_output/ folder produced by DEMtoCSV.py.
# OBJ-cropped opposite_near_h breakup, 5 min dumps (~1297 frames): fine_dt batch.
GRAINS_CSV_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/torque_align_obj_fine_dt/run_0001_grains_output/'

# Path to the bodies output folder — filenames match GRAINS_CSV_DIR.
# Used to read the Sun and Apophis absolute positions and animate the Sun lamp.
# Set to '' or a nonexistent path to skip the Sun lamp entirely.
BODIES_CSV_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/torque_align_obj_fine_dt/run_0001_bodies_output/'

# Sun lamp settings.
# SUN_LAMP_ENERGY: irradiance in Watts — scale to taste for your render setup.
# SUN_LAMP_ANGLE: angular radius of the Sun disc in radians (controls shadow softness).
#   0.00931 rad ≈ 0.53°, the Sun's angular radius as seen from ~1 AU away.
SUN_LAMP_ENERGY = 10.0
SUN_LAMP_ANGLE  = 0.00931

# Interpolation applied to all grain and Sun lamp F-curves between keyframes.
SMOOTH_INTERPOLATION = True
INTERPOLATION_MODE   = 'BEZIER'   # 'BEZIER' or 'LINEAR'
HANDLE_MODE          = 'AUTO_CLAMPED'

# Material colour for the rubble-pile grains (RGBA, 0-1).
GRAIN_COLOR = (0.35, 0.30, 0.25, 1.0)

# Name of the Blender collection that will hold all grain sphere objects.
# Created automatically if it does not already exist.
GRAIN_COLLECTION_NAME = 'DEM_Grains'
# ─────────────────────────────────────────────────────────────────────────────
# COORDINATE NOTE
# ───────────────
# x_vis / y_vis / z_vis are body-frame positions relative to the Apophis
# centre of mass, multiplied by GRAIN_VIS_SCALE (default 50, set in DEMtoCSV.py).
# They are NOT in AU — do not multiply by a solar-system SCALE here.
# Reff_vis is the grain radius in the same scaled units.
#
# The Sun direction is computed from the bodies CSV using absolute km positions:
#   sun_dir = (sun_km - apophis_com_km).normalised()
# Because the body frame is only translated (not rotated) relative to the solar
# system frame, this direction vector is valid in both frames and is used
# directly to orient the Sun lamp.
# ─────────────────────────────────────────────────────────────────────────────

csv_files = sorted(glob.glob(os.path.join(GRAINS_CSV_DIR, '*.csv')))

if not csv_files:
    raise FileNotFoundError(
        f'No CSVs found in {GRAINS_CSV_DIR}\n'
        'Run CSVconvert/DEMtoCSV.py first to generate dem_grains_output/.'
    )

print(f'Found {len(csv_files)} grain CSV(s).')

# Check bodies folder once up front — Sun lamp is skipped if it is missing.
_bodies_available = os.path.isdir(BODIES_CSV_DIR)
if not _bodies_available:
    print(
        f'WARNING: BODIES_CSV_DIR not found ({BODIES_CSV_DIR})\n'
        '  Sun lamp will be skipped. Set BODIES_CSV_DIR to dem_bodies_output/ to enable it.'
    )


def _bodies_csv_for(grains_path):
    """Return the matching bodies CSV path, or None if it does not exist."""
    if not _bodies_available:
        return None
    p = os.path.join(BODIES_CSV_DIR, os.path.basename(grains_path))
    return p if os.path.exists(p) else None


# ── Shared material ───────────────────────────────────────────────────────────
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


# ── Create Sun lamp ───────────────────────────────────────────────────────────
# A Blender SUN lamp emits infinite parallel rays — position is irrelevant,
# only rotation matters.  We orient its local -Z axis toward the Sun each
# frame so the lighting angle matches the physical Sun direction exactly.
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


# ── Create grain collection ───────────────────────────────────────────────────
grain_col = bpy.data.collections.get(GRAIN_COLLECTION_NAME)
if grain_col is None:
    grain_col = bpy.data.collections.new(GRAIN_COLLECTION_NAME)
    bpy.context.scene.collection.children.link(grain_col)

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

    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    grain_col.objects.link(obj)

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

print('Spheres created.')

# ── Second pass: keyframe grain positions and Sun lamp rotation ───────────────
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

    # Orient the Sun lamp using the Sun–Apophis direction from the bodies CSV.
    if sun_lamp_obj is not None:
        bodies_path = _bodies_csv_for(csv_file)
        if bodies_path:
            bdf     = pd.read_csv(bodies_path)
            sun_row = bdf.loc[bdf['name'] == 'Sun']
            apo_row = bdf.loc[bdf['name'] == 'Apophis']
            if not sun_row.empty and not apo_row.empty:
                sun_km  = sun_row[['x_km', 'y_km', 'z_km']].values[0]
                apo_km  = apo_row[['x_km', 'y_km', 'z_km']].values[0]
                sun_rel = sun_km - apo_km   # vector from Apophis to Sun (km)
                sun_dir = mathutils.Vector(sun_rel.tolist()).normalized()
                # Track local -Z toward the Sun (SUN lamp emits along -Z by default).
                rot = sun_dir.to_track_quat('-Z', 'Y').to_euler()
                sun_lamp_obj.rotation_euler = rot
                sun_lamp_obj.keyframe_insert(
                    data_path='rotation_euler', frame=frame_num
                )

# ── Third pass: smooth F-curves ───────────────────────────────────────────────
if SMOOTH_INTERPOLATION:
    print('Smoothing F-curves ...')
    for gid in range(n_grains):
        obj = bpy.data.objects.get(f'DEM_Grain_{gid:03d}')
        if obj:
            _smooth_fcurves(obj, 'location')
    if sun_lamp_obj is not None:
        _smooth_fcurves(sun_lamp_obj, 'rotation_euler')

print(
    f'Done — {n_grains} DEM grains animated over {len(csv_files)} frame(s).\n'
    'Positions are in Apophis body frame (not solar-system AU scale).\n'
    'Sun lamp "DEM_SunLight" direction is keyframed from physical PHANTOM positions.\n'
    'Press Space to play. Tune SUN_LAMP_ENERGY / SUN_LAMP_ANGLE at the top as needed.'
)
