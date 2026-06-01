import bpy

# --- Configure these ---
SOURCE_NAME = "DEM_Grain_521"          # The grain with the texture + subdivision
GRAIN_PREFIX = "DEM_Grain_"            # Prefix shared by all grain objects
# ----------------------

source = bpy.data.objects[SOURCE_NAME]

targets = [
    obj for obj in bpy.data.objects
    if obj.name.startswith(GRAIN_PREFIX) and obj.name != SOURCE_NAME
]

for obj in targets:
    # --- Copy material slots ---
    obj.data.materials.clear()
    for mat in source.data.materials:
        obj.data.materials.append(mat)

    # --- Copy modifiers ---
    # Remove existing modifiers on target first
    obj.modifiers.clear()

    for src_mod in source.modifiers:
        new_mod = obj.modifiers.new(name=src_mod.name, type=src_mod.type)
        # Copy all modifier properties
        for prop in src_mod.bl_rna.properties:
            if prop.identifier in ('rna_type', 'name', 'type'):
                continue
            try:
                setattr(new_mod, prop.identifier, getattr(src_mod, prop.identifier))
            except (AttributeError, TypeError):
                pass

print(f"Done: applied to {len(targets)} objects")