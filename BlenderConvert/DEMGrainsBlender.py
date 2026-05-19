import bpy
import pandas as pd
import glob
import os

# ── Configuration ─────────────────────────────────────────────────────────────
# Path to the dem_grains_output/ folder produced by DEMtoCSV.py.
# Each CSV contains one row per DEM grain with x_vis/y_vis/z_vis columns
# (body-frame positions pre-scaled for Blender) and Reff_vis (sphere radius).
GRAINS_CSV_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/dem_grains_output/'

# Interpolation applied to all grain F-curves between keyframes.
SMOOTH_INTERPOLATION = True
INTERPOLATION_MODE   = 'BEZIER'   # 'BEZIER' or 'LINEAR'
HANDLE_MODE          = 'AUTO_CLAMPED'

# Material colour for the rubble-pile grains (RGBA, 0-1).
# Change to taste — a warm grey works well for a rocky asteroid.
GRAIN_COLOR = (0.35, 0.30, 0.25, 1.0)
# ─────────────────────────────────────────────────────────────────────────────
# COORDINATE NOTE
# ───────────────
# x_vis / y_vis / z_vis are body-frame positions relative to the Apophis
# centre of mass, multiplied by GRAIN_VIS_SCALE (default 50, set in DEMtoCSV.py).
# They are NOT in AU — do not multiply by a solar-system SCALE here.
# Reff_vis is the grain radius in the same scaled units.
#
# The visualisation is not to physical scale by design: at true scale, all 64
# grains would collapse to a single Blender coordinate due to float32 limits.
# ─────────────────────────────────────────────────────────────────────────────

csv_files = sorted(glob.glob(os.path.join(GRAINS_CSV_DIR, '*.csv')))

if not csv_files:
    raise FileNotFoundError(
        f'No CSVs found in {GRAINS_CSV_DIR}\n'
        'Run CSVconvert/DEMtoCSV.py first to generate dem_grains_output/.'
    )

print(f'Found {len(csv_files)} grain CSV(s).')

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


def smooth_location_fcurves(obj):
    if not obj.animation_data or not obj.animation_data.action:
        return
    action   = obj.animation_data.action
    fcurves  = []
    legacy   = getattr(action, 'fcurves', None)
    if legacy is not None:
        fcurves.extend(list(legacy))
    else:
        for layer in getattr(action, 'layers', []):
            for strip in getattr(layer, 'strips', []):
                for bag in getattr(strip, 'channelbags', []):
                    fcurves.extend(list(getattr(bag, 'fcurves', [])))
    for fc in fcurves:
        if fc.data_path != 'location':
            continue
        for kp in fc.keyframe_points:
            kp.interpolation = INTERPOLATION_MODE
            if INTERPOLATION_MODE == 'BEZIER':
                kp.handle_left_type  = HANDLE_MODE
                kp.handle_right_type = HANDLE_MODE


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

print(f'Spheres created.')

# ── Second pass: keyframe positions across all CSV frames ─────────────────────
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

# ── Third pass: smooth F-curves ───────────────────────────────────────────────
if SMOOTH_INTERPOLATION:
    print('Smoothing F-curves ...')
    for gid in range(n_grains):
        obj = bpy.data.objects.get(f'DEM_Grain_{gid:03d}')
        if obj:
            smooth_location_fcurves(obj)

print(
    f'Done — {n_grains} DEM grains animated over {len(csv_files)} frame(s).\n'
    'Positions are in Apophis body frame (not solar-system AU scale).\n'
    'Press Space to play. Adjust GRAIN_COLOR or SMOOTH_INTERPOLATION at the top as needed.'
)
