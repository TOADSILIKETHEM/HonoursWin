import bpy
import pandas as pd
import glob
import os

# -- Configuration -------------------------------------------------------------
CSV_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/ShortCSVlist/'
SCALE = 5000.0   # 1 Blender unit = 1 au
RADIUS_COLUMN = 'h'  # set to your radius field, e.g. 'h', or 'hsoft'
RADIUS_UNIT = 'km'  # 'km' or 'au'
KM_PER_AU = 149_597_870.7
DEFAULT_RADIUS = 0.005   # used when radius data is missing/invalid

SMOOTH_INTERPOLATION = True
INTERPOLATION_MODE = 'BEZIER'  # 'BEZIER' or 'LINEAR'
HANDLE_MODE = 'AUTO_CLAMPED'   # Helps reduce overshoot on curved paths
# -----------------------------------------------------------------------------

# Body names in the order they appear in your dump files
BODY_NAMES = ['Sun', 'Mercury', 'Venus', 'Earth', 'Moon',
              'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Apophis']

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

    # Blender versions before the slotted action system expose action.fcurves
    legacy_fcurves = getattr(action, 'fcurves', None)
    if legacy_fcurves is not None:
        fcurves.extend(list(legacy_fcurves))
    else:
        # Newer Blender versions store f-curves inside action layer/strip channel bags
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


# -- First pass: create one sphere per body ------------------------------------
first_df = pd.read_csv(csv_files[0])

for i, row in first_df.iterrows():
    name = BODY_NAMES[i] if i < len(BODY_NAMES) else f'Body_{i}'
    bpy.ops.mesh.primitive_uv_sphere_add(radius=get_body_radius(row), location=(
        row['x_au'] * SCALE,
        row['y_au'] * SCALE,
        row['z_au'] * SCALE
    ))
    obj = bpy.context.object
    obj.name = name

# -- Second pass: keyframe positions across all timesteps ----------------------
for frame_num, csv_file in enumerate(csv_files, start=1):
    df = pd.read_csv(csv_file)
    bpy.context.scene.frame_set(frame_num)

    for i, row in df.iterrows():
        name = BODY_NAMES[i] if i < len(BODY_NAMES) else f'Body_{i}'
        obj = bpy.data.objects.get(name)
        if obj:
            obj.location = (
                row['x_au'] * SCALE,
                row['y_au'] * SCALE,
                row['z_au'] * SCALE
            )
            obj.keyframe_insert(data_path='location', frame=frame_num)

if SMOOTH_INTERPOLATION:
    for i in range(len(first_df)):
        name = BODY_NAMES[i] if i < len(BODY_NAMES) else f'Body_{i}'
        obj = bpy.data.objects.get(name)
        if obj:
            smooth_location_fcurves(obj)

print('Done - press Space to play the animation.')
