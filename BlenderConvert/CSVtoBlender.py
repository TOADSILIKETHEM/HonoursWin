import bpy
import pandas as pd
import glob
import os

# ── Configuration ─────────────────────────────────────────────────────────────
CSV_DIR     = "c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/csv_output/"
SCALE       = 1.0   # 1 Blender unit = 1 au
RADIUS_COLUMN = "Reff"  # set to your radius field, e.g. "Reff", "h", or "hsoft"
DEFAULT_RADIUS = 0.05   # used when radius data is missing/invalid
# ─────────────────────────────────────────────────────────────────────────────

# Body names in the order they appear in your dump files
BODY_NAMES = ["Sun", "Mercury", "Venus", "Earth", "Moon",
              "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Unknown"]

csv_files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))


def get_body_radius(row):
    """Return radius in simulation units with safe fallbacks."""
    for column in (RADIUS_COLUMN, "Reff", "h", "hsoft"):
        if column in row and pd.notna(row[column]):
            try:
                radius = float(row[column])
                if radius > 0:
                    return radius * SCALE
            except (TypeError, ValueError):
                continue
    return DEFAULT_RADIUS

# ── First pass: create one sphere per body ────────────────────────────────────
first_df = pd.read_csv(csv_files[0])

for i, row in first_df.iterrows():
    name = BODY_NAMES[i] if i < len(BODY_NAMES) else f"Body_{i}"
    bpy.ops.mesh.primitive_uv_sphere_add(radius=get_body_radius(row), location=(
        row['x_au'] * SCALE,
        row['y_au'] * SCALE,
        row['z_au'] * SCALE
    ))
    obj = bpy.context.object
    obj.name = name

# ── Second pass: keyframe positions across all timesteps ──────────────────────
for frame_num, csv_file in enumerate(csv_files, start=1):
    df = pd.read_csv(csv_file)
    bpy.context.scene.frame_set(frame_num)

    for i, row in df.iterrows():
        name = BODY_NAMES[i] if i < len(BODY_NAMES) else f"Body_{i}"
        obj = bpy.data.objects.get(name)
        if obj:
            obj.location = (
                row['x_au'] * SCALE,
                row['y_au'] * SCALE,
                row['z_au'] * SCALE
            )
            obj.keyframe_insert(data_path="location", frame=frame_num)

print("Done — press Space to play the animation.")